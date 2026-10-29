import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents import space_connect, space_wake
from coopagents.spaces import private_write
from coopagents.space_wake import WakeSetupError

FAKE = str(Path(__file__).with_name('fake_mcp_cli.py').resolve())


def hook_commands(document):
    for groups in document.get('hooks', {}).values():
        for group in groups:
            for hook in group.get('hooks', []):
                command = hook.get('command', '')
                marker = ' -EncodedCommand '
                if marker in command:
                    payload = command.split(marker, 1)[1].split()[0]
                    command = base64.b64decode(payload).decode('utf-16-le')
                yield command


class WakeInstall(unittest.TestCase):
    def setUp(self):
        self.directory = (Path('.local/wake-install-tests') / uuid4().hex).resolve()
        self.repo = self.directory / 'repo'
        self.repo.mkdir(parents=True)
        self.profile = self.make_profile('one')
        self.claude_home = self.directory / 'claude-home'
        self.codex_home = self.directory / 'codex-home'
        self.claude_home.mkdir()
        self.codex_home.mkdir()
        self.env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.claude_home), 'CODEX_HOME': str(self.codex_home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def make_profile(self, name):
        path = self.directory / name / 'profile.json'
        private_write(path, dict(schema_version=1, origin='http://127.0.0.1:8765', room_id='room-' + name,
                                 member_id='member', web_token='web-secret', agent_token='agent-secret'))
        return path

    def bridge(self, profile):
        return {'type': 'stdio', 'command': sys.executable, 'args': ['-m', 'coopagents.space_bridge', '--profile', str(profile)]}

    def write_claude(self, servers, project_servers=None):
        document = {'mcpServers': servers}
        if project_servers is not None:
            document['projects'] = {str(self.repo).replace(os.sep, '/'): {'mcpServers': project_servers}}
        (self.claude_home / '.claude.json').write_text(json.dumps(document), encoding='utf-8')

    def test_claude_and_codex_connections_are_found_without_running_anything(self):
        self.write_claude({'coopagents_one': self.bridge(self.profile), 'other': {'command': 'node', 'args': ['x.js']}})
        found = space_connect.registered_spaces('claude', self.repo)
        self.assertEqual([(e['server'], e['profile']) for e in found], [('coopagents_one', str(self.profile))])
        toml = '[mcp_servers.coopagents_one]\ncommand = %s\nargs = ["-m", "coopagents.space_bridge", "--profile", %s]\n' \
               '[mcp_servers.node_repl]\ncommand = "node"\n' % (json.dumps(sys.executable), json.dumps(str(self.profile)))
        (self.codex_home / 'config.toml').write_text(toml, encoding='utf-8')
        found = space_connect.registered_spaces('codex')
        self.assertEqual([e['profile'] for e in found], [str(self.profile)])

    def test_project_scoped_claude_connection_counts_for_that_repository(self):
        self.write_claude({}, {'coopagents_one': self.bridge(self.profile)})
        self.assertEqual(len(space_connect.registered_spaces('claude', self.repo)), 1)
        self.assertEqual(space_connect.registered_spaces('claude', self.directory), [])

    def test_install_without_profile_or_project_dir_uses_the_single_connection_and_current_folder(self):
        self.write_claude({'coopagents_one': self.bridge(self.profile)})
        previous = os.getcwd()
        os.chdir(self.repo)
        try:
            result = space_wake.install(None, 'claude')
        finally:
            os.chdir(previous)
        self.assertEqual(result['profile'], str(self.profile))
        settings = json.loads((self.repo / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(settings['hooks']), ['SessionStart', 'Stop'])
        self.assertTrue(any(str(self.profile).replace(os.sep, '/') in command for command in hook_commands(settings)))

    def test_none_or_several_connections_are_explained_not_guessed(self):
        self.write_claude({})
        with self.assertRaises(WakeSetupError) as raised:
            space_wake.find_profile('claude', self.repo)
        self.assertIn('run space_runtime connect first', str(raised.exception))
        self.write_claude({'coopagents_one': self.bridge(self.profile), 'coopagents_two': self.bridge(self.make_profile('two'))})
        with self.assertRaises(WakeSetupError) as raised:
            space_wake.find_profile('claude', self.repo)
        self.assertIn('coopagents_one, coopagents_two', str(raised.exception))
        self.assertIn('--profile', str(raised.exception))

    def test_cli_reports_the_reason_and_writes_nothing(self):
        self.write_claude({})
        result = subprocess.run([sys.executable, '-m', 'coopagents.space_wake', 'install', '--tool', 'claude'],
                                capture_output=True, text=True, cwd=self.repo, env=os.environ.copy())
        self.assertEqual(result.returncode, 1)
        self.assertIn('No Coopagents connection is registered for claude', result.stderr)
        self.assertFalse((self.repo / '.claude').exists())

    def test_cli_names_a_missing_project_folder(self):
        missing = self.directory / 'not-a-repo'
        result = subprocess.run([sys.executable, '-m', 'coopagents.space_wake', 'install', '--tool', 'claude',
                                 '--profile', str(self.profile), '--project-dir', str(missing)],
                                capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(result.returncode, 1)
        self.assertIn('%s does not exist' % missing, result.stderr)
        self.assertFalse(missing.exists())

    def wake_cli(self, *argv, shell):
        env = {**os.environ, 'CLAUDECODE': '', 'CODEX_THREAD_ID': '', 'CODEX_SESSION_ID': '', **shell}
        return subprocess.run([sys.executable, '-m', 'coopagents.space_wake', 'install', *argv],
                              capture_output=True, text=True, cwd=self.repo, env=env)

    def test_codex_cannot_install_claude_hooks_or_use_a_teammates_profile(self):
        self.write_claude({'coopagents_one': self.bridge(self.profile)})
        codex = {'CODEX_THREAD_ID': 'thread'}
        result = self.wake_cli('--tool', 'claude', '--profile', str(self.profile), shell=codex)
        self.assertEqual(result.returncode, 1)
        self.assertIn('runs inside Codex, but --tool claude', result.stderr)
        result = self.wake_cli('--profile', str(self.profile), shell=codex)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Codex has no Coopagents connection', result.stderr)
        mine = self.make_profile('codex-member')
        toml = '[mcp_servers.coopagents_two]\ncommand = %s\nargs = ["-m", "coopagents.space_bridge", "--profile", %s]\n' % (
            json.dumps(sys.executable), json.dumps(str(mine)))
        (self.codex_home / 'config.toml').write_text(toml, encoding='utf-8')
        result = self.wake_cli('--profile', str(self.profile), shell=codex)
        self.assertEqual(result.returncode, 1)
        self.assertIn('omit --profile', result.stderr)
        self.assertFalse((self.repo / '.claude').exists() or (self.repo / '.codex').exists())
        result = self.wake_cli(shell=codex)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads((self.repo / '.codex' / 'hooks.json').read_text(encoding='utf-8'))
        self.assertTrue(any(str(mine).replace(os.sep, '/') in command for command in hook_commands(settings)))

    def test_connect_can_install_wake_up_in_the_same_step(self):
        state = self.directory / 'mcp.json'
        with patch.dict(os.environ, {'FAKE_TOOL': 'claude', 'FAKE_MCP_STATE': str(state)}):
            plain = space_connect.connect('claude', self.profile, cli=[sys.executable, FAKE], skills=self.directory / 'skills')
            self.assertIn('install_wake', plain['next'])
            self.assertNotIn('wake', plain)
            woken = space_connect.connect('claude', self.profile, cli=[sys.executable, FAKE], skills=self.directory / 'skills',
                                          wake=True, project_dir=self.repo)
        self.assertEqual(woken['wake']['installed'], 'claude')
        self.assertIn('starts with that new session', woken['next'])
        self.assertTrue((self.repo / '.claude' / 'settings.local.json').exists())
        self.assertNotIn('secret', json.dumps(woken))


if __name__ == '__main__':
    unittest.main()
