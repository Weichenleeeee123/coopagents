"""Read-only, bounded WebSocket transport for shared room invalidations."""
import asyncio
import json
import time
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from .config import public_origin
from .errors import AccessDenied, ValidationError


def events_route(service, *, base_url=None, public_url=None, poll_interval=.5,
                 heartbeat_interval=15, auth_timeout=5, send_timeout=5,
                 max_connections=128, per_identity=4, frame_limit=4096):
    """Each factory has its own connection budget. Identity includes room/member/kind."""
    if base_url and public_url:
        raise ValueError('Set only one service origin')
    origin = public_origin(public_url) if public_url else None
    parsed = urlsplit(base_url) if base_url else None
    if parsed and (parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1') or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Base URL must be a local HTTP origin')
    expected_host = urlsplit(origin).netloc if origin else parsed.netloc.lower() if parsed else None
    identities, total = {}, 0

    async def endpoint(ws):
        nonlocal total
        headers = ws.scope['headers']
        hosts = [v.decode('latin-1').lower() for k, v in headers if k == b'host']
        origins = [v.decode('latin-1') for k, v in headers if k == b'origin']
        host = hosts[0] if len(hosts) == 1 else ''
        scheme = 'https' if ws.scope['scheme'] == 'wss' else 'http'
        port = ws.scope.get('server', ('127.0.0.1', 80))[1]
        allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if port == (443 if scheme == 'https' else 80):
            allowed.update({'127.0.0.1', 'localhost'})
        expected_origin = origin or (parsed.scheme + '://' + expected_host if parsed else scheme + '://' + host)
        if (not host or (host != expected_host if expected_host else host not in allowed)
                or origins and (len(origins) != 1 or origins[0] != expected_origin)
                or ws.scope.get('query_string')
                or any(k == b'sec-fetch-site' and v == b'cross-site' for k, v in headers)):
            await ws.close(code=4403)
            return
        if total >= max_connections:
            await ws.close(code=4429)
            return
        # Reserve before accepting: unauthenticated sockets also consume the global budget.
        total += 1
        key = None
        receiver = None
        registered = False
        async def send(payload):
            await asyncio.wait_for(ws.send_json(payload), send_timeout)
        try:
            await asyncio.wait_for(ws.accept(), send_timeout)
            frame = await asyncio.wait_for(ws.receive(), auth_timeout)
            raw = frame.get('text')
            if frame['type'] == 'websocket.disconnect':
                return
            if not isinstance(raw, str) or len(raw.encode('utf-8')) > frame_limit:
                raise ValidationError('Authentication frame too large or not text')
            try:
                auth = json.loads(raw)
            except (ValueError, RecursionError):
                raise ValidationError('Malformed authentication frame') from None
            if not isinstance(auth, dict) or set(auth) != {'token', 'after_id'} or not isinstance(auth['token'], str):
                raise ValidationError('Expected token and after_id')
            token, cursor = auth['token'], auth['after_id']
            principal = await run_in_threadpool(service.identity.authenticate, token)
            key = (principal.room_id, principal.member_id, principal.kind)
            if identities.get(key, 0) >= per_identity:
                await ws.close(code=4429)
                return
            identities[key] = identities.get(key, 0) + 1
            registered = True
            page = await run_in_threadpool(service.change_events.read, token, cursor)
            await send({'type': 'ready', 'protocol': 1, 'room_id': principal.room_id, 'high_water': page['high_water']})
            receiver = asyncio.create_task(ws.receive())
            last_sent = time.monotonic()
            while True:
                if receiver.done():
                    frame = receiver.result()
                    if frame['type'] == 'websocket.disconnect':
                        return
                    # No business commands, acknowledgments or additional auth frames.
                    raise ValidationError('Client frames are not accepted after authentication')
                if page['reset']:
                    await send({'type': 'reset', 'reason': page['reset'], 'cursor': page['cursor']})
                elif page['events']:
                    await send({'type': 'events', **page})
                elif time.monotonic() - last_sent >= heartbeat_interval:
                    await send({'type': 'heartbeat', 'cursor': cursor})
                if page['reset'] or page['events'] or time.monotonic() - last_sent >= heartbeat_interval:
                    last_sent = time.monotonic()
                cursor = page['cursor']
                if not page['has_more']:
                    await asyncio.wait({receiver}, timeout=poll_interval)
                # Re-resolve credentials and account/project revocation every poll/page.
                page = await run_in_threadpool(service.change_events.read, token, cursor)
        except AccessDenied:
            await ws.close(code=4401)
        except (ValidationError, UnicodeError):
            await ws.close(code=4400)
        except TimeoutError:
            await ws.close(code=4408)
        except (WebSocketDisconnect, OSError):
            pass
        finally:
            if receiver:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
            if registered:
                identities[key] -= 1
                if identities[key] == 0:
                    identities.pop(key)
            total -= 1

    return WebSocketRoute('/api/events', endpoint)
