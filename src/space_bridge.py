"""Native stdio MCP proxy and durable invalidations; no business rule copies."""
import argparse
import asyncio
from contextlib import asynccontextmanager, nullcontext
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit

from .bridge_event_cache import EventCache
from .spaces import checked_path, explain, private_write, read_json, read_profile
from .space_runtime import request
from .collaboration_policy import collaboration_instructions
from .errors import AccessDenied, Conflict, ValidationError


FAILURE_TEXT = {
    'network': 'The space transport is unavailable; inspect local recovery status.',
    'server': 'The space service is unavailable; inspect local recovery status.',
    'auth': 'The current personal credential was not accepted; reauthenticate before remote work.',
    'validation': 'The operation payload was rejected; correct it before trying again.',
    'conflict': 'The operation conflicts with current service state; refresh it before retrying.',
    'quota': 'The service requested a quota pause; no automatic hot retry was started.',
    'stopped': 'The owner runtime is stopped or blocked; resume it explicitly before remote work.',
    'unknown': 'The space operation failed; inspect safe local diagnostics before continuing.',
}


class BridgeStopped(RuntimeError):
    def __init__(self):
        super().__init__(FAILURE_TEXT['stopped'])


def bridge_error_kind(error):
    from .local_outbox import classify_error
    while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    if isinstance(error, BridgeStopped):
        return 'stopped'
    kind = classify_error(error)
    if kind != 'unknown':
        return kind
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    if type(status) is int:
        return classify_error(HTTPError('', status, '', {}, None))
    cls = type(error)
    if (cls.__module__.split('.')[0] in ('httpx', 'httpx2', 'httpcore')
            and any(word in cls.__name__ for word in ('Connect', 'Timeout', 'Network', 'Protocol'))):
        return 'network'
    return 'unknown'


def nested_tool_error(value, depth=0):
    if depth > 16:
        return True  # Do not certify arbitrarily deep uninspected envelopes.
    if isinstance(value, dict):
        return (value.get('isError') is True or value.get('is_error') is True
                or any(nested_tool_error(child, depth + 1) for child in value.values()))
    if isinstance(value, list):
        return any(nested_tool_error(child, depth + 1) for child in value)
    return False


def sdk_error_kind(result):
    mapping = {'AccessDenied': 'auth', 'ValidationError': 'validation', 'NotFound': 'validation',
               'Conflict': 'conflict', 'QuotaExceeded': 'quota', 'RateLimitError': 'quota'}
    payload = getattr(result, 'structured_content', None)
    if isinstance(payload, dict) and isinstance(payload.get('error'), str):
        return mapping.get(payload['error'], 'unknown')
    for block in getattr(result, 'content', []) or []:
        text = getattr(block, 'text', None)
        if not isinstance(text, str) or len(text) > 8192:
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get('error'), str):
            return mapping.get(payload['error'], 'unknown')
    return 'unknown'


def token_fingerprint(profile):
    return hashlib.sha256(profile['agent_token'].encode('utf-8')).hexdigest()


def local_diagnostics(profile_path, **kwargs):
    from .workflow_diagnostics import local_diagnostics as project_local
    return project_local(profile_path, **kwargs)


# Native team workflows remain available through an explicitly full connection.
MESSAGE_TOOLS = frozenset(('whoami', 'list_members', 'send_request', 'read_inbox', 'reply', 'read_replies',
                           'read_changes', 'install_wake'))


class Bridge:
    @property
    def status(self):
        return getattr(self, '_transport_status', 'connecting')

    @status.setter
    def status(self, value):
        self._transport_status = value
        self.status_observed_at = time.time()

    messages_only = False
    _legacy_directory = False

    def __init__(self, profile_path, *, messages_only=False):
        self.messages_only = messages_only
        self.profile_path = checked_path(profile_path)
        profile = read_profile(self.profile_path)
        self.identity = (profile['room_id'], profile['member_id'])
        self.cache = EventCache(self.profile_path, *self.identity)
        self.status = 'connecting'
        self._native_alias_supported = False
        self._native_alias_origin = profile['origin']
        from .local_outbox import LocalOutbox
        self.outbox = LocalOutbox(self.profile_path.with_name('bridge-outbox.sqlite3'), *self.identity)
        self.schema_cache_path = self.profile_path.with_name('bridge-tools.json')
        self._outbox_pause_until = 0

    def _local_profile(self):
        profile = read_profile(self.profile_path)
        if (profile['room_id'], profile['member_id']) != self.identity:
            raise AccessDenied('Personal profile identity changed')
        return profile

    def _stopped(self):
        from .space_host import policy
        try:
            document = policy(self.profile_path)
            return bool(document and (not document['desired_running'] or document['blocked']))
        except Exception:
            return True  # An invalid owner policy cannot authorize recovery.

    def _require_running(self):
        if self._stopped():
            self.status = 'stopped'
            raise BridgeStopped()

    def _outbox_summary(self):
        store = getattr(self, 'outbox', None)
        try:
            supplied = store.summary().get('counts', {}) if store else {}
        except Exception:
            supplied = {}
        if not isinstance(supplied, dict):
            supplied = {}
        counts = {key: supplied.get(key, 0) if type(supplied.get(key, 0)) is int
                  and supplied.get(key, 0) >= 0 else 0
                  for key in ('queued_locally', 'blocked', 'synced_to_service')}
        return {'counts': counts, 'model_consumption_proven': False}

    def local_changes(self, arguments):
        self._local_profile()
        if not isinstance(arguments, dict) or set(arguments) - {'after_id', 'limit'}:
            raise ValidationError('Unsupported local status arguments')
        after, limit = arguments.get('after_id', 0), arguments.get('limit', 100)
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValidationError('Invalid local status cursor or limit')
        if self.status == 'auth_denied':
            result = {'events': [], 'cursor': after, 'high_water': None, 'has_more': False,
                      'reset': 'authorization_denied', 'room_id': self.identity[0],
                      'model_read_acknowledged': False}
        else:
            result = self.cache.read(**arguments)
        outbox = self._outbox_summary()
        try:
            diagnostics = local_diagnostics(self.profile_path, transport_status=self.status,
                observed_at=getattr(self, 'status_observed_at', None), outbox=outbox)
        except Exception:
            diagnostics = {'diagnostics': [], 'read_only': True, 'model_consumption_proven': False}
        return {**result, **diagnostics, 'outbox': outbox, 'transport_status': self.status,
                'fresh': False, 'authorization_revalidated': False, 'model_read_acknowledged': False}

    def _cache_tool_schemas(self, tools):
        store = getattr(self, 'outbox', None)
        if store is None:
            return
        profile = self._local_profile()
        retained = [{'name': tool.name, 'description': (tool.description or '')[:4096],
                     'input_schema': tool.input_schema}
                    for tool in tools if store.supports(tool.name)]
        document = {'schema_version': 1, 'room_id': self.identity[0], 'member_id': self.identity[1],
                    'origin': profile['origin'], 'credential_fingerprint': token_fingerprint(profile),
                    'auth_denied': False, 'tools': retained}
        if len(json.dumps(document).encode('utf-8')) > 60000:
            return
        path = getattr(self, 'schema_cache_path', self.profile_path.with_name('bridge-tools.json'))
        private_write(path, document, update=path.exists())

    def _load_tool_schemas(self):
        from mcp.types import Tool
        if self.status == 'auth_denied':
            return []
        try:
            profile = self._local_profile()
            document = read_json(getattr(self, 'schema_cache_path', self.profile_path.with_name('bridge-tools.json')))
            if (document.get('auth_denied') is not False or
                    (document.get('room_id'), document.get('member_id'), document.get('origin'),
                     document.get('credential_fingerprint')) != (*self.identity, profile['origin'], token_fingerprint(profile))):
                return []
            tools = document.get('tools')
            if not isinstance(tools, list) or len(tools) > 5:
                return []
            return [Tool(**tool) for tool in tools if isinstance(tool, dict)
                    and self.outbox.supports(tool.get('name'))]
        except Exception:
            return []

    def _deny_schema_cache(self):
        self._native_alias_supported = False
        try:
            path = getattr(self, 'schema_cache_path', self.profile_path.with_name('bridge-tools.json'))
            document = read_json(path)
            document['auth_denied'] = True
            private_write(path, document, update=True)
        except Exception:
            pass

    def _remember_failure(self, operation, arguments, error):
        store = getattr(self, 'outbox', None)
        if store is not None and store.supports(operation) and isinstance(arguments, dict):
            try:
                store.record_failure(operation, arguments, error)
            except Exception:
                pass

    async def flush_outbox(self):
        store = getattr(self, 'outbox', None)
        if store is None or self._stopped() or self.status == 'auth_denied':
            return self._outbox_summary()
        if time.monotonic() < getattr(self, '_outbox_pause_until', 0):
            return self._outbox_summary()
        profile = self._local_profile()
        def verify_identity():
            self._require_running()
            return request(profile['origin'], '/api/me', token=profile['agent_token'])
        def sender(operation, arguments):
            self._require_running()
            result = request(profile['origin'], '/api/operations/' + operation,
                             token=profile['agent_token'], data=arguments)
            if nested_tool_error(result):
                from .local_outbox import OutboxError
                raise OutboxError('unknown')
            return result
        summary = await asyncio.to_thread(store.flush, verify_identity, sender, stopped=self._stopped, limit=20)
        reasons = {item.get('reason') for item in summary.get('items', []) if isinstance(item, dict)}
        if reasons & {'auth', 'identity_mismatch'}:
            self.status = 'auth_denied'
            self._deny_schema_cache()
        if 'quota' in reasons:
            self._outbox_pause_until = time.monotonic() + 60
        return summary

    async def verified_profile(self):
        profile = self._local_profile()
        self._require_running()
        from .space_host import ensure
        await asyncio.to_thread(ensure, self.profile_path)
        self._require_running()
        me = await asyncio.to_thread(request, profile['origin'], '/api/me', token=profile['agent_token'])
        identity = me.get('me') if isinstance(me, dict) else None
        if not isinstance(identity, dict) or (identity.get('room_id'), identity.get('member_id')) != self.identity or identity.get('kind') != 'agent':
            raise AccessDenied('Remote personal space identity does not match')
        return profile

    @asynccontextmanager
    async def remote(self):
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        import httpx2
        profile = await self.verified_profile()
        if getattr(self, '_native_alias_origin', None) != profile['origin']:
            self._native_alias_supported = False
            self._native_alias_origin = profile['origin']
        remote_host = urlsplit(profile['origin']).hostname not in ('127.0.0.1', 'localhost')
        async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+profile['agent_token'], 'Origin':profile['origin']},
                                      follow_redirects=False, trust_env=remote_host, timeout=10) as http:
            async with Client(streamable_http_client(profile['origin']+'/mcp', http_client=http),
                              cache=None, read_timeout_seconds=15) as client:
                yield client

    async def watch(self):
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed
        delay = .25
        while True:
            if self._stopped():
                self.status = 'stopped'
                return
            if self.status == 'auth_denied':
                return
            try:
                profile = await self.verified_profile()
                origin = profile['origin']
                url = ('wss' if urlsplit(origin).scheme == 'https' else 'ws') + origin[origin.index('://'):]+ '/api/events'
                # Disable SDK redirects explicitly by rejecting all reconnect redirects.
                class SameOriginConnection(connect):
                    def process_redirect(self, exc):
                        return exc
                remote_host = urlsplit(origin).hostname not in ('127.0.0.1', 'localhost')
                async with SameOriginConnection(url, origin=origin, proxy=True if remote_host else None, max_size=65536, max_queue=4,
                                                open_timeout=5, close_timeout=2, ping_interval=15, ping_timeout=15) as ws:
                    stream_cursor = self.cache.cursor
                    await ws.send(json.dumps({'token':profile['agent_token'], 'after_id':stream_cursor}))
                    ready = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if ready.get('type') != 'ready' or ready.get('protocol') != 1 or ready.get('room_id') != self.identity[0]:
                        raise ValueError('Unexpected event stream identity')
                    self.status, delay = 'online', .25
                    try:
                        await self.flush_outbox()
                    except Exception:
                        pass  # Local recovery failure must not fabricate delivery.
                    while True:
                        self._require_running()
                        if self.status == 'auth_denied':
                            return
                        frame = json.loads(await asyncio.wait_for(ws.recv(), 35))
                        self._require_running()
                        if frame.get('type') in ('events', 'reset'):
                            if not self.cache.receive(frame, expected_after_id=stream_cursor):
                                raise ValueError('Stale event stream reset; reconnect with shared cursor')
                            stream_cursor = frame['cursor']
                        elif frame.get('type') != 'heartbeat':
                            raise ValueError('Unexpected event frame')
            except asyncio.CancelledError:
                raise
            except BridgeStopped:
                self.status = 'stopped'
                return
            except HTTPError as error:
                self.status = 'auth_denied' if error.code in (401,403) else 'offline'
                if error.code in (401, 403):
                    self._deny_schema_cache()
                    return
                if error.code == 429:
                    self._outbox_pause_until = time.monotonic() + 60
                    delay = max(delay, 60)
            except ConnectionClosed as error:
                self.status = 'auth_denied' if error.rcvd and error.rcvd.code in (4401, 4403) else 'offline'
                if self.status == 'auth_denied':
                    self._deny_schema_cache()
                    return
            except Exception:
                self.status = 'offline'
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)

    async def _claim_native_alias(self, remote, context, arguments, result):
        """Best-effort metadata for an already successful, current personal claim."""
        if not getattr(self, '_native_alias_supported', False):
            return False
        native = trusted_native_identity(context)
        task = successful_tool_payload(result)
        if not native or not task or not isinstance(arguments, dict):
            return False
        logical = task.get('execution_session_key')
        task_id, epoch = task.get('id'), task.get('ownership_epoch')
        if (type(task_id) is not int or task_id <= 0 or arguments.get('task_id') != task_id
                or type(epoch) is not int or not 0 < epoch < 2**63
                or not session_identifier(logical) or arguments.get('session_key') != logical
                or task.get('state') != 'claimed'
                or (task.get('room_id'), task.get('owner_member_id')) != self.identity):
            return False
        native_id, tool = native
        metadata = {'session_key': logical, 'tool': tool, 'repository': 'unknown', 'branch': 'unknown',
                    'task_id': task_id, 'ownership_epoch': epoch, 'native_session_id': native_id}
        reported = successful_tool_payload(await remote.call_tool('register_session', metadata))
        return bool(reported and all(reported.get(key) == value for key, value in
                    {'room_id': self.identity[0], 'member_id': self.identity[1],
                     'session_key': logical, 'task_id': task_id}.items()))

    def server(self):
        from mcp.server import Server
        from mcp.types import Tool, ListToolsResult, CallToolResult, TextContent
        def failure(error):
            kind = bridge_error_kind(error)
            text = FAILURE_TEXT.get(kind, FAILURE_TEXT['unknown'])
            from .space_wake import WakeSetupError
            if isinstance(error, WakeSetupError):
                text = explain(error) or text  # Known local setup errors, never remote bodies.
            result = {'status': 'unavailable', 'reason': kind, 'delivered': False,
                      'service_applied': False, 'model_consumption_proven': False}
            return CallToolResult(is_error=True, content=[TextContent(type='text', text=text)], structured_content=result)

        def local_tools():
            return [Tool(name='read_changes', description='Read local invalidations and safe recovery diagnostics. '
                'Cached data is never fresh service state or a read receipt; denied authorization hides cached event contents.',
                input_schema={'type': 'object', 'properties': {'after_id': {'type': 'integer', 'minimum': 0, 'default': 0},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 100}}, 'additionalProperties': False})]

        def visible_tools(tools):
            if not self.messages_only:
                return tools
            names = MESSAGE_TOOLS
            offered = {tool.name for tool in tools}
            self._legacy_directory = 'read_team' in offered and 'list_members' not in offered
            if self._legacy_directory:
                # Older hosts provide the directory in their team snapshot.
                names = names | {'read_team'}
            return [tool for tool in tools if tool.name in names]

        async def list_tools(ctx, params):
            self._native_alias_supported = False
            if getattr(self, 'status', 'connecting') == 'auth_denied' or self._stopped():
                return ListToolsResult(tools=local_tools())
            try:
                self._require_running()
                async with self.remote() as remote:
                    tools, cursor = [], None
                    for _ in range(10):
                        page = await remote.list_tools(cursor=cursor)
                        tools.extend(page.tools)
                        cursor = page.next_cursor
                        if not cursor:
                            break
                    else:
                        raise ValueError('Tool list exceeded bounded pages')
                if any(t.name in LOCAL_TOOLS for t in tools):
                    raise ValueError('Remote tool name conflict')
                self._native_alias_supported = any(native_alias_advertised(tool) for tool in tools)
                self.status = 'online'
                try:
                    self._cache_tool_schemas(tools)
                except Exception:
                    pass
                tools.extend(local_tools())
                tools.append(Tool(name='install_wake', description=INSTALL_WAKE_DESCRIPTION,
                    input_schema={'type': 'object', 'properties': {
                        'tool': {'type': 'string', 'enum': ['claude', 'codex'],
                                 'description': 'Omit: detected from the connected agent'},
                        'project_dir': {'type': 'string',
                                        'description': "Omit: this session's own folder. Only for another existing folder the user named"}},
                        'additionalProperties': False}))
                return ListToolsResult(tools=visible_tools(tools))
            except Exception as error:
                kind = bridge_error_kind(error)
                self.status = 'auth_denied' if kind == 'auth' else 'offline' if kind == 'network' else 'degraded'
                if kind == 'auth':
                    self._deny_schema_cache()
                cached = self._load_tool_schemas() if kind == 'network' else []
                return ListToolsResult(tools=visible_tools(cached + local_tools()))

        async def call_tool(ctx, params):
            try:
                if (self.messages_only and params.name not in MESSAGE_TOOLS
                        and not (params.name == 'read_team' and self._legacy_directory)):
                    return CallToolResult(is_error=True, content=[TextContent(type='text', text=
                        'This connection is for messaging. Task tools require a full workflow connection.')])
                if params.name == 'read_changes':
                    data = params.arguments or {}
                    result = self.local_changes(data)
                    return CallToolResult(content=[TextContent(type='text',text=json.dumps(result))],structured_content=result)
                self._require_running()
                if getattr(self, 'status', 'connecting') == 'auth_denied':
                    raise AccessDenied('Current personal authorization is denied')
                if params.name == 'install_wake':
                    await self.verified_profile()
                    result = install_wake(self.profile_path, params.arguments, client_name(ctx))
                    return CallToolResult(content=[TextContent(type='text', text=json.dumps(result))], structured_content=result)
                async with self.remote() as remote:
                    arguments = params.arguments
                    if (params.name == 'register_session' and isinstance(arguments, dict)
                            and 'native_session_id' not in arguments and getattr(self, '_native_alias_supported', False)):
                        native = trusted_native_identity(ctx)
                        if native:
                            native_id, tool = native
                            same_harness = (arguments.get('tool') == tool or
                                tool.startswith('codex-') and arguments.get('tool') in ('codex-cli', 'codex-desktop'))
                            if same_harness:
                                arguments = {**arguments, 'native_session_id': native_id}
                    result = await remote.call_tool(params.name, arguments)
                    supplied = getattr(result, 'structured_content', None)
                    if (getattr(result, 'is_error', None) is True or nested_tool_error(supplied)
                            or isinstance(supplied, dict) and supplied.get('error') is not None):
                        from .local_outbox import OutboxError
                        error = OutboxError(sdk_error_kind(result))
                        self._remember_failure(params.name, params.arguments, error)
                        if error.reason == 'auth':
                            self.status = 'auth_denied'
                            self._deny_schema_cache()
                        if error.reason == 'quota':
                            self._outbox_pause_until = time.monotonic() + 60
                        return failure(error)
                    self.status = 'online'
                    payload = successful_tool_payload(result)
                    store = getattr(self, 'outbox', None)
                    if store is not None and store.supports(params.name) and payload is not None:
                        if params.name == 'ask_owner' and payload.get('status') in ('ambiguous', 'not_found'):
                            from .local_outbox import OutboxError
                            self._remember_failure(params.name, params.arguments, OutboxError('validation'))
                        else:
                            try:
                                store.complete(params.name, params.arguments, payload)
                            except Exception as completion_error:
                                self._remember_failure(params.name, params.arguments, completion_error)
                    if params.name == 'claim_task':
                        try:
                            await self._claim_native_alias(remote, ctx, arguments, result)
                        except Exception:
                            # Claim success and metadata reporting are separate.
                            # Never replace the claim result or assert registration.
                            pass
                    return result
            except Exception as error:
                kind = bridge_error_kind(error)
                self._remember_failure(params.name, params.arguments, error)
                if kind == 'auth':
                    self.status = 'auth_denied'
                    self._deny_schema_cache()
                if kind == 'quota':
                    self._outbox_pause_until = time.monotonic() + 60
                store = getattr(self, 'outbox', None)
                if (kind in ('network', 'server') and self.status != 'auth_denied' and not self._stopped()
                        and store is not None and store.supports(params.name)):
                    try:
                        self._local_profile()
                        queued = store.enqueue(params.name, params.arguments)
                        self.status = 'offline' if kind == 'network' else 'degraded'
                        return CallToolResult(content=[TextContent(type='text', text=json.dumps(queued))], structured_content=queued)
                    except Exception as queue_error:
                        return failure(queue_error)
                return failure(error)
        notes = ('Ordinary tools use your personal agent identity. read_changes reports local invalidations. '
                 'queued_locally means the message is still on this machine. '
                 'Optional wake hooks may start a turn with a counts-only notice. '
                 'On user request, call install_wake. Wake is on when it returns installed. '
                 'Human decisions require a current user instruction through the CLI helper or web UI.')
        if self.messages_only:
            notes += ' On older hosts use read_team when list_members is unavailable.'
        return Server('Coopagents space bridge', on_list_tools=list_tools, on_call_tool=call_tool,
                      instructions=collaboration_instructions(notes))

    async def run(self):
        from mcp.server.stdio import stdio_server
        from .p2p import member_link
        # A peer-to-peer profile reaches its host through a link held for the
        # bridge's lifetime; short CLI helpers reuse it on the same port.
        profile = self._local_profile()
        with (nullcontext() if self._stopped() else member_link(profile)):
            task = asyncio.create_task(self.watch())
            try:
                server = self.server()
                async with stdio_server() as (reader, writer):
                    await server.run(reader, writer, server.create_initialization_options())
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


# A separate CLI path, deliberately absent from ordinary agent MCP discovery.
# Credentials still enforce the shared service's web-role checks.
HUMAN_OPERATIONS = frozenset(('create_task', 'decision', 'assign', 'accept_handoff', 'reject_handoff',
    'force_handoff', 'cancel_task', 'reopen_task', 'bind_repository',
    'resolve_request', 'revoke_member'))


LOCAL_TOOLS = ('read_changes', 'install_wake')
INSTALL_WAKE_DESCRIPTION = (
    'Turn on Coopagents wake-up for the repository this session runs in: installs the native hooks that start a '
    'turn of an idle session when a teammate sends you a request, replies to yours or hands you a task. Call it '
    "without arguments: it detects Claude Code or Codex and this session's folder by itself. Pass project_dir only "
    'for another existing folder the user named. Wake-up is on only when this tool returns installed; registering a '
    'session or checking in does not turn it on.')


def client_name(ctx):
    """The connected agent's MCP client name, e.g. claude-code or codex-mcp-client."""
    try:
        return ctx.session.client_params.client_info.name
    except AttributeError:
        return None


def session_identifier(value):
    return (isinstance(value, str) and 0 < len(value) <= 200 and value == value.strip()
            and all(ord(char) >= 32 and ord(char) != 127 for char in value))


def native_alias_advertised(tool):
    if getattr(tool, 'name', None) != 'register_session':
        return False
    schema = getattr(tool, 'input_schema', None)
    properties = schema.get('properties') if isinstance(schema, dict) else None
    field = properties.get('native_session_id') if isinstance(properties, dict) else None
    if not isinstance(field, dict):
        return False
    kind = field.get('type')
    choices = field.get('anyOf')
    choices = choices if isinstance(choices, list) else []
    return (kind == 'string' or isinstance(kind, list) and 'string' in kind
            or any(isinstance(choice, dict) and choice.get('type') == 'string'
                   for choice in choices))


def trusted_native_identity(context):
    """Only inherited native-process environment supplies a conversation ID."""
    name = client_name(context)
    family = agent_tool(name)
    values = {'codex': os.environ.get('CODEX_THREAD_ID'), 'claude': os.environ.get('CLAUDE_SESSION_ID')}
    if family is None:
        candidates = [kind for kind, value in values.items() if session_identifier(value)]
        if len(candidates) != 1:
            return None
        family = candidates[0]
    value = values[family]
    if not session_identifier(value):
        return None
    tool = ('claude-code' if family == 'claude' else
            'codex-desktop' if (name or '').lower().startswith('codex-desktop') else 'codex-cli')
    return value, tool


def successful_tool_payload(result):
    """Do not infer SDK success or task identity from a text content block."""
    if getattr(result, 'is_error', None) is not False:
        return None
    data = getattr(result, 'structured_content', None)
    if not isinstance(data, dict) or data.get('error') is not None or nested_tool_error(data):
        return None
    return data


def agent_tool(name):
    name = (name or '').lower()
    return 'claude' if name.startswith('claude') else 'codex' if name.startswith('codex') else None


def session_folder(tool):
    """Both agents start MCP servers in the session's folder; Claude Code also names it in CLAUDE_PROJECT_DIR."""
    import os
    return (tool == 'claude' and os.environ.get('CLAUDE_PROJECT_DIR')) or os.getcwd()


def install_wake(profile_path, arguments, client=None):
    """Install wake hooks with this bridge's own Python and profile; the agent needs to pass nothing."""
    from .space_wake import WakeSetupError, install
    data = arguments or {}
    if not isinstance(data, dict) or set(data) - {'tool', 'project_dir'}:
        raise WakeSetupError('install_wake accepts only tool and project_dir; call it without arguments')
    tool = data.get('tool') or agent_tool(client)
    if tool not in ('claude', 'codex'):
        raise WakeSetupError("Could not tell whether this agent is Claude Code or Codex; pass tool 'claude' or 'codex'")
    default = session_folder(tool)
    project = data.get('project_dir') or default
    if not isinstance(project, str) or not Path(project).is_dir():
        raise WakeSetupError("The folder %s does not exist. Call install_wake without project_dir to use this "
                             "session's folder, %s." % (project, default))
    result = install(str(profile_path), tool, 'project', project)
    result['next'] = ('Tell the user: the hooks load when they start a new Claude Code session in %s.' % project
                      if tool == 'claude' else
                      'Tell the user to review and trust the Coopagents hook in /hooks; Codex runs it after that.')
    return result


def human_operation(profile_path, operation, payload_path):
    if operation not in HUMAN_OPERATIONS:
        raise ValueError('Unsupported human operation; use dedicated runtime commands')
    profile = read_profile(profile_path)
    if not profile.get('web_token'):
        raise ValueError('This profile has no human credential; use the service web interface')
    from .p2p import member_link
    with member_link(profile):
        return _human_operation(profile, operation, payload_path)


def _human_operation(profile, operation, payload_path):
    identity = request(profile['origin'], '/api/me', token=profile['web_token'])['me']
    if (identity['room_id'], identity['member_id'], identity['kind']) != (profile['room_id'], profile['member_id'], 'web'):
        raise ValueError('Human profile identity mismatch')
    payload = read_json(payload_path)
    payload.pop('schema_version')
    return request(profile['origin'], '/api/operations/'+operation, token=profile['web_token'], data=payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Private stdio MCP space bridge')
    parser.add_argument('--profile', required=True)
    parser.add_argument('--messages-only', action='store_true', help='Expose the teammate messaging tools')
    parser.add_argument('--human-operation', choices=sorted(HUMAN_OPERATIONS))
    parser.add_argument('--payload-file')
    args = parser.parse_args(argv)
    # Third-party transport logs and exceptions can include credentials/URLs.
    logging.disable(logging.CRITICAL)
    try:
        if args.human_operation:
            if not args.payload_file:
                raise ValueError('Human operation requires a private payload file')
            human_operation(args.profile, args.human_operation, args.payload_file)
            print(json.dumps({'status':'applied', 'operation':args.human_operation}))
        else:
            if args.payload_file:
                raise ValueError('Payload file requires human operation')
            asyncio.run(Bridge(args.profile, messages_only=args.messages_only).run())
        return 0
    except Exception as error:
        print(explain(error) or 'Space bridge failed; verify private profile and runtime health.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
