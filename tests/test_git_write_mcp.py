import asyncio
from contextlib import asynccontextmanager
import unittest

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from transport_support import LiveService


class GitWriteMCPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()

    @asynccontextmanager
    async def client(self, token):
        async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + token}) as http:
            async with Client(streamable_http_client(self.live.url + '/mcp', http_client=http), cache=None) as client:
                yield client

    def test_write_tool_hidden_until_flag_enabled_and_call_fails_closed(self):
        status, _, _ = self.live.request('POST', '/api/git/binding', self.owner['web_token'],
                                         {'repository': 'github.com/acme/demo'})
        self.assertEqual(status, 200)
        task = self.live.request('POST', '/api/tasks', self.owner['web_token'],
                                 {'intent_key': 't', 'title': 'Build Login', 'scope': 'src'})[1]
        status, _, _ = self.live.request('POST', f"/api/tasks/{task['id']}/claim",
                                         self.member['agent_token'], {'session_key': 's1'})
        self.assertEqual(status, 200)
        arguments = {'task_id': task['id'], 'branch': 'coopagents/task-%d-1-build-login' % task['id'],
                     'base_sha': 'a' * 40, 'request_key': 'k1', 'session_key': 's1', 'ownership_epoch': 1}

        async def flag_off():
            async with self.client(self.member['agent_token']) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertNotIn('create_task_branch', names)
                # A cached tool list must not bypass the gate: the call itself fails closed.
                result = await client.call_tool('create_task_branch', arguments)
                self.assertTrue(result.is_error)
        asyncio.run(flag_off())

        status, body, _ = self.live.request('POST', '/api/git/write-enabled',
                                            self.owner['web_token'], {'enabled': True})
        self.assertEqual(status, 200, body)

        async def flag_on():
            async with self.client(self.member['agent_token']) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertIn('create_task_branch', names)
                result = await client.call_tool('create_task_branch', arguments)
                self.assertFalse(result.is_error, result.content)
                self.assertEqual(result.structured_content['branch'], arguments['branch'])
        asyncio.run(flag_on())

    def test_flag_toggle_requires_manager_web_token(self):
        status, body, _ = self.live.request('POST', '/api/git/write-enabled',
                                            self.member['agent_token'], {'enabled': True})
        self.assertNotEqual(status, 200)
        status, _, _ = self.live.request('POST', '/api/git/write-enabled',
                                         self.member['web_token'], {'enabled': True})
        self.assertNotEqual(status, 200)


if __name__ == '__main__':
    unittest.main()
