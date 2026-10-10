"""Local HTTP API; callers are always derived from opaque bearer credentials."""
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount

from .identity import IdentityStore
from .tasks import TaskStore
from .activity import ActivityStore
from .messages import MessageStore
from .contracts import ContractStore
from .errors import AccessDenied, Conflict, NotFound, ValidationError

BODY_LIMIT = 65536
ERROR_STATUS = {ValidationError: 400, AccessDenied: 401, NotFound: 404, Conflict: 409}


def error_payload(error):
    for kind, status in ERROR_STATUS.items():
        if isinstance(error, kind):
            payload = {'error': kind.__name__, 'message': str(error)}
            if isinstance(error, Conflict) and error.owner_member_id is not None:
                payload['owner_member_id'] = error.owner_member_id
            return payload, status
    return {'error': 'InternalError', 'message': 'Operation failed'}, 500


def validate(data, schema):
    if not isinstance(data, dict) or any(key not in schema for key in data):
        raise ValidationError('Expected an object containing only supported fields')
    for key, (kind, required, default) in schema.items():
        if key not in data:
            if required:
                raise ValidationError('Missing required field: ' + key)
            data[key] = default
        value = data[key]
        if value is None and not required and default is None:
            continue
        if type(value) is not kind:
            raise ValidationError('Invalid field type: ' + key)
        if kind is str:
            try:
                value.encode('utf-8')
            except UnicodeEncodeError:
                raise ValidationError('Text must contain valid Unicode') from None
    return data


def fields(required='', optional=None):
    result = {key: (int if key in {'expected_version', 'context_version', 'version', 'request_id', 'contract_id', 'task_id', 'after_id', 'limit'} else str, True, None) for key in required.split()}
    for key, default in (optional or {}).items():
        result[key] = (int if key in {'source_request_id', 'task_id', 'after_id', 'limit'} else str, False, default)
    return result


class Service:
    def __init__(self, database_path):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(path)
        self.tasks = TaskStore(self.identity)
        self.activity = ActivityStore(self.identity)
        self.messages = MessageStore(self.identity)
        self.contracts = ContractStore(self.identity)
        self.operations = {
            'create_room': (None, self.identity.create_room, fields('name owner_name', {'repository': ''})),
            'join': (None, self.identity.join_invite, fields('invite_token display_name')),
            'invite': ('web', self.identity.create_invite, fields()),
            'rotate_agent': ('web', self.identity.rotate_agent, fields()),
            'create_task': ('web', self.tasks.create_task, fields('intent_key title scope')),
            'claim_task': ('agent', self.tasks.claim_task, fields('task_id')),
            'register_session': ('agent', self.activity.register_session, fields('session_key tool repository branch', {'task_id': None})),
            'report_progress': ('agent', self.activity.report_progress, fields('task_id state summary', {'evidence': ''})),
            'send_request': ('agent', self.messages.send_request, fields('request_key context_version body', {'receiver_member_id': None, 'task_id': None})),
            'read_inbox': ('agent', self.messages.read_inbox, fields('', {'after_id': 0, 'limit': 50})),
            'acknowledge': ('agent', self.messages.acknowledge, fields('request_id')),
            'reply': ('agent', self.messages.reply, fields('request_id request_key context_version body', {'evidence': ''})),
            'resolve_request': ('any', self.messages.resolve_request, fields('request_id context_version')),
            'assign': ('web', self.messages.assign_receiver, fields('request_id receiver_member_id')),
            'propose_contract': ('agent', self.contracts.propose, fields('contract_key expected_version title body', {'source_request_id': None, 'commit_ref': ''})),
            'decision': ('web', self.contracts.decide, fields('contract_id version decision')),
        }
        self.reads = {'tasks': self.tasks.list_tasks, 'sessions': self.activity.list_sessions,
                      'progress': self.activity.list_progress, 'overlaps': self.activity.overlaps,
                      'requests': self.messages.list_requests, 'contracts': self.contracts.list_contracts,
                      'events': self.contracts.list_events, 'members': self.identity.list_members}

    def me(self, token):
        return {'me': asdict(self.identity.authenticate(token)), 'room': self.identity.room_info(token)}

    def snapshot(self, token, *, web=True):
        self.identity.authenticate(token, required_kind='web' if web else 'agent')
        result = self.me(token)
        result.update({name: read(token) for name, read in self.reads.items()})
        result['server_time'] = datetime.now(timezone.utc).isoformat()
        return result

    def call(self, operation, token, data):
        kind, method, schema = self.operations[operation]
        if kind:
            self.identity.authenticate(token, required_kind=None if kind == 'any' else kind)
        data = validate(dict(data) if isinstance(data, dict) else data, schema)
        return method(token, **data) if kind else method(**data)


class LocalBoundary:
    """Validate host/origin and actual body bytes before HTTP or MCP handling."""
    def __init__(self, app, base_url=None):
        self.app = app
        self.state = getattr(app, "state", None)
        parsed = urlsplit(base_url) if base_url else None
        if parsed and (parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.scheme not in ('http', 'https') or parsed.username or parsed.password):
            raise ValueError('Base URL must be a local HTTP origin')
        self.host = parsed.netloc.lower() if parsed else None

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
        async def reject(message, status=400):
            await JSONResponse({'error': 'ValidationError', 'message': message}, status_code=status)(scope, receive, response_send)
        rejection = None
        if not host or (host != self.host if self.host else host not in appropriate):
            rejection = ('Host not accepted', 400)
        if scope['method'] not in ('GET', 'HEAD', 'OPTIONS'):
            if any(k == b'sec-fetch-site' and v == b'cross-site' for k, v in headers):
                rejection = ('Origin not accepted', 403)
            origins = [v.decode('latin-1') for k, v in headers if k == b'origin']
            if origins and (len(origins) != 1 or origins[0] != scope['scheme'] + '://' + host):
                rejection = ('Origin not accepted', 403)
        if scope.get('query_string') and scope['path'] != '/api/inbox':
            rejection = ('Query parameters not accepted', 400)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] != 'http.request':
                return
            body.extend(message.get('body', b''))
            if len(body) > BODY_LIMIT:
                return await reject('Request body too large', 413)
            if not message.get('more_body', False):
                break
        if rejection:
            return await reject(*rejection)
        if body and scope['method'] not in ('GET', 'HEAD', 'OPTIONS'):
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


def create_app(database_path='.local/crewmesh.sqlite3', *, base_url=None):
    service = Service(database_path)
    from .mcp_service import create_mcp_app
    mcp_app, authenticated_mcp = create_mcp_app(service)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    async def endpoint(request):
        try:
            path = request.url.path
            if path == '/health' and request.method == 'GET':
                return JSONResponse({'status': 'ok'})
            operation = request.scope.get('operation')
            public = operation in ('create_room', 'join')
            token = None if public else bearer(request)
            if token:
                service.identity.authenticate(token)
            if request.method == 'GET':
                name = request.scope['read_name']
                if name == 'me':
                    result = service.me(token)
                elif name == 'snapshot':
                    result = service.snapshot(token)
                elif name == 'inbox':
                    if any(k not in ('after_id', 'limit') or len(request.query_params.getlist(k)) != 1 for k in request.query_params):
                        raise ValidationError('Unsupported query parameter')
                    try:
                        data = {k: int(v) for k, v in request.query_params.items()}
                    except ValueError:
                        raise ValidationError('Invalid query parameter') from None
                    result = service.call('read_inbox', token, data)
                else:
                    result = service.reads[name](token)
            else:
                if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    raise ValidationError('Content type must be application/json')
                try:
                    data = json.loads((await request.body()).decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeDecodeError):
                    raise ValidationError('Malformed JSON') from None
                if not isinstance(data, dict):
                    raise ValidationError('Expected a JSON object')
                schema = service.operations[operation][2]
                body_schema = {k: v for k, v in schema.items() if k not in request.path_params}
                validate(data, body_schema)
                for key, value in request.path_params.items():
                    data[key] = value
                result = service.call(operation, token, data)
            return JSONResponse(result)
        except Exception as error:
            payload, status = error_payload(error)
            return JSONResponse(payload, status_code=status)

    def route(path, methods, *, operation=None, read_name=None):
        async def handle(request):
            request.scope['operation'] = operation
            request.scope['read_name'] = read_name
            return await endpoint(request)
        return Route(path, handle, methods=methods)

    routes = [route('/health', ['GET']), route('/api/rooms', ['POST'], operation='create_room'), route('/api/join', ['POST'], operation='join'),
              route('/api/me', ['GET'], read_name='me'), route('/api/snapshot', ['GET'], read_name='snapshot'),
              route('/api/invites', ['POST'], operation='invite'), route('/api/agent-token', ['POST'], operation='rotate_agent'),
              route('/api/inbox', ['GET'], read_name='inbox')]
    for name in ('tasks', 'sessions', 'progress', 'overlaps', 'requests', 'contracts', 'events'):
        routes.append(route('/api/' + name, ['GET'], read_name=name))
    for path, operation in [('/api/tasks', 'create_task'), ('/api/tasks/{task_id:int}/claim', 'claim_task'),
                            ('/api/sessions', 'register_session'), ('/api/tasks/{task_id:int}/progress', 'report_progress'),
                            ('/api/requests', 'send_request'), ('/api/requests/{request_id:int}/ack', 'acknowledge'),
                            ('/api/requests/{request_id:int}/reply', 'reply'), ('/api/requests/{request_id:int}/resolve', 'resolve_request'),
                            ('/api/requests/{request_id:int}/assign', 'assign'), ('/api/contracts', 'propose_contract'),
                            ('/api/contracts/{contract_id:int}/decision', 'decision')]:
        routes.append(route(path, ['POST'], operation=operation))
    routes.append(Mount('/', app=authenticated_mcp))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.service = service
    return LocalBoundary(app, base_url)

