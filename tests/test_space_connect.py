import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents import space_connect
from coopagents.space_connect import ConnectError
from coopagents.spaces import private_write

FAKE = str(Path(__file__).with_name('fake_mcp_cli.py').resolve())


class Connect(unittest.TestCase):
    def setUp(self):
        self.directory = (Path('.local/connect-tests') / uuid4().hex).resolve()
        self.directory.mkdir(parents=True)
        self.profile = self.directory / 'state' / 'profile.json'
        private_write(self.profile, dict(schema_version=1, origin='http://127.0.0.1:8765',
                                         room_id='e12dd599-347b-4bd1-a389-ed32462cc11b', member_id='member',
                                         web_token='web-secret', agent_token='agent-secret'))
        self.state = self.directory / 'mcp.json'
        self.skills = self.directory / 'skills'

    def run_connect(self, tool, **kwargs):
        env = {'FAKE_TOOL': tool, 'FAKE_MCP_STATE': str(self.state)} | kwargs.pop('env', {})
        with patch.dict(os.environ, env):
            return space_connect.connect(tool, self.profile, cli=[sys.executable, FAKE], skills=self.skills, **kwargs)

    def test_claude_and_codex_register_verify_and_install_skill(self):
        for tool in ('claude', 'codex'):
            with self.subTest(tool=tool):
                self.state.unlink(missing_ok=True)
                result = self.run_connect(tool)
                self.assertEqual((result['config'], result['verified']), ('added', True))
                self.assertEqual(result['server'], 'coopagents_e12dd599')
                registered = json.loads(self.state.read_text())['coopagents_e12dd599']
                self.assertEqual(registered, [sys.executable, '-m', 'coopagents.space_bridge', '--profile', str(self.profile)])
                self.assertIn('new %s session' % ('Claude Code' if tool == 'claude' else 'Codex'), result['next'])
                skill = Path(result['skill_path'])
                self.assertTrue((skill / 'SKILL.md').read_text(encoding='utf-8').startswith('---'))
                self.assertTrue((skill / 'scripts' / 'verify_cloudflared.py').exists())
                self.assertNotIn('secret', json.dumps(result))

    def test_rerun_is_idempotent_and_skill_stays_present(self):
        first = self.run_connect('claude')
        second = self.run_connect('claude')
        self.assertEqual((first['skill'], second['config'], second['skill']), ('installed', 'already_configured', 'present'))

    def test_different_existing_server_is_never_overwritten(self):
        self.state.write_text(json.dumps({'coopagents_e12dd599': ['node', 'other.js']}))
        with self.assertRaises(ConnectError) as raised:
            self.run_connect('codex')
        self.assertIn('--name', str(raised.exception))
        self.assertEqual(json.loads(self.state.read_text())['coopagents_e12dd599'], ['node', 'other.js'])
        self.assertEqual(self.run_connect('codex', name='coopagents_second')['config'], 'added')

    def test_an_add_that_did_not_land_is_reported_not_claimed(self):
        with self.assertRaises(ConnectError) as raised:
            self.run_connect('claude', env={'FAKE_IGNORE_ADD': '1'})
        self.assertIn('not found in the native configuration', str(raised.exception))

    def test_broken_cli_points_to_cli_option(self):
        with self.assertRaises(ConnectError) as raised:
            self.run_connect('codex', env={'FAKE_BROKEN': '1'})
        self.assertIn('--cli', str(raised.exception))

    def test_falls_through_to_the_first_cli_that_can_read_its_configuration(self):
        broken, working = [sys.executable, FAKE, '--broken'], [sys.executable, FAKE]
        with patch.object(space_connect, 'cli_candidates', return_value=[broken, working]),                 patch.dict(os.environ, {'FAKE_TOOL': 'codex', 'FAKE_MCP_STATE': str(self.state)}):
            result = space_connect.connect('codex', self.profile, skills=self.skills)
        self.assertEqual((result['config'], result['cli']), ('added', FAKE))
        with patch.object(space_connect, 'cli_candidates', return_value=[broken]),                 patch.dict(os.environ, {'FAKE_TOOL': 'codex', 'FAKE_MCP_STATE': str(self.state)}):
            with self.assertRaises(ConnectError):
                space_connect.connect('codex', self.profile, skills=self.skills)

    def test_candidates_prefer_the_running_claude_and_skip_missing_paths(self):
        exe = self.directory / 'claude.exe'
        exe.write_text('')
        with patch.dict(os.environ, {'CLAUDE_CODE_EXECPATH': str(exe), 'COOPAGENTS_CLAUDE_CLI': str(self.directory / 'missing')}):
            self.assertEqual(space_connect.cli_candidates('claude')[0], [str(exe)])
        self.assertEqual(space_connect.cli_candidates('codex', cli='C:/x/codex.exe'), [['C:/x/codex.exe']])

    def test_different_skill_copy_is_backed_up_not_removed(self):
        old = self.skills / 'coopagents-space'
        old.mkdir(parents=True)
        (old / 'SKILL.md').write_text('old skill', encoding='utf-8')
        result = self.run_connect('codex')
        self.assertEqual(result['skill'], 'updated')
        backup = Path(result['skill_backup'])
        self.assertEqual((backup / 'SKILL.md').read_text(encoding='utf-8'), 'old skill')
        # A backup inside the skills folder would load as a second skill.
        self.assertFalse(backup.is_relative_to(self.skills))
        self.assertEqual(sorted(path.name for path in self.skills.iterdir()), ['coopagents-space'])
        self.assertNotEqual((old / 'SKILL.md').read_text(encoding='utf-8'), 'old skill')

    def test_copy_differing_only_in_line_endings_is_the_same_skill(self):
        source = Path(space_connect.__file__).resolve().parent / 'skills' / 'coopagents-space'
        copy = self.skills / 'coopagents-space'
        for path in source.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                target = copy / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes().replace(b'\r\n', b'\n')
                target.write_bytes(data.replace(b'\n', b'\r\n') if path.suffix == '.md' else data)
        result = self.run_connect('claude')
        self.assertEqual(result['skill'], 'present')
        self.assertNotIn('skill_backup', result)

    def test_invalid_names_and_tools_are_refused(self):
        with self.assertRaises(ConnectError):
            self.run_connect('claude', name='bad name;rm')
        with self.assertRaises(ConnectError):
            space_connect.connect('cursor', self.profile)

    def test_cli_prints_json_and_fixed_errors(self):
        # The command runs in Codex's shell, as an agent would run it.
        env = os.environ | {'FAKE_TOOL': 'codex', 'FAKE_MCP_STATE': str(self.state), 'FAKE_BROKEN': '1',
                            'COOPAGENTS_CODEX_CLI': FAKE, 'CODEX_THREAD_ID': 'thread', 'CLAUDECODE': ''}
        # A .py path is not directly executable, so the CLI path is exercised through --cli on a wrapper.
        wrapper = self.directory / ('fake.cmd' if os.name == 'nt' else 'fake.sh')
        wrapper.write_text(('@"%s" "%s" %%*\n' if os.name == 'nt' else '#!/bin/sh\nexec "%s" "%s" "$@"\n') % (sys.executable, FAKE))
        wrapper.chmod(0o755)
        failed = subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'connect', '--tool', 'codex',
                                 '--profile', str(self.profile), '--cli', str(wrapper)], capture_output=True, text=True, env=env)
        self.assertEqual(failed.returncode, 1)
        self.assertIn('--cli', json.loads(failed.stderr)['message'])
        env.pop('FAKE_BROKEN')
        done = subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'connect', '--tool', 'codex',
                               '--profile', str(self.profile), '--cli', str(wrapper)], capture_output=True, text=True,
                              env=env | {'CODEX_HOME': str(self.directory / 'codex-home')})
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertTrue(result['verified'])
        self.assertTrue(Path(result['skill_path']).is_relative_to(self.directory / 'codex-home'))
        self.assertNotIn('secret', done.stdout + done.stderr)


if __name__ == '__main__':
    unittest.main()
