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
import json
import logging
import re
import threading
import urllib.request
from urllib.parse import urlsplit

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

            threading.Thread(target=run, name='crewmesh-p2p', daemon=True).start()
            ready.wait()
            _loop = loop
        return _loop


def _run(coro, timeout):
    return asyncio.run_coroutine_threadsafe(coro, _background_loop()).result(timeout)


def validate_endpoint_id(value):
    if not isinstance(value, str) or not ENDPOINT_ID.fullmatch(value):
        raise ValueError('Peer-to-peer endpoint id must be 64 lowercase hex characters')
    return value


def validate_link(value):
    if not isinstance(value, dict) or set(value) != {'endpoint_id'}:
        raise ValueError('Invalid peer-to-peer link')
    validate_endpoint_id(value['endpoint_id'])
    return value


def new_secret():
    return _iroh().SecretKey.generate().to_bytes().hex()


def endpoint_id(secret):
    return str(_iroh().SecretKey.from_bytes(bytes.fromhex(secret)).public())


def _options(*, secret=None, alpns=None, local_only=False):
    iroh = _iroh()
    # local_only disables relay and discovery: direct addresses on this
    # computer only. It exists for deterministic offline tests.
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

    def __init__(self, secret, target_port, *, local_only=False, online_timeout=10):
        self.target_port = target_port
        self.connections = set()
        self.online = False
        self.endpoint = _run(self._bind(secret, local_only, online_timeout), online_timeout + 20)
        self.endpoint_id = str(self.endpoint.id())
        self.accepting = asyncio.run_coroutine_threadsafe(self._accept(), _background_loop())

    async def _bind(self, secret, local_only, online_timeout):
        endpoint = await _iroh().Endpoint.bind(_options(secret=secret, alpns=[ALPN], local_only=local_only))
        if not local_only:
            # Remote members need the relay and discovery record. Without them
            # the space still serves direct dialers, so report rather than fail.
            try:
                await asyncio.wait_for(endpoint.online(), online_timeout)
                self.online = True
            except asyncio.TimeoutError:
                self.online = False
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
        try:
            _run(self.endpoint.close(), 10)
        finally:
            self.accepting.cancel()


class MemberLink:
    """Listen on the space's loopback port and carry each connection to the host."""

    def __init__(self, endpoint_id, port, *, addresses=None, local_only=False, connect_timeout=30):
        self.remote = validate_endpoint_id(endpoint_id)
        self.port = port
        self.addresses = addresses or {}
        self.connect_timeout = connect_timeout
        self.connection = None
        self.server, self.endpoint = _run(self._start(local_only), 30)

    async def _start(self, local_only):
        self.lock = asyncio.Lock()
        endpoint = await _iroh().Endpoint.bind(_options(local_only=local_only))
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
        _run(shutdown(), 10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _serves_space(origin, room_id):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(origin + '/health', headers={'Accept': 'application/json'}), timeout=5) as response:
            return json.loads(response.read(4096)).get('room_id') == room_id
    except (OSError, ValueError):
        return False


def member_link(profile):
    """Context manager making a member profile's origin reachable on this computer.

    The space's loopback port may already serve this space: the bridge holds
    the link, or the host runs on this same computer. Reuse it after verifying
    the space identity; any other program on the port is an error.
    """
    link = profile.get('p2p')
    if not link:
        return nullcontext()
    port = urlsplit(profile['origin']).port
    try:
        return MemberLink(validate_link(link)['endpoint_id'], port)
    except OSError:
        if _serves_space(profile['origin'], profile['room_id']):
            return nullcontext()
        raise ValueError('The local port for this space is used by another program')
