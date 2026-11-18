"""Peer-to-peer transport for agent-hosted spaces over iroh.

The host accepts QUIC connections addressed to its persistent endpoint key and
forwards each bidirectional stream to its loopback collaboration port. A member
binds the same loopback port number on its own computer, so HTTP Host and
Origin are byte-identical to local access and the shared boundary checks,
HTTP/MCP operations and WebSocket events stay unchanged.

Only the endpoint id (a public key) is shared in invitations; addresses come
from iroh discovery, with relay fallback when no direct path exists.
"""
import asyncio
from contextlib import nullcontext
import ipaddress
import json
import logging
import re
import threading
import time
import urllib.request
from urllib.parse import urlsplit

# Wire identifier from before the rename to Coopagents; kept so 0.6 hosts and members still connect.
ALPN = b'crewmesh/space/1'
CHUNK = 65536
MAX_CONNECTIONS = 64
MAX_STREAMS = 64
ENDPOINT_ID = re.compile(r'[0-9a-f]{64}')

log = logging.getLogger(__name__)
_loop = None
_loop_lock = threading.Lock()
_tasks = set()  # asyncio keeps only weak references to running tasks


def _spawn(coro):
    task = asyncio.ensure_future(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _iroh():
    try:
        import iroh
    except ImportError as error:
        raise RuntimeError('Peer-to-peer mode requires the space extra (iroh)') from error
    return iroh


def _background_loop():
    """One event loop per process; iroh's bindings accept a single loop."""
    global _loop
    with _loop_lock:
        if _loop is None:
            iroh = _iroh()
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run():
                asyncio.set_event_loop(loop)
                iroh.iroh_ffi.uniffi_set_event_loop(loop)
                ready.set()
                loop.run_forever()

            threading.Thread(target=run, name='coopagents-p2p', daemon=True).start()
            ready.wait()
            _loop = loop
        return _loop


def _run(coro, timeout):
    return asyncio.run_coroutine_threadsafe(coro, _background_loop()).result(timeout)


class SpaceUnreachableError(ValueError):
    """The space could not be reached over its transport.

    Raised for a failed peer-to-peer dial and for a busy local port. The
    identity was never checked, so this must not be reported as an identity
    mismatch; it stays a ValueError so existing ValueError handling is
    preserved.
    """


def validate_endpoint_id(value):
    if not isinstance(value, str) or not ENDPOINT_ID.fullmatch(value):
        raise ValueError('Peer-to-peer endpoint id must be 64 lowercase hex characters')
    return value


MAX_RELAY_URLS = 4
MAX_RELAY_URL_LENGTH = 2048
# The v1 invitation code body is capped at 4096 base64 characters (~3072 JSON
# bytes); the aggregate bound keeps every accepted relay list decodable with
# headroom for the descriptor's other fields.
MAX_RELAY_URLS_TOTAL_LENGTH = 1024
_HOST_LABEL = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?')


def _loopback_host(hostname):
    if hostname == 'localhost':
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _valid_hostname(hostname):
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    if not hostname or len(hostname) > 253:
        return False
    labels = hostname[:-1].split('.') if hostname.endswith('.') else hostname.split('.')
    return all(_HOST_LABEL.fullmatch(label) and len(label) <= 63 for label in labels)


def validate_relay_urls(value):
    """Relay URLs for a self-hosted relay: 1-4 bare origins.

    Plain HTTP is accepted only for loopback relays used in local development
    and tests; a relay on any other host must be HTTPS. Credentials, queries,
    fragments and paths below the root are rejected: the relay serves its own
    fixed paths, so anything more is a misconfigured URL. The authority is
    validated up front — a host or port iroh cannot consume is rejected here,
    not deferred to endpoint setup after the URL has been saved.
    """
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_RELAY_URLS:
        raise ValueError('Relay URLs must be a list of 1 to 4 URLs')
    urls = []
    for url in value:
        if (not isinstance(url, str) or not url or len(url) > MAX_RELAY_URL_LENGTH
                or any(char.isspace() for char in url)):
            raise ValueError('Invalid relay URL')
        if '?' in url or '#' in url:
            raise ValueError('Relay URL must not carry a query or a fragment')
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https'):
            raise ValueError('Relay URL must be an HTTP(S) URL with a host')
        try:
            hostname = parts.hostname
            port = parts.port
        except ValueError:
            raise ValueError('Invalid relay URL authority') from None
        if not hostname or not _valid_hostname(hostname) or port == 0:
            raise ValueError('Invalid relay URL authority')
        if parts.username is not None or parts.password is not None:
            raise ValueError('Relay URL must not carry credentials')
        if parts.path not in ('', '/'):
            raise ValueError('Relay URL must be a bare origin without a path')
        if parts.scheme == 'http' and not _loopback_host(hostname):
            raise ValueError('A non-loopback relay URL must use HTTPS')
        urls.append(url)
    if sum(len(url) for url in urls) > MAX_RELAY_URLS_TOTAL_LENGTH:
        raise ValueError('Relay URLs exceed the total length an invitation code can carry')
    return urls


def validate_link(value):
    if not isinstance(value, dict) or 'endpoint_id' not in value or set(value) - {'endpoint_id', 'relay_urls'}:
        raise ValueError('Invalid peer-to-peer link')
    validate_endpoint_id(value['endpoint_id'])
    link = {'endpoint_id': value['endpoint_id']}
    if 'relay_urls' in value:
        link['relay_urls'] = validate_relay_urls(value['relay_urls'])
    return link


def new_secret():
    return _iroh().SecretKey.generate().to_bytes().hex()


def endpoint_id(secret):
    return str(_iroh().SecretKey.from_bytes(bytes.fromhex(secret)).public())


def _options(*, secret=None, alpns=None, local_only=False, relay_urls=None):
    iroh = _iroh()
    # local_only disables relay and discovery: direct addresses on this
    # computer only. It exists for deterministic offline tests.
    if relay_urls is not None:
        if local_only:
            raise ValueError('Custom relay URLs conflict with local-only mode')
        # RelayMode.relay_map segfaults in the iroh 1.1.0 Python bindings
        # (verified by construction probes); custom_from_urls is the working
        # constructor for a caller-supplied relay list.
        return iroh.EndpointOptions(preset=iroh.preset_n0(),
                                    secret_key=bytes.fromhex(secret) if secret else None, alpns=alpns,
                                    relay_mode=iroh.RelayMode.custom_from_urls(validate_relay_urls(relay_urls)))
    preset = iroh.preset_minimal() if local_only else iroh.preset_n0()
    return iroh.EndpointOptions(preset=preset, secret_key=bytes.fromhex(secret) if secret else None, alpns=alpns)


async def _pump_quic_to_tcp(recv, writer):
    try:
        while chunk := await recv.read(CHUNK):
            writer.write(chunk)
            await writer.drain()
        # End of the QUIC stream closes only our sending half; the peer may
        # still be answering on the other direction.
        if writer.can_write_eof():
            writer.write_eof()
    except Exception as error:
        # A reset or lost connection aborts the local socket in both directions.
        log.debug('quic to tcp ended: %r', error)
        writer.close()


async def _pump_tcp_to_quic(reader, send):
    try:
        while chunk := await reader.read(CHUNK):
            await send.write_all(chunk)
        await send.finish()
    except Exception as error:
        log.debug('tcp to quic ended: %r', error)
        try:
            send.reset(0)
        except Exception:
            pass


async def _bridge(reader, writer, bi):
    try:
        await asyncio.gather(_pump_quic_to_tcp(bi.recv(), writer), _pump_tcp_to_quic(reader, bi.send()))
    finally:
        writer.close()


def _splice(reader, writer, bi):
    return _spawn(_bridge(reader, writer, bi))


class HostLink:
    """Accept members by endpoint key and forward streams to the loopback port."""

    def __init__(self, secret, target_port, *, local_only=False, online_timeout=10, relay_urls=None):
        self.target_port = target_port
        self.connections = set()
        self._online = False
        self._closed = False
        self.endpoint = None
        self.endpoint = _run(self._bind(secret, local_only, online_timeout, relay_urls), online_timeout + 20)
        self.endpoint_id = str(self.endpoint.id())
        self.accepting = asyncio.run_coroutine_threadsafe(self._accept(), _background_loop())

    @property
    def online(self):
        """Whether the endpoint currently has a usable home relay.

        The home relay can arrive after the bind-time wait (slow networks,
        relay rotation), so this re-reads the endpoint's current address
        instead of trusting the one-shot bind result. A local-only endpoint
        never has a relay and stays offline.
        """
        if self._closed or self.endpoint is None:
            return self._online
        try:
            return self.endpoint.addr().relay_url() is not None
        except Exception:
            return self._online

    def status(self):
        """Secret-free diagnostics for the owner control endpoint."""
        result = {'endpoint_id': self.endpoint_id, 'online': self.online, 'members': len(self.connections)}
        try:
            addresses = self.addresses()
        except Exception:
            return result
        result['relay_url'] = addresses['relay_url']
        result['direct_addresses'] = addresses['addresses']
        return result

    async def _bind(self, secret, local_only, online_timeout, relay_urls):
        endpoint = await _iroh().Endpoint.bind(_options(secret=secret, alpns=[ALPN], local_only=local_only,
                                                        relay_urls=relay_urls))
        if not local_only:
            # Remote members need the relay and discovery record. Without them
            # the space still serves direct dialers, so report rather than fail.
            # The live `online` property re-reads the home relay afterwards;
            # this wait only seeds the initial value and surfaces slow relays.
            try:
                await asyncio.wait_for(endpoint.online(), online_timeout)
                self._online = True
            except asyncio.TimeoutError:
                self._online = False
                log.warning('p2p endpoint has no home relay after %ss; remote members cannot discover this host yet',
                            online_timeout)
            except Exception as error:
                self._online = False
                log.warning('p2p endpoint online check failed: %r', error)
        return endpoint

    def addresses(self):
        """Direct addresses and relay of this endpoint, for same-computer tests."""
        addr = self.endpoint.addr()
        return {'relay_url': addr.relay_url(), 'addresses': list(addr.direct_addresses())}

    async def _accept(self):
        while True:
            incoming = await self.endpoint.accept_next()
            if incoming is None:
                return
            if len(self.connections) >= MAX_CONNECTIONS:
                continue
            _spawn(self._serve(incoming))

    async def _serve(self, incoming):
        try:
            connection = await (await incoming.accept()).connect()
        except Exception:
            return
        if connection.alpn() != ALPN:
            connection.close(1, b'unsupported protocol')
            return
        connection.set_max_concurrent_bi_streams(MAX_STREAMS)
        self.connections.add(connection)
        try:
            while True:
                try:
                    bi = await connection.accept_bi()
                except Exception as error:
                    log.debug('host connection ended: %r', error)
                    return
                log.debug('host accepted stream')
                try:
                    # Windows retries refused loopback connects; bound the wait.
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection('127.0.0.1', self.target_port), 5)
                except (OSError, asyncio.TimeoutError):
                    # Refuse: stop reading and end our direction, so the member
                    # sees an immediate end of stream. (A reset alone was not
                    # observed by the peer's pending read in iroh 1.1.)
                    bi.recv().stop(0)
                    try:
                        await bi.send().finish()
                    except Exception:
                        pass
                    log.debug('host target unreachable; stream refused')
                    continue
                log.debug('host connected target')
                _splice(reader, writer, bi)
        finally:
            self.connections.discard(connection)

    def close(self):
        self._online = False
        self._closed = True
        try:
            if self.endpoint is not None:
                _run(self.endpoint.close(), 10)
        finally:
            self.accepting.cancel()


class MemberLink:
    """Listen on the space's loopback port and carry each connection to the host."""

    def __init__(self, endpoint_id, port, *, addresses=None, local_only=False, connect_timeout=30, relay_urls=None):
        self.remote = validate_endpoint_id(endpoint_id)
        self.port = port
        self.addresses = addresses or {}
        self.connect_timeout = connect_timeout
        self.connection = None
        self.server, self.endpoint = _run(self._start(local_only, relay_urls), 30)

    async def _start(self, local_only, relay_urls):
        self.lock = asyncio.Lock()
        endpoint = await _iroh().Endpoint.bind(_options(local_only=local_only, relay_urls=relay_urls))
        try:
            server = await asyncio.start_server(self._local, '127.0.0.1', self.port)
        except OSError:
            await endpoint.close()
            raise
        return server, endpoint

    async def _connect(self):
        async with self.lock:
            if self.connection is not None and self.connection.close_reason() is None:
                return self.connection
            iroh = _iroh()
            addr = iroh.EndpointAddr(iroh.EndpointId.from_string(self.remote),
                                     self.addresses.get('relay_url'), list(self.addresses.get('addresses', [])))
            self.connection = await asyncio.wait_for(self.endpoint.connect(addr, ALPN), self.connect_timeout)
            return self.connection

    def ensure_connected(self):
        """Dial the host now, within the connection budget.

        The first HTTP request over a fresh link otherwise pays the whole
        relay/discovery dial out of its own much shorter timeout and fails
        with a generic unreachable message even though the dial would have
        succeeded. Warming here surfaces a peer-to-peer-specific failure
        instead, and consumes no invitation: only a QUIC connection is made.
        """
        try:
            return _run(self._connect(), self.connect_timeout + 10)
        except Exception as error:
            self.connection = None
            raise SpaceUnreachableError('Could not reach the space over its peer-to-peer transport. '
                                          'The host may be offline, or unreachable from this network.') from error

    async def _local(self, reader, writer):
        # One retry covers a connection the host closed since the last use.
        for attempt in range(2):
            try:
                bi = await (await self._connect()).open_bi()
            except Exception as error:
                log.debug('member stream failed (attempt %d): %r', attempt, error)
                self.connection = None
                continue
            log.debug('member opened stream')
            _splice(reader, writer, bi)
            return
        writer.close()

    def path(self):
        """Selected path of the live connection: direct, relay or none."""
        connection = self.connection
        if connection is None or connection.close_reason() is not None:
            return {'state': 'disconnected'}
        for path in connection.paths():
            if getattr(path, 'is_selected', False):
                return {'state': 'relay' if path.is_relay else 'direct', 'rtt_ms': getattr(path, 'rtt_ms', None)}
        return {'state': 'connecting'}

    def close(self):
        async def shutdown():
            self.server.close()
            await self.endpoint.close()
        try:
            _run(shutdown(), 10)
        except Exception as error:
            # Cleanup must not fail the operation that used the link: on a
            # slow path the endpoint close can stall past its budget after a
            # request already succeeded, and join would then lose its profile.
            log.debug('member link shutdown did not finish cleanly: %r', error)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _serves_space(origin, room_id):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(origin + '/health', headers={'Accept': 'application/json'}), timeout=5) as response:
                payload = json.loads(response.read(4096))
        except (OSError, ValueError):
            # The listener exists but is not answering yet (the host is still
            # starting); retry briefly. A definitive answer never retries.
            if attempt < 2:
                time.sleep(1)
            continue
        return payload.get('room_id') == room_id
    return False


def member_link(profile, *, warm=False):
    """Context manager making a member profile's origin reachable on this computer.

    The space's loopback port may already serve this space: the bridge holds
    the link, or the host runs on this same computer. Reuse it after verifying
    the space identity; any other program on the port is an error.

    With warm=True, the QUIC connection is established before returning, so a
    caller about to make a short-timeout HTTP request (join) does not pay the
    relay/discovery dial out of that request's budget.
    """
    link = profile.get('p2p')
    if not link:
        return nullcontext()
    port = urlsplit(profile['origin']).port
    try:
        validated = validate_link(link)
        # Pass relay URLs only when the link carries them: the default
        # construction must stay exactly MemberLink(endpoint_id, port).
        kwargs = {'relay_urls': validated['relay_urls']} if 'relay_urls' in validated else {}
        member = MemberLink(validated['endpoint_id'], port, **kwargs)
    except OSError:
        if _serves_space(profile['origin'], profile['room_id']):
            return nullcontext()
        raise SpaceUnreachableError('The local port for this space is used by another program')
    if warm:
        try:
            member.ensure_connected()
        except Exception:
            try:
                member.close()
            except Exception:
                pass  # the dial error below is the diagnostic that matters
            raise
    return member
