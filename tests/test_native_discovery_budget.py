"""The native client must wait for bounded owner/P2P startup, preserving user config."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents import space_connect


class DiscoveryBudget(unittest.TestCase):
    def setUp(self):
        self.root = (Path('.local/discovery-budget-tests') / uuid4().hex).resolve()
        self.root.mkdir(parents=True)
        self.path = self.root / 'config.toml'
        self.command = ['python', '-m', 'coopagents.space_bridge', '--profile', '/synthetic/profile.json']
        self.prefix = '# Retain my provider and comments\nmodel = "synthetic"\n'
        self.table = ('[mcp_servers.coopagents_test]\ncommand = "python"\nargs = '
                      + json.dumps(self.command[1:]) + '\n')
        self.foreign = '\n[mcp_servers.personal]\ncommand = "unrelated"\nstartup_timeout_sec = 7\n'

    def configure(self):
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root)}):
            return space_connect.configure_discovery_budget('coopagents_test', self.command)

    def test_sets_owned_server_budget_preserves_unrelated_text_and_backup(self):
        original = self.prefix + self.table + self.foreign
        self.path.write_text(original, encoding='utf-8')
        result = self.configure()
        import tomllib
        config = tomllib.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(config['mcp_servers']['coopagents_test']['startup_timeout_sec'], 120)
        self.assertIs(config['mcp_servers']['coopagents_test']['required'], True)
        self.assertTrue(self.path.read_text(encoding='utf-8').startswith(self.prefix))
        self.assertIn(self.foreign, self.path.read_text(encoding='utf-8'))
        self.assertEqual(Path(result['backup']).read_text(encoding='utf-8'), original)
        before = self.path.read_bytes()
        self.configure()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_retains_larger_existing_budget(self):
        self.path.write_text(self.prefix + self.table + 'startup_timeout_sec = 180\nrequired = true\n' + self.foreign, encoding='utf-8')
        original = self.path.read_bytes()
        self.assertEqual(self.configure()['startup_timeout_sec'], 180)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_larger_timeout_alone_does_not_make_optional_tools_ready(self):
        self.path.write_text(self.table + 'startup_timeout_sec = 180\nrequired = false\n', encoding='utf-8')
        self.configure()
        import tomllib
        entry = tomllib.loads(self.path.read_text(encoding='utf-8'))['mcp_servers']['coopagents_test']
        self.assertIs(entry['required'], True)
        self.assertEqual(entry['startup_timeout_sec'], 180)

    def test_updates_small_budget_inside_quoted_native_table_only(self):
        self.path.write_text((self.prefix + self.table).replace('[mcp_servers.coopagents_test]', '[mcp_servers."coopagents_test"]')
                             + 'startup_timeout_sec = 10 # Too short for P2P\n' + self.foreign, encoding='utf-8')
        self.assertEqual(self.configure()['startup_timeout_sec'], 120)
        import tomllib
        config = tomllib.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(config['mcp_servers']['personal']['startup_timeout_sec'], 7)

    def test_foreign_entry_and_unsupported_layout_are_never_overwritten(self):
        for text in (self.table.replace('command = "python"', 'command = "foreign"'),
                     'mcp_servers = {coopagents_test = {command="python",args=' + json.dumps(self.command[1:]) + '}}\n'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding='utf-8')
                before = self.path.read_bytes()
                with self.assertRaises(space_connect.ConnectError):
                    self.configure()
                self.assertEqual(self.path.read_bytes(), before)

    def test_doctor_reports_legacy_optional_entry_without_changing_it(self):
        from coopagents.onboarding_doctor import mcp_check
        from coopagents.spaces import private_write
        path = self.root / 'profile.json'
        private_write(path, dict(schema_version=1, origin='http://127.0.0.1:8765',
                                room_id='room', member_id='member', agent_token='fixture'))
        self.path.write_text(self.table, encoding='utf-8')
        original = self.path.read_bytes()
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root)}), \
                patch.object(space_connect, '_registered', return_value=space_connect.bridge_command(path.resolve())):
            result = mcp_check('codex', path, name='coopagents_test', cli=['synthetic'])
        self.assertEqual(result['status'], 'needs_user')
        self.assertIn('connect', result['next'])
        self.assertEqual(self.path.read_bytes(), original)

    def test_concurrent_user_edit_is_preserved_instead_of_overwritten(self):
        self.path.write_text(self.table, encoding='utf-8')
        original = self.path.read_bytes()
        edited = self.prefix + self.table
        def change_while_staging(path):
            if path.suffix == '.pending':
                self.path.write_text(edited, encoding='utf-8')
        with patch('coopagents.spaces.protect', side_effect=change_while_staging):
            with self.assertRaisesRegex(space_connect.ConnectError, 'changed during'):
                self.configure()
        self.assertEqual(self.path.read_text(encoding='utf-8'), edited)
        self.assertEqual(next(self.root.glob('*.bak')).read_bytes(), original)
        self.assertTrue(list(self.root.glob('*.pending')))


if __name__ == '__main__':
    unittest.main()
