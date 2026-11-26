"""Common transport boundary for workflow and collaboration hosts."""
import asyncio
import json
import time
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from .config import public_origin
from .errors import AccessDenied, Conflict, NotFound, ValidationError

BODY_LIMIT = 65536
ASSET_BODY_LIMIT = 10 * 1024 * 1024 + 65536
ERROR_STATUS = {ValidationError: 400, AccessDenied: 401, NotFound: 404, Conflict: 409}


def error_payload(error):
    for kind, status in ERROR_STATUS.items():
        if isinstance(error, kind):
            payload = {'error': kind.__name__, 'message': str(error)}
            if isinstance(error, Conflict) and error.owner_member_id is not None:
                payload['owner_member_id'] = error.owner_member_id
            return payload, status
    return {'error': 'InternalError', 'message': 'Operation failed'}, 500


class LocalBoundary:
    """Validate host/origin and actual body bytes before HTTP or MCP handling."""
    def __init__(self, app, base_url=None, public_url=None, *, billing_webhook=False):
        self.app = app
        self.billing_webhook = billing_webhook
        self.state = getattr(app, "state", None)
        parsed = urlsplit(base_url) if base_url else None
        if parsed and (parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.scheme not in ('http', 'https') or parsed.username or parsed.password):
            raise ValueError('Base URL must be a local HTTP origin')
        self.host = parsed.netloc.lower() if parsed else None
        self.origin = public_origin(public_url) if public_url else None
        if self.origin:
            self.host = urlsplit(self.origin).netloc

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def private_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message.get('headers', [])) + [(b'cache-control', b'no-store')]
            await send(message)
        response_send = private_send
        headers = scope['headers']
        hosts = [value.decode('latin-1').lower() for key, value in headers if key == b'host']
        host = hosts[0] if len(hosts) == 1 else ''
        port = scope.get('server', ('127.0.0.1', 80))[1]
        appropriate = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if port == (443 if scope['scheme'] == 'https' else 80):
            appropriate.update({'127.0.0.1', 'localhost'})
        close_connection = False
        async def reject(message, status=400):
            await JSONResponse({'error': 'ValidationError', 'message': message}, status_code=status, headers={'Connection': 'close'} if close_connection else {})(scope, receive, response_send)
        rejection = None
        if not host or (host != self.host if self.host else host not in appropriate):
            rejection = ('Host not accepted', 400)
        if scope['method'] not in ('GET', 'HEAD', 'OPTIONS'):
            if any(k == b'sec-fetch-site' and v == b'cross-site' for k, v in headers):
                rejection = ('Origin not accepted', 403)
        origins = [v.decode('latin-1') for k, v in headers if k == b'origin']
        if origins and (len(origins) != 1 or origins[0] != (self.origin or scope['scheme'] + '://' + host)):
            rejection = ('Origin not accepted', 403)
        if scope.get('query_string') and scope['path'] not in ('/api/inbox', '/api/context', '/api/deliveries', '/board/context') and not (scope['path'] in ('/account/oauth/github/callback','/api/git/github/callback') and scope['method'] == 'GET'):
            rejection = ('Query parameters not accepted', 400)
        if rejection:
            # Reply after small pending bodies arrive, avoiding Windows TCP reset.
            # Hostile streams remain bounded by both bytes and elapsed time.
            deadline, consumed = time.monotonic() + 2, 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    close_connection = True
                    break
                try:
                    message = await asyncio.wait_for(receive(), timeout=remaining)
                except TimeoutError:
                    close_connection = True
                    break
                if message['type'] != 'http.request':
                    close_connection = True
                    break
                consumed += len(message.get('body', b''))
                limit = ASSET_BODY_LIMIT if scope['path'] == '/api/assets' else BODY_LIMIT
                if consumed > limit:
                    close_connection = True
                    break
                if not message.get('more_body', False):
                    break
            return await reject(*rejection)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] != 'http.request':
                return
            body.extend(message.get('body', b''))
            limit = ASSET_BODY_LIMIT if scope['path'] == '/api/assets' and scope['method'] == 'POST' else BODY_LIMIT
            if len(body) > limit:
                return await reject('Request body too large', 413)
            if not message.get('more_body', False):
                break
        raw_webhook = self.billing_webhook and scope['path'] == '/billing/stripe/webhook' and scope['method'] == 'POST'
        asset_upload = scope['path'] == '/api/assets' and scope['method'] == 'POST'
        if body and scope['method'] not in ('GET', 'HEAD', 'OPTIONS') and not raw_webhook and not asset_upload:
            try:
                decoded = bytes(body).decode('utf-8')
                decoded.encode('utf-8')
                document = json.loads(decoded, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
                def valid_unicode(value):
                    if isinstance(value, str):
                        value.encode('utf-8')
                    elif isinstance(value, dict):
                        for key, item in value.items():
                            valid_unicode(key)
                            valid_unicode(item)
                    elif isinstance(value, list):
                        for item in value:
                            valid_unicode(item)
                valid_unicode(document)
            except (ValueError, UnicodeError, RecursionError):
                return await reject('Malformed JSON')
        delivered = False
        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, buffered_receive, response_send)


def bearer(request):
    values = request.headers.getlist('authorization')
    if len(values) != 1 or not values[0].startswith('Bearer ') or not values[0][7:] or any(c.isspace() for c in values[0][7:]):
        raise AccessDenied('Credential not accepted')
    return values[0][7:]
