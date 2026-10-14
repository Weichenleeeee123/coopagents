"""Public collaboration transport and separate loopback lifecycle control."""
from contextlib import asynccontextmanager
import hmac
import json
import time

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .api import LocalBoundary, bearer, error_payload
from .errors import AccessDenied, ValidationError
from .protocol import validate, fields


def create_space_app(service, *, room_id, origin):
    from .coordination_http import coordination_routes
    from .mcp_service import create_mcp_app
    from .realtime import events_route
    from urllib.parse import urlsplit
    local = urlsplit(origin).scheme == 'http'
    base, public = (origin, None) if local else (None, origin)
    mcp, protected = create_mcp_app(service, origin=origin)
    attempts = {}

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.router.lifespan_context(mcp):
            yield

    async def health(request):
        return JSONResponse({'status': 'ok', 'room_id': room_id})

    async def join(request):
        try:
            now = time.monotonic()
            stale = [key for key, value in attempts.items() if now - value[0] >= 60]
            for key in stale:
                attempts.pop(key)
            address = request.client.host if request.client else 'unknown'
            if address not in attempts and len(attempts) >= 1024:
                return JSONResponse({'error': 'RateLimited'}, status_code=429)
            started, count = attempts.get(address, (now, 0))
            attempts[address] = (started, count + 1)
            if count >= 60:
                return JSONResponse({'error': 'RateLimited'}, status_code=429)
            if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                raise ValidationError('Content type must be application/json')
            data = validate(await request.json(), fields('invite_token display_name room_id'))
            if data['room_id'] != room_id:
                raise AccessDenied('Invitation space does not match')
            result = await run_in_threadpool(service.identity.join_invite, data['invite_token'], data['display_name'],
                                             expected_room_id=room_id)
            return JSONResponse(result)
        except Exception as error:
            payload, status = error_payload(error)
            return JSONResponse(payload, status_code=status)

    routes = [Route('/health', health), Route('/api/join', join, methods=['POST'])]
    routes += coordination_routes(service, base_url=base, public_url=public, include_named=True)
    routes.append(events_route(service, base_url=base, public_url=public))
    routes.append(Mount('/', app=protected))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.service = service
    return LocalBoundary(app, base, public)


def create_control_app(control_origin, control_token, stop_event, room_id, ready_event=None, *, service=None, source_token=None):
    async def control(request):
        try:
            if request.client.host not in ('127.0.0.1', '::1'):
                raise AccessDenied('Loopback control only')
            if not hmac.compare_digest(bearer(request), control_token):
                raise AccessDenied('Control credential not accepted')
            if request.method == 'POST':
                data = await request.json()
                if data != {}:
                    raise ValidationError('Expected empty control request')
                stop_event.set()
            status = 'stopping' if stop_event.is_set() else 'starting' if ready_event and not ready_event.is_set() else 'running'
            return JSONResponse({'status': status, 'room_id': room_id})
        except Exception as error:
            payload, status = error_payload(error)
            return JSONResponse(payload, status_code=status)
    routes = [Route('/status', control), Route('/stop', control, methods=['POST'])]
    if service is not None and source_token is not None:
        from .space_board import board_routes
        routes += board_routes(service, source_token, control_origin, control_token, room_id)
    return LocalBoundary(Starlette(routes=routes),
                         base_url=control_origin)
