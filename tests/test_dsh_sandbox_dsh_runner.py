import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / 'experiments' / 'agent-integration'
sys.path.insert(0, str(SANDBOX))

import dsh_sandbox.dsh_runner as dsh_runner


class DshNativeRunnerTests(unittest.IsolatedAsyncioTestCase):
    def make_root(self):
        root = ROOT / '.local' / 'dsh-native-runner-tests' / uuid4().hex
        root.mkdir(parents=True, exist_ok=False)
        return root

    def test_patch_is_json_yaml_and_has_native_provider_and_arm_specific_mcp(self):
        patch_file = self.make_root() / 'patch.yml'
        dsh_runner.write_patch(
            patch_file, proxy_base_url='http://127.0.0.1:9123/team/v1',
            mcp_url='http://127.0.0.1:8123/mcp', api_key_env='PRIVATE_LLM_KEY',
            arm='coopagents')

        rows = json.loads(patch_file.read_text(encoding='utf-8'))
        by_id = {row['id']: row for row in rows if 'id' in row}
        provider = by_id['llm-pi-ai']['config']['providers']['mota']
        self.assertEqual(provider['api'], 'openai-completions')
        self.assertEqual(provider['apiKeyEnv'], 'PRIVATE_LLM_KEY')
        self.assertEqual(provider['baseURL'], 'http://127.0.0.1:9123/team/v1')
        self.assertEqual(provider['compat']['thinkingFormat'], 'deepseek')
        self.assertEqual(by_id['agent-default-model']['config'], {
            'provider': 'mota', 'model': 'deepseekv41flash-auto-b'})
        mcp = next(row for row in rows if 'insert' in row)['insert'][0]
        self.assertEqual(mcp['name'], '@deepseek-ai/dsh-mcp-client')
        self.assertEqual(mcp['config']['url'], 'http://127.0.0.1:8123/mcp')
        self.assertNotIn('headers', mcp['config'])
        self.assertNotIn('runtime-secret-sentinel', patch_file.read_text(encoding='utf-8'))

        control_file = self.make_root() / 'control.yml'
        dsh_runner.write_patch(
            control_file, proxy_base_url='http://127.0.0.1:9123/team/v1',
            mcp_url='http://127.0.0.1:8123/mcp', api_key_env='PRIVATE_LLM_KEY',
            arm='control')
        control_rows = json.loads(control_file.read_text(encoding='utf-8'))
        self.assertFalse(any(row.get('insert') for row in control_rows))

    def test_rejects_non_loopback_proxy_and_non_loopback_mcp_url(self):
        args = {'api_key_env': 'PRIVATE_LLM_KEY', 'arm': 'control'}
        with self.assertRaises(ValueError):
            dsh_runner.build_patch(proxy_base_url='http://relay.example/v1',
                                   mcp_url='http://127.0.0.1:8/mcp', **args)
        self.assertTrue(dsh_runner.build_patch(
            proxy_base_url='https://private-proxy.example/team/v1',
            mcp_url='http://127.0.0.1:8/mcp', **args))
        with self.assertRaises(ValueError):
            dsh_runner.build_patch(proxy_base_url='http://127.0.0.1:9/v1',
                                   mcp_url='http://gateway.example/mcp', arm='coopagents',
                                   api_key_env='PRIVATE_LLM_KEY')

    async def test_fake_process_retains_trace_and_returns_only_redacted_metadata(self):
        root = self.make_root()
        fake = root / 'fake_dsh.py'
        fake.write_text(
            "import json,sys,os\n"
            "if '--version' in sys.argv: print('0.2.1-rc.2'); raise SystemExit(0)\n"
            "print(json.dumps({'type':'env_check','ambient_secret':bool(os.environ.get('AWS_SECRET_ACCESS_KEY')),"
            "'runtime_key':os.environ.get('PRIVATE_LLM_KEY') == 'runtime-secret-sentinel'}))\n"
            "print(json.dumps({'type':'session','sessionId':'native-123'}))\n"
            "print(json.dumps({'type':'tool_call','tool':'mcp__coopagents__whoami'}))\n"
            "print(json.dumps({'type':'status','phase':'turn_end','reason':'completed'}))\n"
            "print(json.dumps({'type':'final','text':'done'}))\n",
            encoding='utf-8')
        command = (sys.executable, str(fake))
        runner = dsh_runner.DshNativeRunner(
            output_root=root / 'runs', proxy_base_url='http://127.0.0.1:9123/v1',
            mcp_url='http://127.0.0.1:8123/mcp', api_key_env='PRIVATE_LLM_KEY',
            command=command, native_process=False)

        with patch.dict(os.environ, {'PRIVATE_LLM_KEY': 'runtime-secret-sentinel',
                                     'AWS_SECRET_ACCESS_KEY': 'ambient-secret-sentinel'}):
            result = await runner.run_turn(
                arm='coopagents', role='backend', prompt='private prompt sentinel',
                session_id=None, fresh_session=False, workspace=root,
                timeout_seconds=5, budget_remaining_usd=1)

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['source'], 'harness_only')
        self.assertEqual(result['session_id'], 'native-123')
        self.assertEqual(result['tool_names'], ['mcp__coopagents__whoami'])
        self.assertEqual(result['cost_usd'], None)
        trace = Path(result['trace_ref'])
        self.assertTrue(trace.is_file())
        self.assertNotIn('runtime-secret-sentinel', trace.read_text(encoding='utf-8'))
        self.assertNotIn('ambient-secret-sentinel', trace.read_text(encoding='utf-8'))
        env_check = json.loads(trace.read_text(encoding='utf-8').splitlines()[0])
        self.assertFalse(env_check['ambient_secret'])
        self.assertTrue(env_check['runtime_key'])
        self.assertNotIn('private prompt sentinel', json.dumps({k: v for k, v in result.items()
                                                                 if k != 'trace_ref'}))
        self.assertEqual(result['trace_sha256'], __import__('hashlib').sha256(trace.read_bytes()).hexdigest())
        self.assertEqual(set(result), {'status', 'source', 'exit_code', 'session_id',
                                       'model_alias', 'trace_ref', 'trace_sha256',
                                       'tool_names', 'tool_count', 'cost_usd'})

    async def test_nonzero_process_and_prose_do_not_become_native_success(self):
        root = self.make_root()
        fake = root / 'fake_dsh.py'
        fake.write_text("import sys\nif '--version' in sys.argv: print('0.2.1-rc.2'); raise SystemExit(0)\n"
                        "print('completed successfully')\nraise SystemExit(7)\n", encoding='utf-8')
        runner = dsh_runner.DshNativeRunner(
            output_root=root / 'runs', proxy_base_url='http://127.0.0.1:9123/v1',
            mcp_url='http://127.0.0.1:8123/mcp', api_key_env='PRIVATE_LLM_KEY',
            command=(sys.executable, str(fake)), native_process=True)

        with patch.dict(os.environ, {'PRIVATE_LLM_KEY': 'runtime-secret-sentinel'}):
            result = await runner.run_turn(
                arm='control', role='frontend', prompt='work', session_id=None,
                fresh_session=False, workspace=root, timeout_seconds=5,
                budget_remaining_usd=1)

        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['source'], 'harness_only')
        self.assertEqual(result['exit_code'], 7)

    async def test_resume_uses_returned_native_session_and_keeps_role_home_isolated(self):
        root = self.make_root()
        capture = root / 'invocations.jsonl'
        fake = root / 'fake_dsh.py'
        fake.write_text(
            "import json,os,sys\n"
            "if '--version' in sys.argv: print('0.2.1-rc.2'); raise SystemExit(0)\n"
            "with open(r'%s','a',encoding='utf-8') as f: "
            "f.write(json.dumps({'args':sys.argv[1:],'home':os.environ['DSH_HOME']})+'\\n')\n"
            "sid=sys.argv[sys.argv.index('--session-id')+1] if '--session-id' in sys.argv else 'native-created'\n"
            "for e in [{'type':'session','sessionId':sid},"
            "{'type':'status','phase':'turn_end','reason':'completed'},"
            "{'type':'final','text':'done'}]: print(json.dumps(e))\n" % capture,
            encoding='utf-8')
        runner = dsh_runner.DshNativeRunner(
            output_root=root / 'runs', proxy_base_url='http://127.0.0.1:9123/v1',
            mcp_url='http://127.0.0.1:8123/mcp', api_key_env='PRIVATE_LLM_KEY',
            command=(sys.executable, str(fake)), native_process=False)
        with patch.dict(os.environ, {'PRIVATE_LLM_KEY': 'runtime-secret-sentinel'}):
            first = await runner.run_turn(
                arm='control', role='backend', prompt='first', session_id=None,
                fresh_session=False, workspace=root, timeout_seconds=5, budget_remaining_usd=1)
            second = await runner.run_turn(
                arm='control', role='backend', prompt='continue', session_id=first['session_id'],
                fresh_session=False, workspace=root, timeout_seconds=5, budget_remaining_usd=1)
            third = await runner.run_turn(
                arm='control', role='integration', prompt='new role', session_id=None,
                fresh_session=False, workspace=root, timeout_seconds=5, budget_remaining_usd=1)
            fourth = await runner.run_turn(
                arm='control', role='backend', prompt='fresh', session_id=first['session_id'],
                fresh_session=True, workspace=root, timeout_seconds=5, budget_remaining_usd=1)
        calls = [json.loads(line) for line in capture.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(first['session_id'], 'native-created')
        self.assertEqual(second['session_id'], first['session_id'])
        self.assertNotIn('--session-id', calls[0]['args'])
        self.assertEqual(calls[1]['args'][calls[1]['args'].index('--session-id') + 1],
                         first['session_id'])
        self.assertEqual(calls[0]['home'], calls[1]['home'])
        self.assertNotEqual(calls[1]['home'], calls[2]['home'])
        self.assertNotIn('--session-id', calls[3]['args'])
        self.assertEqual(third['source'], 'harness_only')
        self.assertEqual(fourth['source'], 'harness_only')

    def test_cli_requires_both_native_opt_ins_before_starting_a_process(self):
        root = self.make_root()
        called = root / 'called.txt'
        fake = root / 'fake_dsh.py'
        fake.write_text("import sys,json\nif '--version' in sys.argv: print('0.2.1-rc.2'); raise SystemExit(0)\n"
                        "from pathlib import Path\nPath(r'%s').write_text('started')\n"
                        "for e in [{'type':'session','sessionId':'cli-session'},"
                        "{'type':'status','phase':'turn_end','reason':'completed'},"
                        "{'type':'final','text':'done'}]: print(json.dumps(e))\n" % called,
                        encoding='utf-8')
        env = os.environ.copy()
        env.update({'DSH_NATIVE_OUTPUT_ROOT': str(root / 'runs'),
                    'DSH_NATIVE_COMMAND': json.dumps([sys.executable, str(fake)]),
                    'DSH_NATIVE_PROXY_BASE_URL': 'http://127.0.0.1:9123/v1',
                    'DSH_NATIVE_MCP_URL': 'http://127.0.0.1:8123/mcp',
                    'DSH_NATIVE_API_KEY_ENV': 'PRIVATE_LLM_KEY',
                    'PRIVATE_LLM_KEY': 'runtime-secret-sentinel'})
        for flags in ([], ['--execute-native']):
            result = subprocess.run([sys.executable, str(SANDBOX / 'dsh_sandbox' / 'dsh_runner.py'),
                                     'run', '--prompt', 'test', *flags],
                                    capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(called.exists())
        result = subprocess.run([sys.executable, str(SANDBOX / 'dsh_sandbox' / 'dsh_runner.py'),
                                 'run', '--prompt', 'test', '--execute-native', '--key-rotated'],
                                capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(called.exists())
        self.assertNotIn('PRIVATE_LLM_KEY', result.stdout + result.stderr)

    def test_run_config_reads_private_prompt_and_rejects_paths_outside_role_root(self):
        root = self.make_root() / 'runs'
        role_root = root / 'run-001' / 'control' / 'backend'
        workspace = role_root / 'project'
        workspace.mkdir(parents=True)
        prompt_file = role_root / 'prompt.txt'
        prompt_file.write_text('private prompt from file', encoding='utf-8')
        capture = role_root / 'fake-capture.json'
        fake = role_root / 'fake_dsh.py'
        fake.write_text(
            "import sys,json\n"
            "if '--version' in sys.argv: print('0.2.1-rc.2'); raise SystemExit(0)\n"
            "from pathlib import Path\n"
            "Path(r'%s').write_text(json.dumps({'args':sys.argv[1:],'stdin':sys.stdin.read()}))\n"
            "for e in [{'type':'session','sessionId':'session-from-config'},"
            "{'type':'status','phase':'turn_end','reason':'completed'},"
            "{'type':'final','text':'done'}]: print(json.dumps(e))\n" % capture,
            encoding='utf-8')
        config = role_root / 'config.json'
        document = {
            'schema_version': 1, 'run_id': 'run-001', 'arm': 'control', 'role': 'backend',
            'prompt_path': str(prompt_file), 'workspace': str(workspace),
            'fresh_session': True, 'session_id': None, 'timeout_seconds': 5,
            'budget_remaining_usd': 1, 'execute_native': True, 'key_rotated': True,
        }
        config.write_text(json.dumps(document), encoding='utf-8')
        env = os.environ.copy()
        env.update({'DSH_NATIVE_RUNS_ROOT': str(root),
                    'DSH_NATIVE_COMMAND': json.dumps([sys.executable, str(fake)]),
                    'DSH_NATIVE_PROXY_BASE_URL': 'https://private-proxy.example/team/v1',
                    'DSH_NATIVE_MCP_URL': 'http://127.0.0.1:8123/mcp',
                    'DSH_NATIVE_API_KEY_ENV': 'PRIVATE_LLM_KEY',
                    'PRIVATE_LLM_KEY': 'runtime-secret-sentinel'})
        result = subprocess.run([sys.executable, str(SANDBOX / 'dsh_sandbox' / 'dsh_runner.py'),
                                 'run-config', '--config', str(config)],
                                capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('private prompt from file', result.stdout + result.stderr)
        self.assertNotIn('runtime-secret-sentinel', result.stdout + result.stderr)
        captured = json.loads(capture.read_text(encoding='utf-8'))
        self.assertEqual(captured['stdin'], 'private prompt from file')
        self.assertNotIn('private prompt from file', captured['args'])

        document['prompt_path'] = str(root / 'outside-prompt.txt')
        config.write_text(json.dumps(document), encoding='utf-8')
        rejected = subprocess.run([sys.executable, str(SANDBOX / 'dsh_sandbox' / 'dsh_runner.py'),
                                   'run-config', '--config', str(config)],
                                  capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn('configuration_error', rejected.stdout)

    async def test_direct_native_call_requires_both_opt_ins(self):
        root = self.make_root()
        runner = dsh_runner.DshNativeRunner(
            output_root=root / 'runs', proxy_base_url='https://private-proxy.example/v1',
            mcp_url='http://127.0.0.1:8123/mcp', api_key_env='PRIVATE_LLM_KEY')
        with patch.dict(os.environ, {'PRIVATE_LLM_KEY': 'runtime-secret-sentinel'}), \
                patch('dsh_sandbox.dsh_runner.subprocess.run') as process:
            result = await runner.run_turn(
                arm='control', role='frontend', prompt='work', session_id=None,
                fresh_session=False, workspace=root, timeout_seconds=5,
                budget_remaining_usd=1)
        self.assertEqual(result['status'], 'failed')
        process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
