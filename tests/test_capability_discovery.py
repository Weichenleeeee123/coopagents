import json
import unittest
from pathlib import Path
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import ValidationError


class CapabilityDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path('.local/test-evidence/capability-discovery') / uuid4().hex
        self.folder.mkdir(parents=True)
        self.service = CoordinationService(self.folder / 'capabilities.sqlite3')
        self.owner = self.service.identity.create_room('Capabilities', 'Owner')
        self.member = self.service.identity.add_member(self.owner['web_token'], 'Member')

    def test_discovery_separates_members_agents_and_capability_evidence(self):
        self.service.activity.register_session(
            self.member['agent_token'], 'cursor-session', 'cursor', 'github.com/acme/demo', 'feature/ui',
            harness='cursor', harness_version='0.45.0', platform='windows',
            capabilities={'mcp': 'supported', 'native_hook': 'unknown'})
        result = self.service.read_capabilities(self.owner['web_token'])
        self.assertEqual({row['harness'] for row in result['harnesses']},
                         {'claude-code', 'codex', 'cursor', 'opencode', 'pi', 'kimi-code', 'zcode'})
        member = next(row for row in result['members'] if row['member_id'] == self.member['member_id'])
        self.assertEqual(len(member['agents']), 1)
        agent = member['agents'][0]
        self.assertEqual((agent['harness'], agent['version'], agent['platform']), ('cursor', '0.45.0', 'windows'))
        self.assertEqual(agent['status'], 'registered')
        self.assertEqual(agent['capabilities']['mcp'], 'unknown')
        self.assertEqual(agent['reported_capabilities']['mcp'], 'supported')
        encoded = json.dumps(result)
        self.assertNotIn('transcript', encoded)
        self.assertNotIn('online', encoded)

    def test_unknown_and_unsupported_matrix_cells_are_explicit(self):
        result = self.service.read_capabilities(self.owner['agent_token'])
        cursor = next(row for row in result['harnesses'] if row['harness'] == 'cursor')
        pi = next(row for row in result['harnesses'] if row['harness'] == 'pi')
        self.assertEqual(cursor['capabilities']['mcp'], 'unknown')
        self.assertEqual(cursor['configuration']['mcp'], 'supported')
        self.assertEqual(cursor['capabilities']['native_hook'], 'unknown')
        self.assertEqual(pi['capabilities']['native_hook'], 'unsupported')
        self.assertIn(cursor['evidence']['source'], ('adapter_contract', 'unverified'))

    def test_capability_payload_is_bounded_and_old_session_shape_is_preserved(self):
        row = self.service.activity.register_session(
            self.owner['agent_token'], 'legacy', 'codex-cli', 'repo', 'main', harness='codex',
            capabilities={'mcp': 'supported'})
        self.assertEqual(set(row), {'id', 'room_id', 'member_id', 'session_key', 'tool', 'repository', 'branch', 'task_id', 'updated_at'})
        with self.assertRaises(ValidationError):
            self.service.activity.register_session(
                self.owner['agent_token'], 'bad', 'codex-cli', 'repo', 'main', harness='codex',
                capabilities={'x' * 101: 'supported'})

    def test_verification_is_scoped_and_revocation_and_expiry_are_explicit(self):
        from coopagents.errors import AccessDenied
        self.service.activity.register_session(self.member['agent_token'], 'first', 'cursor', 'repo', 'main',
            harness_version='1.0', platform='windows', capabilities={'idle_wake': 'supported'})
        self.service.activity.register_session(self.member['agent_token'], 'second', 'cursor', 'repo', 'feature',
            harness_version='2.0', platform='linux')
        payload = dict(harness='cursor', version='1.0', platform='windows', capability='mcp',
                       status='supported', evidence='docs/acceptance/cursor-windows-1.0.md', constraints='Manual MCP only')
        with self.assertRaises(AccessDenied):
            self.service.capability_store.record(self.member['agent_token'], **payload)
        self.service.capability_store.record(self.owner['web_token'], **payload)
        view = self.service.read_capabilities(self.owner['agent_token'])
        member = next(m for m in view['members'] if m['member_id'] == self.member['member_id'])
        first = next(a for a in member['agents'] if a['version'] == '1.0')
        second = next(a for a in member['agents'] if a['version'] == '2.0')
        self.assertEqual(first['capabilities']['mcp'], 'supported')
        self.assertEqual(second['capabilities']['mcp'], 'unknown')
        self.assertEqual(first['capabilities']['idle_wake'], 'unknown')
        self.service.identity.revoke_agent(self.owner['web_token'], self.member['member_id'])
        view = self.service.read_capabilities(self.owner['web_token'])
        self.assertEqual(next(m for m in view['members'] if m['member_id'] == self.member['member_id'])['agents'][0]['status'], 'unavailable')
        with self.service.identity.db.connect(write=True) as db:
            db.execute("UPDATE capability_verifications SET verified_at='2000-01-01T00:00:00+00:00'")
        view = self.service.read_capabilities(self.owner['web_token'])
        entry = next(h for h in view['harnesses'] if h['harness'] == 'cursor' and h['evidence']['version'] == '1.0')
        self.assertEqual(entry['capabilities']['mcp'], 'stale')

    def test_each_harness_registers_under_its_real_tool_name_and_retains_history(self):
        tools = ('claude-code', 'codex-cli', 'codex-desktop', 'cursor', 'opencode', 'pi', 'kimi-code', 'zcode')
        for tool in tools:
            self.service.activity.register_session(self.member['agent_token'], tool, tool, 'repo', 'main')
        view = self.service.read_capabilities(self.owner['web_token'])
        member = next(m for m in view['members'] if m['member_id'] == self.member['member_id'])
        self.assertEqual({a['tool'] for a in member['agents']}, set(tools))
        self.assertEqual(len(self.service.activity.list_sessions(self.owner['web_token'])), len(tools))

    def test_http_and_mcp_discovery_and_strict_registration(self):
        import asyncio
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        from transport_support import LiveService
        live=LiveService();self.addCleanup(live.close)
        owner,member=live.bootstrap()
        status,row,_=live.request('POST','/api/sessions',member['agent_token'],dict(session_key='http',tool='cursor',repository='repo',branch='main',harness_version='1',platform='windows'))
        self.assertEqual(status,200,row)
        status,view,_=live.request('GET','/api/capabilities',owner['web_token'])
        self.assertEqual(status,200,view)
        self.assertEqual(next(m for m in view['members'] if m['member_id']==member['member_id'])['agents'][0]['harness'],'cursor')
        evidence=dict(harness='cursor',version='1',platform='windows',capability='mcp',status='supported',evidence='retained-test-evidence')
        status,record,_=live.request('POST','/api/operations/record_capability',owner['web_token'],evidence,headers={'Origin':live.url})
        self.assertEqual(status,200,record)
        async def run():
            async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+member['agent_token']}) as http:
                async with Client(streamable_http_client(live.url+'/mcp',http_client=http),cache=None) as client:
                    result=await client.call_tool('read_capabilities',{})
                    self.assertFalse(result.is_error,result.content)
                    self.assertEqual(len(result.structured_content['members']),2)
                    tools={t.name for t in (await client.list_tools()).tools}
                    self.assertNotIn('record_capability',tools)
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
