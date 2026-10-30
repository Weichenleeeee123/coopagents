"""Loopback-only read capability; browser never receives source credentials."""
from pathlib import Path
import hmac
import secrets
import threading
import time
from types import SimpleNamespace

from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from .api import bearer, error_payload
from .errors import AccessDenied, ValidationError
from .realtime import events_route


class BoardAccess:
    def __init__(self, service, source_token, *, clock=time.monotonic, limit=128):
        self.service, self.source_token = service, source_token
        self.clock, self.limit = clock, limit
        self.tickets, self.sessions = {}, {}
        self.lock = threading.RLock()
        self.identity = SimpleNamespace(authenticate=self.authenticate)
        self.change_events = SimpleNamespace(read=self.events)
        self._source()

    def _source(self):
        principal = self.service.identity.authenticate(self.source_token, required_kind='agent')
        if principal.role != 'owner':
            raise AccessDenied('Only the host owner may open the board')
        return principal

    def _prune(self, mapping):
        for token in list(mapping):
            if mapping[token] <= self.clock():
                mapping.pop(token)

    def _put(self, mapping, ttl):
        self._prune(mapping)
        if len(mapping) >= self.limit:
            mapping.pop(next(iter(mapping)))
        token = secrets.token_urlsafe(32)
        mapping[token] = self.clock() + ttl
        return token

    def issue(self):
        with self.lock:
            self._source()
            return self._put(self.tickets, 60)

    def consume(self, ticket):
        with self.lock:
            self._prune(self.tickets)
            if not isinstance(ticket, str) or ticket not in self.tickets:
                raise AccessDenied('Board ticket expired or already used')
            self.tickets.pop(ticket)
            self._source()
            return self._put(self.sessions, 3600)

    def authenticate(self, token):
        with self.lock:
            self._prune(self.sessions)
            if token not in self.sessions:
                raise AccessDenied('Board session expired')
            return self._source()

    def events(self, token, cursor):
        self.authenticate(token)
        return self.service.change_events.read(self.source_token, cursor)

    def snapshot(self, token):
        self.authenticate(token)
        # Common snapshot uses list_requests, never the receipt-writing read_inbox.
        return self.service.snapshot(self.source_token, web=False)


def board_routes(service, source_token, control_origin, control_token, room_id):
    access = BoardAccess(service, source_token)
    if access._source().room_id != room_id:
        raise AccessDenied('Board space does not match host')
    static = Path(__file__).parent / 'static'
    allowed = {'board.js', 'realtime_client.js', 'space_board.js', 'styles.css', 'git.js', 'project_activity.js', 'dependencies.js'}
    headers = {'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
               'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'}

    async def endpoint(request):
        try:
            if not request.client or request.client.host not in ('127.0.0.1', '::1'):
                raise AccessDenied('Loopback board only')
            if request.url.path == '/board/open':
                if not hmac.compare_digest(bearer(request), control_token):
                    raise AccessDenied('Control credential not accepted')
                if await request.json() != {}:
                    raise ValidationError('Expected empty board request')
                ticket = await run_in_threadpool(access.issue)
                return JSONResponse({'url': control_origin + '/board#' + ticket}, headers=headers)
            if request.url.path == '/board/session':
                if request.headers.get('origin') != control_origin:
                    raise AccessDenied('Same origin session exchange required')
                data = await request.json()
                if not isinstance(data, dict) or set(data) != {'ticket'}:
                    raise ValidationError('Expected board ticket')
                token = await run_in_threadpool(access.consume, data['ticket'])
                return JSONResponse({'token': token, 'expires_in': 3600}, headers=headers)
            if request.url.path == '/board/snapshot':
                result = await run_in_threadpool(access.snapshot, bearer(request))
                return JSONResponse(result, headers=headers)
            name = request.path_params.get('name')
            if name and name not in allowed:
                return JSONResponse({'error': 'NotFound'}, status_code=404, headers=headers)
            return FileResponse(static / (name or 'board.html'), headers=headers)
        except Exception as error:
            payload, status = error_payload(error)
            return JSONResponse(payload, status_code=status, headers=headers)

    return [Route('/board', endpoint), Route('/board/static/{name}', endpoint),
            Route('/board/open', endpoint, methods=['POST']), Route('/board/session', endpoint, methods=['POST']),
            Route('/board/snapshot', endpoint), events_route(access, base_url=control_origin)]
