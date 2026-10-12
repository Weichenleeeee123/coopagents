"""Local HTTP API; callers are always derived from opaque bearer credentials."""
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import asyncio
import time
import hmac
import hashlib
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, Mount

from .identity import IdentityStore
from .tasks import TaskStore
from .activity import ActivityStore
from .messages import MessageStore
from .contracts import ContractStore
from .errors import AccessDenied, Conflict, NotFound, ValidationError
from .config import public_origin, validate_bootstrap_secret

BODY_LIMIT = 65536
WEB_CSP = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
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
    result = {key: (int if key in {'source_task_id', 'target_task_id', 'dependency_id', 'reply_id', 'expected_revision', 'ownership_epoch', 'expected_version', 'context_version', 'version', 'request_id', 'contract_id', 'task_id', 'after_id', 'limit'} else str, True, None) for key in required.split()}
    for key, default in (optional or {}).items():
        result[key] = (int if key in {'before_id', 'ownership_epoch', 'source_request_id', 'task_id', 'after_id', 'limit'} else str, False, default)
    return result


class Service:
    def __init__(self, database_path, github_app=None):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(path)
        from .accounts import AccountStore
        from .workspaces import WorkspaceStore
        self.accounts = AccountStore(self.identity)
        self.workspaces = WorkspaceStore(self.accounts)
        self.tasks = TaskStore(self.identity)
        from .task_lifecycle import TaskLifecycleStore, ACTIONS
        self.lifecycle = TaskLifecycleStore(self.identity)
        from .dependencies import DependencyStore, schemas as dependency_schemas
        self.dependencies = DependencyStore(self.identity)
        self.activity = ActivityStore(self.identity)
        self.messages = MessageStore(self.identity)
        self.contracts = ContractStore(self.identity)
        from .checkpoints import CheckpointStore
        self.checkpoints = CheckpointStore(self.identity)
        from .repositories import RepositoryStore
        self.repositories = RepositoryStore(self.identity)
        from .github_app import GitHubApp
        from .github_sync import GitHubSync
        self.github = GitHubSync(self.identity, self.repositories, github_app or GitHubApp())
        self.operations = {
            'checkpoint': ('agent', self.checkpoints.checkpoint, fields('session_key tool event', {'task_id': None, 'ownership_epoch': None})),
            'diagnostic_start': ('agent', self.checkpoints.diagnostic_start, fields('challenge')),
            'diagnostic_read': ('agent', self.checkpoints.diagnostic_read, fields('diagnostic_id')),
            'diagnostic_complete': ('agent', self.checkpoints.diagnostic_complete, fields('diagnostic_id proof')),
            'create_room': (None, self.identity.create_room, fields('name owner_name', {'repository': ''})),
            'join': (None, self.identity.join_invite, fields('invite_token display_name')),
            'invite': ('web', self.identity.create_invite, fields()),
            'rotate_agent': ('web', self.identity.rotate_agent, fields()),
            'connect_agent': ('web', self.identity.connect_agent, fields()),
            'create_task': ('web', self.tasks.create_task, fields('intent_key title scope')),
            'claim_task': ('agent', self.tasks.claim_task, fields('task_id', {'session_key': None})),
            'register_session': ('agent', self.activity.register_session, fields('session_key tool repository branch', {'task_id': None, 'ownership_epoch': None})),
            'report_progress': ('agent', self.activity.report_progress, fields('task_id state summary', {'evidence': '', 'session_key': None, 'ownership_epoch': None})),
            'send_request': ('agent', self.messages.send_request, fields('request_key context_version body', {'receiver_member_id': None, 'task_id': None})),
            'read_inbox': ('agent', self.messages.read_inbox, fields('', {'after_id': 0, 'limit': 50})),
            'acknowledge': ('agent', self.messages.acknowledge, fields('request_id')),
            'reply': ('agent', self.messages.reply, fields('request_id request_key context_version body', {'evidence': ''})),
            'resolve_request': ('any', self.messages.resolve_request, fields('request_id context_version')),
            'assign': ('web', self.messages.assign_receiver, fields('request_id receiver_member_id')),
            'propose_contract': ('agent', self.contracts.propose, fields('contract_key expected_version title body', {'source_request_id': None, 'commit_ref': ''})),
            'decision': ('web', self.contracts.decide, fields('contract_id version decision')),
            'bind_repository': ('web', self.repositories.bind_repository, fields('repository')),
            'observe_repository': ('agent', self.repositories.observe, {'task_id': (int, True, None), 'observation': (dict, True, None)}),
            'repo_checkpoint': ('agent', self.repo_checkpoint, {'task_id': (int, True, None), 'observation': (dict, True, None)}),
            'read_git_team': ('agent', lambda token: self.snapshot(token, web=False), fields()),
            'link_delivery': ('any', self.github.associate, {'task_id': (int, True, None),
                'branch': (str, False, ''), 'pr_number': (int, False, None), 'commit_sha': (str, False, '')}),
        }
        for name, schema in dependency_schemas(fields).items():
            self.operations[name] = ('any', getattr(self.dependencies, name), schema)
        for action in ACTIONS:
            optional = {'session_key': None, 'ownership_epoch': None} if action in ('release_task', 'propose_handoff') else {}
            required = 'task_id expected_revision request_key summary'
            if action in ('propose_handoff', 'force_handoff'):
                required += ' target_member_id'
            self.operations[action] = ('any' if action in ('release_task', 'propose_handoff') else 'web',
                                       getattr(self.lifecycle, action), fields(required, optional))
        self.operations['read_task_history'] = ('any', self.lifecycle.read_task_history, fields('task_id', {'before_id':None,'limit':20}))
        for name in ('observe_repository', 'repo_checkpoint', 'link_delivery'):
            self.operations[name][2].update(fields('', {'session_key': None, 'ownership_epoch': None}))
        self.reads = {'tasks': self.tasks.list_tasks, 'sessions': self.activity.list_sessions,
                      'progress': self.activity.list_progress, 'overlaps': self.activity.overlaps,
                      'requests': self.messages.list_requests, 'contracts': self.contracts.list_contracts,
                      'events': self.contracts.list_events, 'members': self.identity.list_members}
        self.reads['git'] = self.git_snapshot
        self.reads['collaboration'] = self.checkpoints.snapshot
        self.reads['lifecycle'] = self.lifecycle.snapshot
        self.reads['dependencies'] = self.dependencies.snapshot

    def git_snapshot(self, token):
        result = self.repositories.snapshot(token)
        result.update(self.github.snapshot(token))
        result['github_configured'] = self.github.app.enabled
        return result

    def repo_checkpoint(self, token, task_id, observation, session_key=None, ownership_epoch=None):
        observed = self.repositories.observe(token, task_id, observation, session_key, ownership_epoch)
        return {'observation': observed, 'team': self.snapshot(token, web=False),
                'inbox': self.messages.read_inbox(token)}

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
        if scope.get('query_string') and scope['path'] != '/api/inbox' and not (scope['path'] in ('/account/oauth/github/callback','/api/git/github/callback') and scope['method'] == 'GET'):
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
                if consumed > BODY_LIMIT:
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
            if len(body) > BODY_LIMIT:
                return await reject('Request body too large', 413)
            if not message.get('more_body', False):
                break
        raw_webhook = self.billing_webhook and scope['path'] == '/billing/stripe/webhook' and scope['method'] == 'POST'
        if body and scope['method'] not in ('GET', 'HEAD', 'OPTIONS') and not raw_webhook:
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


def create_app(database_path='.local/crewmesh.sqlite3', *, base_url=None, public_url=None, bootstrap_secret=None, mode='self-hosted', github_client_id=None, github_client_secret=None, github_app=None, billing_config=None):
    if base_url and public_url:
        raise ValueError('Set only one service origin')
    origin = public_origin(public_url) if public_url is not None else None
    if mode not in ('self-hosted', 'cloud'):
        raise ValueError('Mode must be self-hosted or cloud')
    if bootstrap_secret is not None:
        validate_bootstrap_secret(bootstrap_secret)
    bootstrap_hash = hashlib.sha256(validate_bootstrap_secret(bootstrap_secret).encode('ascii')).digest() if origin and mode == 'self-hosted' else None
    from .billing_api import billing_catalog, billing_routes, BillingRuntime
    from .billing import BillingStore
    from .billing_service import BillingService
    from .stripe_billing import StripeClient
    from .billing_worker import BillingWorker
    catalog = billing_catalog(mode, billing_config, origin)
    service = Service(database_path, github_app)
    store = BillingStore(service.workspaces, mode, catalog)
    client = StripeClient(billing_config.secret_key, catalog.provider_mode) if catalog else None
    service.billing = BillingService(store, client, billing_config.webhook_secret if catalog else None, origin)
    service.billing_store = store
    billing_runtime = BillingRuntime()
    billing_worker = BillingWorker(service.billing, billing_runtime)
    from .account_api import account_routes
    from .oauth import GitHubOAuth
    oauth = GitHubOAuth.configured(service.accounts, mode, origin, github_client_id, github_client_secret)
    from .mcp_service import create_mcp_app
    mcp_app, authenticated_mcp = create_mcp_app(service, origin=origin or base_url)

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                billing_worker.start()
                try:
                    async with github_lifespan():
                        yield
                finally:
                    await billing_worker.close()
        finally:
            await billing_runtime.close()

    @asynccontextmanager
    async def github_lifespan():
        stop = asyncio.Event()
        async def github_worker():
            next_poll = time.monotonic() + 300
            while not stop.is_set():
                # Network calls run outside the event loop. Durable inbox records
                # are committed before acknowledgement and survive restarts.
                try:
                    await run_in_threadpool(service.github.process_pending, limit=1, should_stop=stop.is_set)
                    if not stop.is_set() and time.monotonic() >= next_poll:
                        await run_in_threadpool(service.github.reconcile_all, should_stop=stop.is_set)
                        next_poll = time.monotonic() + 300
                except Exception:
                    # Do not log request bodies or provider credentials. Failed
                    # records remain pending; the next pass retries them.
                    import logging
                    logging.getLogger(__name__).warning('GitHub reconciliation pass failed')
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
        worker = asyncio.create_task(github_worker()) if service.github.app.enabled else None
        try:
            yield
        finally:
            stop.set()
            if worker:
                await worker

    async def endpoint(request):
        try:
            path = request.url.path
            if path == '/health' and request.method == 'GET':
                return JSONResponse({'status': 'ok'})
            if path == '/ready' and request.method == 'GET':
                try:
                    with service.identity.db.connect() as connection:
                        connection.execute('SELECT id FROM rooms LIMIT 1').fetchone()
                    return JSONResponse({'status': 'ready'})
                except Exception:
                    return JSONResponse({'status': 'unavailable'}, status_code=503)
            operation = request.scope.get('operation')
            if mode == 'cloud' and operation in ('create_room', 'join'):
                raise AccessDenied('GitHub account workspace required')
            if operation == 'create_room' and bootstrap_hash is not None:
                credentials = request.headers.getlist('x-crewmesh-bootstrap')
                candidate = credentials[0] if len(credentials) == 1 else ''
                if not hmac.compare_digest(hashlib.sha256(candidate.encode('utf-8')).digest(), bootstrap_hash):
                    raise AccessDenied('Bootstrap credential not accepted')
            public = operation in ('create_room', 'join')
            token = None if public else bearer(request)
            if token:
                service.identity.authenticate(token)
            if operation == 'connect_agent':
                # Account project bearers are tied to a validated cookie session.
                origins = request.headers.getlist('origin')
                expected = origin or base_url or str(request.base_url).rstrip('/')
                if len(origins) != 1 or origins[0] != expected:
                    return JSONResponse({'error': 'AccessDenied', 'message': 'Origin not accepted'}, status_code=403)
            if request.method == 'GET':
                name = request.scope['read_name']
                if name == 'me':
                    result = service.me(token)
                elif name == 'snapshot':
                    result = service.snapshot(token)
                elif name == 'lifecycle_event':
                    result = service.lifecycle.history_event(token, request.path_params['task_id'], request.path_params['event_id'])
                elif name == 'git_binding':
                    result = service.repositories.get_binding(token)
                elif name == 'git_observation':
                    result = service.repositories.read_observation(token,request.path_params['observation_id'])
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

    async def skill_asset(request):
        resource = request.path_params['resource']
        if resource not in ('SKILL.md', 'protocol.md'):
            return Response(status_code=404)
        return Response(files('crewmesh').joinpath('skills', 'crewmesh-connect', resource).read_bytes(),
                        media_type='text/plain', headers={'X-Content-Type-Options':'nosniff',
                        'Content-Security-Policy': WEB_CSP})

    async def web_asset(request):
        assets = {'/': ('index.html', 'text/html'),
                  '/static/styles.css': ('styles.css', 'text/css'),
                  '/static/app.js': ('app.js', 'text/javascript'),
                  '/static/git.js': ('git.js', 'text/javascript'),
                  '/static/collaboration.js': ('collaboration.js', 'text/javascript'),
                  '/static/dependencies.js': ('dependencies.js', 'text/javascript'),
                  '/static/task_lifecycle.js': ('task_lifecycle.js', 'text/javascript'),
                  '/static/accounts.js': ('accounts.js', 'text/javascript'),
                  '/static/invitations.js': ('invitations.js', 'text/javascript'),
                  '/static/billing.js': ('billing.js', 'text/javascript'),
                  '/static/icon.png': ('icon.png', 'image/png')}
        headers = {'Content-Security-Policy': WEB_CSP, 'X-Content-Type-Options': 'nosniff'}
        if request.url.path == '/favicon.ico':
            return Response(status_code=204, headers=headers)
        resource, mime = assets[request.url.path]
        return Response(files('crewmesh').joinpath('static', resource).read_bytes(), media_type=mime, headers=headers)

    routes = [Route(path, web_asset, methods=['GET']) for path in ('/', '/static/styles.css', '/static/app.js', '/static/git.js', '/static/collaboration.js', '/static/task_lifecycle.js', '/static/dependencies.js', '/static/accounts.js', '/static/invitations.js', '/static/billing.js', '/static/icon.png', '/favicon.ico')]
    routes += [route('/health', ['GET']), route('/ready', ['GET']), route('/api/rooms', ['POST'], operation='create_room'), route('/api/join', ['POST'], operation='join'),
              route('/api/me', ['GET'], read_name='me'), route('/api/snapshot', ['GET'], read_name='snapshot'),
              route('/api/invites', ['POST'], operation='invite'), route('/api/agent-token', ['POST'], operation='rotate_agent'),
              route('/api/inbox', ['GET'], read_name='inbox'),
              route('/api/agent-connect', ['POST'], operation='connect_agent'),
              Route('/skills/crewmesh-connect/{resource}', skill_asset, methods=['GET'])]
    for name in ('tasks', 'sessions', 'progress', 'overlaps', 'requests', 'contracts', 'events', 'git'):
        routes.append(route('/api/' + name, ['GET'], read_name=name))
    routes.append(route('/api/git/binding',['GET'],read_name='git_binding'))
    routes.append(route('/api/git/observations/{observation_id:int}',['GET'],read_name='git_observation'))
    for path, operation in [('/api/git/binding', 'bind_repository'), ('/api/git/observations', 'observe_repository'),
                            ('/api/checkpoints', 'checkpoint'),
                            ('/api/diagnostics/start', 'diagnostic_start'),
                            ('/api/diagnostics/read', 'diagnostic_read'),
                            ('/api/diagnostics/complete', 'diagnostic_complete'),
                            ('/api/git/checkpoint', 'repo_checkpoint'),
                            ('/api/git/team', 'read_git_team'),
                            ('/api/tasks', 'create_task'), ('/api/tasks/{task_id:int}/claim', 'claim_task'),
                            ('/api/sessions', 'register_session'), ('/api/tasks/{task_id:int}/progress', 'report_progress'),
                            ('/api/requests', 'send_request'), ('/api/requests/{request_id:int}/ack', 'acknowledge'),
                            ('/api/requests/{request_id:int}/reply', 'reply'), ('/api/requests/{request_id:int}/resolve', 'resolve_request'),
                            ('/api/requests/{request_id:int}/assign', 'assign'), ('/api/contracts', 'propose_contract'),
                            ('/api/contracts/{contract_id:int}/decision', 'decision')]:
        routes.append(route(path, ['POST'], operation=operation))
    routes.append(route('/api/dependencies', ['GET'], read_name='dependencies'))
    routes.append(route('/api/dependencies', ['POST'], operation='create_dependency'))
    routes.append(route('/api/owners/lookup', ['POST'], operation='lookup_owner'))
    for action in ('read','reply','resolve','cancel'):
        routes.append(route('/api/dependencies/{dependency_id:int}/'+action, ['POST'], operation=action+'_dependency'))
    routes.append(route('/api/tasks/{task_id:int}/history', ['POST'], operation='read_task_history'))
    routes.append(route('/api/tasks/{task_id:int}/history/{event_id:int}', ['GET'], read_name='lifecycle_event'))
    from .task_lifecycle import ACTIONS
    for action in ACTIONS:
        routes.append(route('/api/tasks/{task_id:int}/' + action.replace('_', '-'), ['POST'], operation=action))
    routes.extend(account_routes(service, mode=mode, origin=origin or base_url, bootstrap_secret=bootstrap_secret, oauth=oauth))
    from .git_routes import git_routes
    routes.extend(git_routes(service, service.github))
    routes.extend(billing_routes(service, billing_runtime, origin=origin or base_url))
    routes.append(Mount('/', app=authenticated_mcp))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.service = service
    app.state.billing_worker = billing_worker
    return LocalBoundary(app, base_url, origin, billing_webhook=store.enabled)
