"""Bridge recovery contracts with fake transport/stores, never native execution."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

from mcp.types import CallToolResult, TextContent, Tool

from coopagents import space_bridge


ALLOWED = {'ask_owner', 'send_request', 'reply', 'reply_dependency', 'create_dependency'}
PROFILE = dict(schema_version=1, origin='http://127.0.0.1:9', room_id='room', member_id='member', agent_token='PRIVATE-TOKEN')


class Outbox:
    def __init__(self):
        self.queued, self.completed, self.failures = [], [], []
        self.flushed = []

    def supports(self, operation):
        return operation in ALLOWED

    def enqueue(self, operation, arguments):
        self.queued.append((operation, deepcopy(arguments)))
        return dict(status='queued_locally', delivered=False, service_applied=False, outbox_id=1,
                    operation=operation, attempts=0, model_consumption_proven=False)

    def complete(self, operation, arguments, result):
        self.completed.append((operation, deepcopy(arguments), deepcopy(result)))

    def record_failure(self, operation, arguments, error):
        self.failures.append((operation, deepcopy(arguments)))

    def summary(self):
        return {'counts': {'queued_locally': len(self.queued), 'blocked': 0, 'synced_to_service': len(self.completed)},
                'items': [{'args': 'OUTBOX-PRIVATE-BODY', 'reason': 'PRIVATE-ERROR'}],
                'model_consumption_proven': False}

    def flush(self, verify_identity, sender, stopped=lambda: False, limit=20):
        if stopped():
            return self.summary()
        try:
            identity = verify_identity().get('me')
            if identity != dict(room_id='room', member_id='member', kind='agent'):
                return self.summary()
            for operation, arguments in self.queued[:limit]:
                if stopped():
                    break
                sender(operation, arguments)
                self.flushed.append((operation, deepcopy(arguments)))
        except Exception:
            pass
        return self.summary()


class Cache:
    def __init__(self):
        self.calls = 0

    def read(self, **data):
        self.calls += 1
        return dict(events=[{'entity_id': 'CACHED-PRIVATE-ID'}], cursor=4, high_water=4,
                    room_id='room', has_more=False, reset=None, model_read_acknowledged=False)


class Remote:
    def __init__(self, *, error=None, result=None):
        self.error, self.calls = error, []
        self.result = result or CallToolResult(is_error=False, structured_content={'id': 7}, content=[])

    async def list_tools(self, cursor=None):
        if self.error:
            raise self.error
        return SimpleNamespace(tools=[Tool(name='ask_owner', description='Technical question', input_schema={})], next_cursor=None)

    async def call_tool(self, operation, arguments):
        self.calls.append((operation, deepcopy(arguments)))
        if self.error:
            raise self.error
        return self.result


class BridgeOutboxTests(unittest.TestCase):
    def bridge(self, *, error=None, result=None, status='online', stopped=False):
        bridge = space_bridge.Bridge.__new__(space_bridge.Bridge)
        bridge.identity, bridge.profile_path, bridge.status = ('room', 'member'), Path('unused-private-profile'), status
        bridge.cache, bridge.outbox = Cache(), Outbox()
        bridge._stopped = lambda: stopped
        bridge._cache_tool_schemas = lambda tools: None
        bridge._load_tool_schemas = lambda: [Tool(name='ask_owner', description='Cached technical schema', input_schema={})]
        bridge._deny_schema_cache = lambda: None
        remote = Remote(error=error, result=result)
        @asynccontextmanager
        async def connection():
            yield remote
        bridge.remote = connection
        bridge.verified_profile = AsyncMock(side_effect=AssertionError('local read must not verify or start a host'))
        return bridge, remote

    def server(self, bridge):
        with patch('mcp.server.Server', side_effect=lambda *a, **kwargs: SimpleNamespace(**kwargs)):
            return bridge.server()

    def call(self, bridge, operation, arguments):
        with patch.object(space_bridge, 'read_profile', return_value=PROFILE):
            return asyncio.run(self.server(bridge).on_call_tool(SimpleNamespace(),
                SimpleNamespace(name=operation, arguments=arguments)))

    def test_messaging_connection_filters_online_and_cached_discovery(self):
        bridge, remote = self.bridge()
        bridge.messages_only = True
        offered = ['whoami', 'list_members', 'read_team', 'send_request', 'reply', 'read_replies',
                   'read_inbox', 'claim_task', 'work_brief', 'find_related', 'share_work', 'remember_choice']
        schemas = [Tool(name=name, input_schema={}) for name in offered]
        remote.list_tools = AsyncMock(return_value=SimpleNamespace(tools=schemas, next_cursor=None))
        server = self.server(bridge)
        names = lambda: {tool.name for tool in asyncio.run(server.on_list_tools(SimpleNamespace(), None)).tools}
        self.assertEqual(names(), space_bridge.MESSAGE_TOOLS)
        for name in ('claim_task', 'work_brief', 'read_team'):
            self.assertTrue(self.call(bridge, name, {}).is_error)
        self.assertEqual(remote.calls, [])
        bridge._load_tool_schemas = lambda: schemas
        remote.list_tools.side_effect = ConnectionError()
        self.assertEqual(names(), space_bridge.MESSAGE_TOOLS - {'install_wake'})
        self.assertEqual(bridge.outbox.queued, [])
        remote.list_tools.side_effect = None
        remote.list_tools.return_value = SimpleNamespace(tools=[t for t in schemas if t.name != 'list_members'],
                                                        next_cursor=None)
        self.assertIn('read_team', names())

    def test_transport_failure_persists_only_allowed_idempotent_intent_as_not_delivered(self):
        bridge, _ = self.bridge(error=ConnectionError('RAW-PRIVATE-REMOTE-BODY'))
        arguments = {'request_key': 'stable-key', 'body': 'Private technical question',
                     'source_task_id': 7, 'session_key': 'old-execution', 'ownership_epoch': 3}
        result = self.call(bridge, 'ask_owner', arguments)
        self.assertFalse(result.is_error, 'local durable enqueue is a distinct successful local operation')
        self.assertEqual(result.structured_content['status'], 'queued_locally')
        self.assertIs(result.structured_content['delivered'], False)
        self.assertIs(result.structured_content['service_applied'], False)
        self.assertEqual(bridge.outbox.queued, [('ask_owner', arguments)])
        self.assertNotIn('RAW-PRIVATE', result.model_dump_json())

    def test_auth_validation_conflict_quota_and_unknown_errors_never_create_a_queue_record(self):
        for code in (400, 401, 403, 404, 409, 422, 429):
            bridge, _ = self.bridge(error=HTTPError(PROFILE['origin'], code, 'RAW-PRIVATE', {}, None))
            with self.subTest(code=code):
                result = self.call(bridge, 'ask_owner', {'request_key': 'q', 'body': 'Question'})
                self.assertTrue(result.is_error)
                self.assertEqual(bridge.outbox.queued, [])
                self.assertNotIn('RAW-PRIVATE', result.model_dump_json())
        bridge, _ = self.bridge(error=RuntimeError('RAW-PRIVATE-UNKNOWN'))
        self.assertTrue(self.call(bridge, 'ask_owner', {'request_key': 'q', 'body': 'Question'}).is_error)
        self.assertEqual(bridge.outbox.queued, [])

    def test_reads_ack_resolution_human_and_host_operations_are_never_queued(self):
        for operation in ('read_inbox', 'read_replies', 'acknowledge', 'resolve_request',
                          'decision', 'accept_handoff', 'create_task', 'start'):
            bridge, _ = self.bridge(error=ConnectionError('offline'))
            with self.subTest(operation=operation):
                self.assertTrue(self.call(bridge, operation, {'request_key': 'q'}).is_error)
                self.assertEqual(bridge.outbox.queued, [])

    def test_live_success_completes_old_intent_but_nested_sdk_error_does_not(self):
        payload = {'request': {'id': 7}}
        successful = CallToolResult(is_error=False, structured_content=payload, content=[])
        bridge, _ = self.bridge(result=successful)
        arguments = {'request_key': 'q', 'body': 'Question'}
        self.assertIs(self.call(bridge, 'ask_owner', arguments), successful)
        self.assertEqual(bridge.outbox.completed, [('ask_owner', arguments, payload)])
        for error_result in (CallToolResult(is_error=True, structured_content={'error': 'Conflict'}, content=[]),
                CallToolResult(is_error=False, structured_content={'result': {'isError': True, 'message': 'RAW-PRIVATE'}}, content=[])):
            bridge, _ = self.bridge(result=error_result)
            result = self.call(bridge, 'ask_owner', arguments)
            self.assertEqual(bridge.outbox.completed, [])
            self.assertEqual(bridge.outbox.queued, [])
            self.assertTrue(result.is_error)
            self.assertNotIn('RAW-PRIVATE', result.model_dump_json())

    def test_nonpersisted_owner_candidates_keep_native_result_and_block_only_old_intent(self):
        arguments = {'request_key': 'q', 'body': 'Question', 'scope': 'src/api'}
        for status in ('ambiguous', 'not_found'):
            payload = {'status': status, 'candidates': [], 'request': None, 'dependency': None}
            original = CallToolResult(is_error=False, structured_content=payload, content=[])
            bridge, _ = self.bridge(result=original)
            bridge.outbox.queued = [('ask_owner', arguments)]
            self.assertIs(self.call(bridge, 'ask_owner', arguments), original)
            self.assertEqual(bridge.outbox.completed, [])
            self.assertEqual(bridge.outbox.failures, [('ask_owner', arguments)])
            self.assertEqual(bridge.outbox.queued, [('ask_owner', arguments)])
        original = CallToolResult(is_error=False, structured_content={'status': 'unassigned', 'request': None}, content=[])
        bridge, _ = self.bridge(result=original)
        self.assertIs(self.call(bridge, 'ask_owner', arguments), original)
        self.assertEqual(len(bridge.outbox.completed), 1, 'a service-persisted waiting question can be synchronized')

    def test_offline_changes_are_local_unfresh_and_only_return_safe_outbox_counts(self):
        bridge, _ = self.bridge(status='offline')
        with patch('coopagents.workflow_diagnostics.local_diagnostics', return_value={
                'diagnostics': [], 'read_only': True, 'model_consumption_proven': False}) as diagnostics:
            result = self.call(bridge, 'read_changes', {})
        self.assertFalse(result.is_error)
        self.assertFalse(result.structured_content['fresh'])
        self.assertIn('diagnostics', result.structured_content)
        self.assertIn('counts', result.structured_content['outbox'])
        self.assertNotIn('OUTBOX-PRIVATE', result.model_dump_json())
        bridge.verified_profile.assert_not_awaited()
        diagnostics.assert_called_once()

    def test_auth_denied_exposes_only_local_status_not_cached_event_contents(self):
        bridge, _ = self.bridge(status='auth_denied')
        with patch('coopagents.workflow_diagnostics.local_diagnostics', return_value={'diagnostics': []}):
            result = self.call(bridge, 'read_changes', {})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content['events'], [])
        self.assertEqual(bridge.cache.calls, 0)
        self.assertNotIn('CACHED-PRIVATE', result.model_dump_json())

    def test_cached_technical_schema_is_network_only_and_auth_denial_is_local_only(self):
        for error, expected in ((ConnectionError('offline'), {'ask_owner', 'read_changes'}),
                (HTTPError(PROFILE['origin'], 401, 'private', {}, None), {'read_changes'}),
                (RuntimeError('unknown-private'), {'read_changes'})):
            bridge, _ = self.bridge(error=error)
            with patch.object(space_bridge, 'read_profile', return_value=PROFILE):
                listed = asyncio.run(self.server(bridge).on_list_tools(SimpleNamespace(), None))
            self.assertEqual({tool.name for tool in listed.tools}, expected)

    def test_protected_schema_cache_is_identity_credential_bound_and_technical_only(self):
        bridge, _ = self.bridge()
        tools = [Tool(name=name, description='Static tool', input_schema={'type': 'object'})
                 for name in ('ask_owner', 'read_inbox', 'decision')]
        with patch.object(space_bridge, 'read_profile', return_value=PROFILE), \
                patch.object(space_bridge, 'private_write') as write:
            space_bridge.Bridge._cache_tool_schemas(bridge, tools)
        document = write.call_args.args[1]
        self.assertEqual([tool['name'] for tool in document['tools']], ['ask_owner'])
        self.assertNotIn(PROFILE['agent_token'], json.dumps(document))
        self.assertFalse(document['auth_denied'])
        with patch.object(space_bridge, 'read_profile', return_value=PROFILE), \
                patch.object(space_bridge, 'read_json', return_value=document):
            self.assertEqual([tool.name for tool in space_bridge.Bridge._load_tool_schemas(bridge)], ['ask_owner'])
        for changed in ({'member_id': 'foreign'}, {'credential_fingerprint': 'other'}, {'auth_denied': True}):
            with self.subTest(changed=changed), patch.object(space_bridge, 'read_profile', return_value=PROFILE), \
                    patch.object(space_bridge, 'read_json', return_value={**document, **changed}):
                self.assertEqual(space_bridge.Bridge._load_tool_schemas(bridge), [])

    def test_sdk_error_text_is_classified_without_forwarding_the_remote_body(self):
        result = CallToolResult(is_error=True, content=[TextContent(type='text',
            text=json.dumps({'error': 'Conflict', 'message': 'RAW-PRIVATE-REMOTE-ERROR'}))])
        bridge, _ = self.bridge(result=result)
        response = self.call(bridge, 'ask_owner', {'request_key': 'q', 'body': 'Question'})
        self.assertTrue(response.is_error)
        self.assertEqual(response.structured_content['reason'], 'conflict')
        self.assertNotIn('RAW-PRIVATE', response.model_dump_json())
        self.assertEqual(bridge.outbox.completed, [])

    def test_quota_pause_prevents_automatic_flush_hot_retries(self):
        bridge, _ = self.bridge(error=HTTPError(PROFILE['origin'], 429, '', {}, None))
        bridge.outbox.queued = [('ask_owner', {'request_key': 'q', 'body': 'Question'})]
        self.assertTrue(self.call(bridge, 'ask_owner', bridge.outbox.queued[0][1]).is_error)
        with patch.object(space_bridge, 'request', side_effect=AssertionError('quota is paused')):
            asyncio.run(bridge.flush_outbox())
            asyncio.run(bridge.flush_outbox())
        self.assertEqual(bridge.outbox.flushed, [])

    def test_stopped_background_watcher_never_connects_or_verifies(self):
        bridge, _ = self.bridge(stopped=True)
        asyncio.run(bridge.watch())
        bridge.verified_profile.assert_not_awaited()
        self.assertEqual(bridge.status, 'stopped')

    def test_flush_does_not_send_after_user_stops_during_identity_verification(self):
        bridge, _ = self.bridge()
        bridge.outbox.queued = [('ask_owner', {'request_key': 'q', 'body': 'Question'})]
        state = {'stopped': False}
        bridge._stopped = lambda: state['stopped']
        def verify_then_stop(origin, path, **kwargs):
            self.assertEqual(path, '/api/me')
            state['stopped'] = True
            return {'me': dict(room_id='room', member_id='member', kind='agent')}
        with patch.object(space_bridge, 'read_profile', return_value=PROFILE), \
                patch.object(space_bridge, 'request', side_effect=verify_then_stop) as request:
            asyncio.run(bridge.flush_outbox())
        self.assertEqual(request.call_count, 1)
        self.assertEqual(bridge.outbox.flushed, [])

    def test_message_text_that_looks_like_json_is_not_executed_as_an_error_envelope(self):
        payload = {'request': {'body': '{"isError":true}'}}
        bridge, _ = self.bridge(result=CallToolResult(is_error=False, structured_content=payload, content=[]))
        self.assertFalse(self.call(bridge, 'ask_owner', {'request_key': 'q', 'body': 'Question'}).is_error)
        self.assertEqual(len(bridge.outbox.completed), 1)

    def test_flush_revalidates_identity_without_ensure_and_preserves_old_epoch_payload(self):
        self.assertTrue(hasattr(space_bridge.Bridge, 'flush_outbox'), 'bounded replay helper is missing')
        bridge, _ = self.bridge()
        arguments = dict(request_key='q', body='Question', session_key='old-execution', ownership_epoch=3)
        bridge.outbox.queued = [('ask_owner', arguments)]
        def request(origin, path, *, token, data=None):
            self.assertEqual((origin, token), (PROFILE['origin'], PROFILE['agent_token']))
            return {'me': dict(room_id='room', member_id='member', kind='agent')} if path == '/api/me' else {'id': 7}
        with patch.object(space_bridge, 'read_profile', return_value=PROFILE), \
                patch.object(space_bridge, 'request', side_effect=request) as send, \
                patch('coopagents.space_host.ensure', side_effect=AssertionError('flush must not start a host')):
            asyncio.run(bridge.flush_outbox())
        self.assertEqual(send.call_args_list[0].args[1], '/api/me')
        self.assertEqual(send.call_args_list[1].kwargs['data'], arguments)
        self.assertEqual(bridge.outbox.flushed, [('ask_owner', arguments)])
        bridge.verified_profile.assert_not_awaited()

    def test_explicit_stopped_policy_prevents_flush_and_live_network_attempts(self):
        self.assertTrue(hasattr(space_bridge.Bridge, 'flush_outbox'), 'bounded replay helper is missing')
        bridge, remote = self.bridge(stopped=True)
        bridge.outbox.queued = [('ask_owner', {'request_key': 'q', 'body': 'Question'})]
        with patch.object(space_bridge, 'request', side_effect=AssertionError('stopped means no network')):
            asyncio.run(bridge.flush_outbox())
            result = self.call(bridge, 'ask_owner', {'request_key': 'q', 'body': 'Question'})
        self.assertTrue(result.is_error)
        self.assertEqual(remote.calls, [])
        self.assertEqual(bridge.outbox.flushed, [])

    def test_verified_profile_does_not_ensure_when_owner_is_stopped_or_blocked(self):
        bridge, _ = self.bridge()
        # Exercise the real local-policy check, not this fixture's shortcut.
        if '_stopped' in bridge.__dict__:
            del bridge.__dict__['_stopped']
        for policy in (dict(desired_running=False, blocked=False), dict(desired_running=True, blocked=True)):
            with patch.object(space_bridge, 'read_profile', return_value=PROFILE), \
                    patch('coopagents.space_host.policy', return_value=policy), \
                    patch('coopagents.space_host.ensure', side_effect=AssertionError('must not revive')) as ensure, \
                    patch.object(space_bridge, 'request', side_effect=AssertionError('must not connect')) as request:
                with self.assertRaises(Exception):
                    asyncio.run(space_bridge.Bridge.verified_profile(bridge))
                ensure.assert_not_called()
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
