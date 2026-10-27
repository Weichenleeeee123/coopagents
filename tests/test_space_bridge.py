import asyncio
import json
from pathlib import Path
import sys
import subprocess
import hashlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import threading
import sqlite3
from io import BytesIO
import unittest
from unittest.mock import patch
from uuid import uuid4

from mcp import Client
from mcp.client.stdio import StdioServerParameters
import httpx2
from mcp.client.streamable_http import streamable_http_client

from coopagents.spaces import private_write
from coopagents.space_bridge import EventCache, Bridge, agent_tool, human_operation, install_wake
from coopagents.space_wake import WakeSetupError
from mcp.types import Implementation
from transport_support import LiveService


class SpaceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()
        self.path = Path('.local/test-evidence') / uuid4().hex / 'profile.json'
        private_write(self.path, dict(schema_version=1, origin=self.live.url, **self.owner))

    def test_cache_bounded_durable_and_reset(self):
        cache = EventCache(self.path, self.owner['room_id'], self.owner['member_id'], capacity=3)
        for n in range(1, 6):
            cache.receive({'type': 'events', 'cursor': n, 'events': [dict(id=n, room_id=self.owner['room_id'], topic='tasks', entity_id='1', action='insert', created_at='now')]})
        reopened = EventCache(self.path, self.owner['room_id'], self.owner['member_id'], capacity=3)
        self.assertEqual(reopened.cursor, 5)
        self.assertEqual(reopened.read(0, 100)['reset'], 'local_cache_expired')
        self.assertEqual([e['id'] for e in reopened.read(2, 100)['events']], [3, 4, 5])
        reopened.receive({'type':'reset','cursor':8,'reason':'expired_cursor'})
        self.assertEqual(reopened.read(5, 100)['reset'], 'expired_cursor')
        self.assertEqual(reopened.read(8, 100)['events'], [])
        self.assertNotIn(self.owner['agent_token'], reopened.path.read_bytes().decode('latin1'))

    def test_shared_cache_accepts_duplicate_and_overlapping_event_pages(self):
        first = EventCache(self.path, self.owner['room_id'], self.owner['member_id'])
        second = EventCache(self.path, self.owner['room_id'], self.owner['member_id'])
        def page(*ids):
            return dict(type='events', cursor=ids[-1], events=[dict(id=n, room_id=self.owner['room_id'], topic='tasks', entity_id='1', action='insert', created_at='now') for n in ids])
        first.receive(page(1, 2, 3))
        second.receive(page(1, 2))
        self.assertEqual(first.cursor, 3)
        second.receive(page(2, 3, 4))
        first.receive(page(3, 4, 5))
        self.assertEqual(second.cursor, 5)
        self.assertEqual([e['id'] for e in first.read(0, 100)['events']], [1, 2, 3, 4, 5])
        invalid = page(1)
        invalid['events'][0]['room_id'] = 'other-room'
        with self.assertRaises(ValueError):
            second.receive(invalid)
        self.assertEqual(second.cursor, 5)

    def test_concurrent_cache_initialization_has_one_identity_row(self):
        gate = threading.Barrier(6)
        def initialize(_):
            gate.wait(timeout=5)
            return EventCache(self.path,self.owner['room_id'],self.owner['member_id'])
        with ThreadPoolExecutor(max_workers=6) as workers:
            caches=list(workers.map(initialize,range(6)))
        with caches[0].connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM state').fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('INSERT INTO state VALUES(?,?,0,0,NULL)',('other-room','other-member'))
        with self.assertRaises(ValueError):
            EventCache(self.path,'other-room','other-member')

    def test_stale_stream_reset_preserves_progress_then_fresh_rollback_applies(self):
        first=EventCache(self.path,self.owner['room_id'],self.owner['member_id'])
        second=EventCache(self.path,self.owner['room_id'],self.owner['member_id'])
        def page(*ids):
            return dict(type='events',cursor=ids[-1],events=[dict(id=n,room_id=self.owner['room_id'],topic='tasks',entity_id='1',action='insert',created_at='now') for n in ids])
        first.receive(page(100))
        second.receive(page(101,120))
        self.assertFalse(first.receive(dict(type='reset',reason='expired_cursor',cursor=100),expected_after_id=0))
        self.assertEqual(first.cursor,120)
        self.assertEqual([e['id'] for e in first.read(100,100)['events']],[101,120])
        self.assertTrue(first.receive(dict(type='reset',reason='future_cursor',cursor=90),expected_after_id=120))
        self.assertEqual(second.cursor,90)
        self.assertEqual(second.read(90,100)['events'],[])

    def test_real_stdio_forwards_exact_schemas_identity_and_changes(self):
        repo = self.path.parent / 'repo'
        repo.mkdir()
        async def run():
            # Like Claude Code: the bridge starts in the session's folder and the client names itself.
            params = StdioServerParameters(command=sys.executable, cwd=str(repo.absolute()),
                                           args=['-m', 'coopagents.space_bridge', '--profile', str(self.path.absolute())])
            async with Client(params, cache=None, client_info=Implementation(name='claude-code', version='0')) as bridge:
                async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+self.owner['agent_token']}) as http:
                    async with Client(streamable_http_client(self.live.url+'/mcp', http_client=http), cache=None) as remote:
                        expected = {t.name:t.model_dump() for t in (await remote.list_tools()).tools}
                actual = {t.name:t.model_dump() for t in (await bridge.list_tools()).tools}
                self.assertEqual({n:v for n,v in actual.items() if n not in ('read_changes', 'install_wake')}, expected)
                self.assertIn('returns installed', actual['install_wake']['description'])
                self.assertNotIn('required', actual['install_wake']['input_schema'])
                bad = await bridge.call_tool('install_wake', {'tool': 'cursor'})
                self.assertTrue(bad.is_error)
                missing = await bridge.call_tool('install_wake', {'project_dir': str(repo.absolute() / 'nope')})
                self.assertTrue(missing.is_error)
                # The agent sees why and what to do instead of a generic failure.
                self.assertIn('does not exist', missing.content[0].text)
                self.assertIn('without project_dir', missing.content[0].text)
                self.assertIn(str(repo.absolute()), missing.content[0].text)
                self.assertFalse((repo / '.claude').exists())
                woke = await bridge.call_tool('install_wake', {})
                self.assertFalse(woke.is_error, woke.content)
                self.assertEqual(woke.structured_content['installed'], 'claude')
                settings = json.loads((repo / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
                self.assertEqual(sorted(settings['hooks']), ['SessionStart', 'Stop'])
                self.assertIn('coopagents.space_wake watch --tool claude', json.dumps(settings))
                self.assertNotIn(self.owner['agent_token'], woke.model_dump_json())
                identity = await bridge.call_tool('whoami', {})
                self.assertFalse(identity.is_error)
                self.assertEqual(identity.structured_content['me']['room_id'], self.owner['room_id'])
                result = await bridge.call_tool('checkpoint', {'session_key':'bridge','tool':'codex-cli','event':'startup'})
                self.assertFalse(result.is_error)
                self.assertNotIn(self.owner['agent_token'], result.model_dump_json())
                for _ in range(30):
                    changes = await bridge.call_tool('read_changes', {'after_id':0})
                    if changes.structured_content['events']:
                        break
                    await asyncio.sleep(.1)
                self.assertTrue(changes.structured_content['events'])
                self.assertFalse(changes.structured_content['model_read_acknowledged'])
        asyncio.run(run())

    def test_install_wake_detects_the_agent_and_its_folder(self):
        repo = (self.path.parent / 'session').absolute()
        repo.mkdir()
        profile = self.path.absolute()
        self.assertEqual(agent_tool('claude-code'), 'claude')
        self.assertEqual(agent_tool('codex-mcp-client'), 'codex')
        self.assertIsNone(agent_tool('mcp'))
        with self.assertRaisesRegex(WakeSetupError, "pass tool 'claude' or 'codex'"):
            install_wake(profile, {}, 'some-other-client')
        with self.assertRaisesRegex(WakeSetupError, 'accepts only tool and project_dir'):
            install_wake(profile, {'profile': 'x'}, 'claude-code')
        with patch.dict('os.environ', {'CLAUDE_PROJECT_DIR': str(repo)}):
            result = install_wake(profile, None, 'claude-code')
        self.assertEqual(result['installed'], 'claude')
        self.assertTrue((repo / '.claude' / 'settings.local.json').exists())
        self.assertIn(str(repo), result['next'])
        with patch('os.getcwd', return_value=str(repo)):
            result = install_wake(profile, {}, 'codex-mcp-client')
        self.assertEqual(result['installed'], 'codex')
        self.assertTrue((repo / '.codex' / 'hooks.json').exists())
        self.assertIn('/hooks', result['next'])
        with patch('os.getcwd', return_value=str(Path.home())), self.assertRaisesRegex(WakeSetupError, 'home folder'):
            install_wake(profile, {}, 'codex-mcp-client')

    def test_identity_mismatch_and_agent_human_denial(self):
        profile = json.loads(self.path.read_text())
        profile['room_id'] = 'wrong'
        private_write(self.path, profile, update=True)
        with self.assertRaises(ValueError):
            asyncio.run(Bridge(self.path).verified_profile())
        profile['room_id'] = self.owner['room_id']
        profile.pop('web_token')
        private_write(self.path, profile, update=True)
        payload = self.path.parent/'payload.json'
        private_write(payload, dict(schema_version=1, intent_key='t', title='Task', scope='src'))
        with self.assertRaises(ValueError):
            human_operation(self.path, 'create_task', payload)

    def test_human_helper_reuses_permissions_and_operation_endpoint(self):
        payload = self.path.parent/'task.json'
        private_write(payload, dict(schema_version=1, intent_key='human', title='Task', scope='src'))
        result = human_operation(self.path, 'create_task', payload)
        self.assertEqual(result['title'], 'Task')
        with self.assertRaises(ValueError):
            human_operation(self.path, 'rotate_agent', payload)

    def test_background_reconnect_rereads_origin_and_durable_replay(self):
        async def wait_for(check):
            for _ in range(100):
                if check():
                    return
                await asyncio.sleep(.1)
            self.fail('Bridge did not recover within bounded deadline')
        async def run():
            bridge = Bridge(self.path)
            watcher = asyncio.create_task(bridge.watch())
            try:
                await wait_for(lambda: bridge.status == 'online' and bridge.cache.cursor > 0)
                before = bridge.cache.cursor
                second = await asyncio.to_thread(LiveService, self.live.database)
                self.addCleanup(second.close)
                profile = json.loads(self.path.read_text())
                profile['origin'] = second.url
                await asyncio.to_thread(private_write, self.path, profile, update=True)
                await asyncio.to_thread(self.live.close)
                status, task, _ = second.request('POST','/api/tasks',self.owner['web_token'],dict(intent_key='reconnect',title='Recover',scope='src'))
                self.assertEqual(status, 200)
                await wait_for(lambda: bridge.status == 'online' and bridge.cache.cursor > before)
                received = bridge.cache.read(before,100)
                self.assertTrue(any(e['topic']=='tasks' and e['entity_id']==str(task['id']) for e in received['events']))
                cursor = bridge.cache.cursor
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            reopened = Bridge(self.path)
            self.assertEqual(reopened.cache.cursor, cursor)
        asyncio.run(run())

    def test_revoked_identity_cannot_discover_call_or_read_cache(self):
        profile = json.loads(self.path.read_text())
        profile.update(self.member)
        profile.pop('web_token')
        private_write(self.path,profile,update=True)
        async def run():
            params = StdioServerParameters(command=sys.executable,args=['-m','coopagents.space_bridge','--profile',str(self.path.absolute())])
            async with Client(params,cache=None) as bridge:
                self.assertTrue((await bridge.list_tools()).tools)
                status, _, _ = self.live.request('POST','/api/operations/revoke_member',self.owner['web_token'],{'member_id':self.member['member_id']},headers={'Origin':self.live.url})
                self.assertEqual(status,200)
                self.assertEqual((await bridge.list_tools()).tools,[])
                self.assertTrue((await bridge.call_tool('whoami',{})).is_error)
                self.assertTrue((await bridge.call_tool('read_changes',{})).is_error)
        asyncio.run(run())

    def test_cli_failure_does_not_emit_secrets(self):
        profile=json.loads(self.path.read_text())
        profile['agent_token']='never-output-this-private-token'
        private_write(self.path,profile,update=True)
        payload=self.path.parent/'bad-payload.json'
        private_write(payload,dict(schema_version=1,unexpected='wrong'))
        result=subprocess.run([sys.executable,'-m','coopagents.space_bridge','--profile',str(self.path.absolute()),
                               '--human-operation','create_task','--payload-file',str(payload.absolute())],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,1)
        self.assertEqual(result.stdout,'')
        for secret in (profile['agent_token'],profile['web_token']):
            self.assertNotIn(secret,result.stdout+result.stderr)

    def test_cloudflare_official_digest_and_mismatch(self):
        source=Path(__file__).resolve().parents[1]/'src/skills/coopagents-space/scripts/verify_cloudflared.py'
        spec=importlib.util.spec_from_file_location('cloudflare_verifier',source)
        helper=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        binary=b'fake executable for unit digest verification'
        name='cloudflared-windows-amd64.exe'
        asset=dict(name=name,digest='sha256:'+hashlib.sha256(binary).hexdigest(),browser_download_url='https://github.com/cloudflare/cloudflared/releases/download/2026.1.0/'+name)
        destination=self.path.parent/name
        with patch('urllib.request.urlopen',side_effect=[BytesIO(json.dumps({'assets':[asset]}).encode()),BytesIO(binary)]):
            self.assertEqual(helper.install('2026.1.0',name,destination).read_bytes(),binary)
        bad=self.path.parent/'bad.exe'
        with patch('urllib.request.urlopen',side_effect=[BytesIO(json.dumps({'assets':[asset]}).encode()),BytesIO(b'corrupt')]):
            with self.assertRaises(ValueError):
                helper.install('2026.1.0',name,bad)
        self.assertFalse(bad.exists())


if __name__ == '__main__':
    unittest.main()
