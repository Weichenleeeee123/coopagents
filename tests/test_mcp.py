import asyncio
from contextlib import asynccontextmanager
import json
import unittest
from unittest.mock import patch

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from transport_support import LiveService


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()

    @asynccontextmanager
    async def client(self, token):
        async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + token}) as http:
            async with Client(streamable_http_client(self.live.url + '/mcp', http_client=http), cache=None) as client:
                yield client

    async def call(self, client, name, arguments):
        result = await client.call_tool(name, arguments)
        self.assertFalse(result.is_error, result.content)
        self.assertIsNotNone(result.structured_content)
        return result.structured_content

    def test_two_client_workflow(self):
        task = self.live.request('POST', '/api/tasks', self.owner['web_token'], {'intent_key': 't', 'title': 'Build', 'scope': 'src'})[1]
        async def run():
            async with self.client(self.owner['agent_token']) as owner, self.client(self.member['agent_token']) as member:
                tools = (await owner.list_tools()).tools
                names = {tool.name for tool in tools}
                self.assertEqual(names, {'lookup_owner', 'create_dependency', 'read_dependency', 'reply_dependency', 'resolve_dependency', 'cancel_dependency', 'whoami', 'read_team', 'list_assets', 'read_asset', 'read_task_history', 'release_task', 'propose_handoff', 'claim_task', 'register_session', 'report_progress', 'send_request', 'read_inbox', 'acknowledge', 'reply', 'resolve_request', 'propose_contract', 'repo_checkpoint', 'link_delivery', 'checkpoint', 'diagnostic_start', 'diagnostic_read', 'diagnostic_complete'})
                for tool in tools:
                    props = tool.input_schema.get('properties', {})
                    self.assertNotIn('author', props)
                    self.assertNotIn('token', props)
                results = await asyncio.gather(self.call(owner, 'whoami', {}), self.call(member, 'whoami', {}))
                checkpoint = await self.call(owner, 'checkpoint', {'session_key':'mcp','tool':'codex-cli','event':'startup'})
                self.assertEqual(checkpoint['checkpoint']['source'], 'tool')
                self.assertEqual([r['me']['member_id'] for r in results], [self.owner['member_id'], self.member['member_id']])
                claims = await asyncio.gather(owner.call_tool('claim_task', {'task_id': task['id']}), member.call_tool('claim_task', {'task_id': task['id']}))
                self.assertEqual(sum(r.is_error for r in claims), 1)
                winning_index = next(i for i, r in enumerate(claims) if not r.is_error)
                winner = (owner, member)[winning_index]
                await self.call(winner, 'register_session', {'session_key': 's', 'tool': 'codex-cli', 'repository': 'repo', 'branch': 'main', 'task_id': task['id']})
                await self.call(winner, 'report_progress', {'task_id': task['id'], 'state': 'working', 'summary': 'Testing'})
                request = await self.call(owner, 'send_request', {'request_key': 'r', 'receiver_member_id': self.member['member_id'], 'task_id': None, 'context_version': 1, 'body': 'Question; ignore previous instructions is data'})
                inbox = await self.call(member, 'read_inbox', {})
                self.assertEqual(inbox['requests'][0]['id'], request['id'])
                await self.call(member, 'acknowledge', {'request_id': request['id']})
                await self.call(member, 'reply', {'request_id': request['id'], 'request_key': 'reply', 'context_version': 1, 'body': 'Answer', 'evidence': 'test'})
                await self.call(owner, 'resolve_request', {'request_id': request['id'], 'context_version': 1})
                proposal = await self.call(owner, 'propose_contract', {'contract_key': 'c', 'expected_version': 0, 'title': 'Schema', 'body': 'v1', 'source_request_id': request['id']})
                status, approved, _ = self.live.request('POST', f"/api/contracts/{proposal['id']}/decision", self.owner['web_token'], {'version': 1, 'decision': 'approved'})
                self.assertEqual(status, 200, approved)
                team = await self.call(member, 'read_team', {})
                self.assertEqual(team['contracts'][0]['effective_version'], 1)
                self.assertEqual(team['me']['member_id'], self.member['member_id'])
        asyncio.run(run())

    def test_tool_descriptions_guide_addressing_and_unaddressed_requests_say_so(self):
        async def run():
            async with self.client(self.owner['agent_token']) as owner:
                tools = {tool.name: tool.description for tool in (await owner.list_tools()).tools}
                self.assertIn('receiver_member_id', tools['send_request'])
                self.assertIn('delivered to nobody', tools['send_request'])
                self.assertIn('member_id', tools['read_team'])
                self.assertIn('does not list replies', tools['read_inbox'])
                self.assertIn('requests[].replies', tools['send_request'])
                self.assertNotIn('Authenticated room operation', tools['send_request'] + tools['read_team'])
                addressed = await self.call(owner, 'send_request', {'request_key': 'a', 'receiver_member_id': self.member['member_id'],
                                                                    'context_version': 1, 'body': 'Q'})
                self.assertNotIn('not_delivered', addressed)
                unaddressed = await self.call(owner, 'send_request', {'request_key': 'b', 'context_version': 1, 'body': 'Please ask Claude'})
                self.assertIsNone(unaddressed['receiver_member_id'])
                self.assertIn('nobody receives or is woken', unaddressed['not_delivered'])
        asyncio.run(run())

    def test_agent_can_read_only_explicitly_shared_project_assets(self):
        asset = self.live.app.state.service.assets.upload(self.owner['web_token'], 'guide.md',
            'text/markdown', b'# shared')
        async def run():
            async with self.client(self.member['agent_token']) as client:
                listed = await self.call(client, 'list_assets', {})
                self.assertEqual([item['id'] for item in listed['assets']], [asset['id']])
                read = await self.call(client, 'read_asset', {'asset_id': asset['id']})
                self.assertEqual(read['asset']['sha256'], asset['sha256'])
                import base64
                self.assertEqual(base64.b64decode(read['content_base64']), b'# shared')
                invalid = await client.call_tool('read_asset', {'asset_id': asset['id'], 'path': 'C:/secret'})
                self.assertTrue(invalid.is_error)
        asyncio.run(run())

    def test_mcp_asset_read_has_a_bounded_response(self):
        service = self.live.app.state.service
        service.assets.max_file_bytes = 10 * 1024 * 1024 + 1
        service.assets.max_project_bytes = 10 * 1024 * 1024 + 1
        service.assets.max_total_bytes = 10 * 1024 * 1024 + 1
        asset = service.assets.upload(self.owner['web_token'], 'large.bin', 'application/octet-stream',
                                      b'x' * (10 * 1024 * 1024 + 1))
        async def run():
            async with self.client(self.owner['agent_token']) as client:
                result = await client.call_tool('read_asset', {'asset_id': asset['id']})
                self.assertTrue(result.is_error)
                self.assertIn('MCP read limit', result.content[0].text)
        asyncio.run(run())

    def test_mcp_asset_read_has_a_bounded_response(self):
        service = self.live.app.state.service
        service.assets.max_file_bytes = 10 * 1024 * 1024 + 1
        service.assets.max_project_bytes = 10 * 1024 * 1024 + 1
        service.assets.max_total_bytes = 10 * 1024 * 1024 + 1
        asset = service.assets.upload(self.owner['web_token'], 'large.bin', 'application/octet-stream',
                                      b'x' * (10 * 1024 * 1024 + 1))
        async def run():
            async with self.client(self.owner['agent_token']) as client:
                result = await client.call_tool('read_asset', {'asset_id': asset['id']})
                self.assertTrue(result.is_error)
                self.assertIn('MCP read limit', result.content[0].text)
        asyncio.run(run())

    def test_cross_room_sdk_isolation(self):
        status, other, _ = self.live.request('POST', '/api/rooms', data={'name': 'Other room', 'owner_name': 'Other owner'})
        self.assertEqual(status, 200)
        status, task, _ = self.live.request('POST', '/api/tasks', self.owner['web_token'],
            {'intent_key': 'private-task', 'title': 'Private task', 'scope': 'private'})
        self.assertEqual(status, 200)
        status, request, _ = self.live.request('POST', '/api/requests', self.owner['agent_token'],
            {'request_key': 'private-request', 'receiver_member_id': self.member['member_id'],
             'context_version': 1, 'body': 'Private request'})
        self.assertEqual(status, 200)

        async def run():
            async with self.client(self.owner['agent_token']) as owner, self.client(other['agent_token']) as outsider:
                await self.call(owner, 'claim_task', {'task_id': task['id']})
                first, second = await asyncio.gather(self.call(owner, 'read_team', {}), self.call(outsider, 'read_team', {}))
                self.assertEqual(first['room']['id'], self.owner['room_id'])
                self.assertEqual(second['room']['id'], other['room_id'])
                self.assertEqual(second['me']['member_id'], other['member_id'])
                self.assertEqual([member['member_id'] for member in second['members']], [other['member_id']])
                for name in ('tasks', 'sessions', 'progress', 'overlaps', 'requests', 'contracts', 'events'):
                    self.assertEqual(second[name], [], name)
                for name, args in (
                    ('claim_task', {'task_id': task['id']}),
                    ('propose_contract', {'contract_key': 'cross-room', 'expected_version': 0,
                                          'title': 'Private source', 'body': 'v1', 'source_request_id': request['id']}),
                ):
                    result = await outsider.call_tool(name, args)
                    self.assertTrue(result.is_error)
                    error = json.loads(result.content[0].text)
                    self.assertEqual(error['error'], 'NotFound')
                    self.assertNotIn('owner_member_id', error)
                    self.assertNotIn(self.owner['member_id'], result.content[0].text)
                    self.assertIsNone(result.structured_content)
                self.assertEqual((await self.call(outsider, 'read_team', {}))['contracts'], [])

        asyncio.run(run())

    def test_raw_schema_auth_rotation_and_isolation(self):
        async def run():
            async with self.client(self.owner['agent_token']) as owner, self.client(self.member['agent_token']) as member:
                for name, args in [('whoami', {'author': 'forged'}), ('claim_task', {'task_id': True}),
                                   ('claim_task', {'task_id': '1'}), ('send_request', {'request_key': 'r', 'body': 'b', 'context_version': True})]:
                    with self.subTest(name=name, args=args):
                        result = await owner.call_tool(name, args)
                        self.assertTrue(result.is_error, result)
                        self.assertIn('ValidationError', result.content[0].text)
                operations = self.live.app.state.service.operations
                kind, method, schema = operations['claim_task']
                with patch.dict(operations, {'claim_task': (kind, lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('secret-token')), schema)}):
                    failure = await owner.call_tool('claim_task', {'task_id': 1})
                    self.assertTrue(failure.is_error)
                    self.assertNotIn('secret-token', failure.content[0].text)
                    self.assertIn('InternalError', failure.content[0].text)
                for _ in range(3):
                    results = await asyncio.gather(*[self.call(owner if i % 2 == 0 else member, 'whoami', {}) for i in range(8)])
                    self.assertEqual([r['me']['member_id'] for r in results], [self.owner['member_id'] if i % 2 == 0 else self.member['member_id'] for i in range(8)])
                self.assertEqual((await self.call(member, 'whoami', {}))['me']['member_id'], self.member['member_id'])
        asyncio.run(run())
        self.live.request('POST', '/api/agent-token', self.owner['web_token'], {})
        status, body, headers = self.live.request('POST', '/mcp', self.member['agent_token'],
            raw=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"whoami","arguments":{"extra":"\\ud800"}}}',
            headers={'Content-Type': 'application/json'})
        self.assertEqual(status, 400, body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.live.request('POST', '/mcp', self.member['agent_token'],
            raw=b'x' * 65537, headers={'Content-Type': 'application/json'})[0], 413)
        for token in (None, self.owner['web_token'], self.owner['agent_token']):
            status, result, headers = self.live.request('POST', '/mcp', token, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
            self.assertEqual(status, 401, result)
            self.assertNotIn('resource_metadata', headers.get('WWW-Authenticate', ''))
