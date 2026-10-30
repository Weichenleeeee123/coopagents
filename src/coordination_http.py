"""HTTP adapters shared by hosted and agent-managed compositions."""
import asyncio
import json
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route
from .errors import AccessDenied, Conflict, NotFound, ValidationError


OPERATION_PATHS = {
    '/api/capabilities/evidence': 'record_capability',
    '/api/invites': 'invite', '/api/agent-token': 'rotate_agent',
    '/api/agent-connect': 'connect_agent', '/api/tasks': 'create_task',
    '/api/tasks/{task_id:int}/claim': 'claim_task', '/api/sessions': 'register_session',
    '/api/tasks/{task_id:int}/progress': 'report_progress', '/api/requests': 'send_request',
    '/api/requests/{request_id:int}/ack': 'acknowledge',
    '/api/requests/{request_id:int}/reply': 'reply',
    '/api/requests/{request_id:int}/resolve': 'resolve_request',
    '/api/requests/{request_id:int}/assign': 'assign', '/api/contracts': 'propose_contract',
    '/api/contracts/{contract_id:int}/decision': 'decision',
    '/api/checkpoints': 'checkpoint', '/api/diagnostics/start': 'diagnostic_start',
    '/api/diagnostics/read': 'diagnostic_read', '/api/diagnostics/complete': 'diagnostic_complete',
    '/api/git/binding': 'bind_repository', '/api/git/observations': 'observe_repository',
    '/api/git/checkpoint': 'repo_checkpoint', '/api/git/team': 'read_git_team',
    '/api/dependencies': 'create_dependency', '/api/owners/lookup': 'lookup_owner',
    '/api/tasks/{task_id:int}/history': 'read_task_history',
    '/api/git/delivery': 'link_delivery',
}


def coordination_routes(service, *, base_url=None, public_url=None, include_named=False):
    origin = public_url or base_url

    async def endpoint(request):
        try:
            credentials = request.headers.getlist('authorization')
            if (len(credentials) != 1 or not credentials[0].startswith('Bearer ')
                    or not credentials[0][7:] or any(c.isspace() for c in credentials[0][7:])):
                raise AccessDenied('Credential not accepted')
            token = credentials[0][7:]
            principal = await run_in_threadpool(service.identity.authenticate, token)
            operation = request.scope.get('coordination_operation', request.path_params.get('operation'))
            read = request.scope.get('coordination_read')
            if request.query_params and read not in ('inbox', 'context'):
                raise ValidationError('Query parameters not accepted')
            if request.method == 'GET':
                if read == 'me':
                    result = await run_in_threadpool(service.me, token)
                elif read in ('snapshot', 'agent_snapshot'):
                    if read == 'agent_snapshot':
                        await run_in_threadpool(service.identity.authenticate, token, 'agent')
                    result = await run_in_threadpool(service.snapshot, token, web=principal.kind == 'web')
                elif read == 'inbox':
                    if any(k not in ('after_id', 'limit') for k in request.query_params):
                        raise ValidationError('Unsupported inbox query')
                    try:
                        data = {k: int(v) for k, v in request.query_params.items()}
                    except ValueError:
                        raise ValidationError('Invalid inbox query') from None
                    result = await run_in_threadpool(service.call, 'read_inbox', token, data)
                elif read == 'capabilities':
                    result = await run_in_threadpool(service.read_capabilities, token)
                elif read == 'context':
                    if any(k not in ('task_id', 'member_id', 'limit') or len(request.query_params.getlist(k)) != 1
                           for k in request.query_params):
                        raise ValidationError('Unsupported context query parameter')
                    values = dict(request.query_params)
                    try:
                        data = {'task_id': int(values['task_id'])} if 'task_id' in values else {}
                        if 'member_id' in values:
                            data['member_id'] = values['member_id']
                        if 'limit' in values:
                            data['limit'] = int(values['limit'])
                    except ValueError:
                        raise ValidationError('Invalid context query parameter') from None
                    result = await run_in_threadpool(service.read_context, token, **data)
                else:
                    result = await run_in_threadpool(service.reads[read], token)
            else:
                if operation not in service.operations or service.operations[operation][0] is None:
                    raise AccessDenied('Bootstrap operations are not available through this adapter')
                if principal.kind == 'web':
                    expected = origin or str(request.base_url).rstrip('/')
                    if request.headers.getlist('origin') != [expected]:
                        raise AccessDenied('Origin not accepted')
                if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                    raise ValidationError('Expected application/json')
                async def body():
                    raw = bytearray()
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 65536:
                            raise ValidationError('Request body too large')
                    return raw
                raw = await asyncio.wait_for(body(), 10)
                try:
                    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError, RecursionError):
                    raise ValidationError('Malformed JSON') from None
                if not isinstance(data, dict):
                    raise ValidationError('Expected an object')
                for key, value in request.path_params.items():
                    if key != 'operation':
                        if key in data and data[key] != value:
                            raise ValidationError('Path and payload differ')
                        data[key] = value
                result = await run_in_threadpool(service.call, operation, token, data)
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except (AccessDenied, Conflict, NotFound, ValidationError) as error:
            kind, status = next((kind, status) for kind, status in
                                ((AccessDenied,401),(Conflict,409),(NotFound,404),(ValidationError,400))
                                if isinstance(error, kind))
            payload = {'error':kind.__name__, 'message':str(error)}
            if isinstance(error, Conflict) and error.owner_member_id is not None:
                payload['owner_member_id'] = error.owner_member_id
            return JSONResponse(payload, status_code=status, headers={'Cache-Control':'no-store'})
        except TimeoutError:
            return JSONResponse({'error':'ValidationError','message':'Request timed out'}, status_code=408)

    def route(path, method, *, operation=None, read=None):
        async def handle(request):
            request.scope['coordination_operation'] = operation or request.path_params.get('operation')
            request.scope['coordination_read'] = read
            return await endpoint(request)
        return Route(path, handle, methods=[method])

    routes = [route('/api/operations/{operation}', 'POST'),
              route('/api/agent-snapshot', 'GET', read='agent_snapshot'),
              route('/api/context', 'GET', read='context'),
              route('/api/capabilities', 'GET', read='capabilities')]
    if include_named:
        routes.extend(route(path, 'POST', operation=operation) for path, operation in OPERATION_PATHS.items())
        from .task_lifecycle import ACTIONS
        routes.extend(route('/api/tasks/{task_id:int}/'+action.replace('_','-'), 'POST', operation=action) for action in ACTIONS)
        routes.extend(route('/api/dependencies/{dependency_id:int}/'+action, 'POST', operation=action+'_dependency') for action in ('read','reply','resolve','cancel'))
        routes.extend([route('/api/me','GET',read='me'), route('/api/snapshot','GET',read='snapshot'),
                       route('/api/context','GET',read='context'), route('/api/inbox','GET',read='inbox')])
        routes.extend(route('/api/'+name, 'GET', read=name) for name in service.reads)
    return routes
