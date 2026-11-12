import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from coopagents.checkpoint_hook import hook_argv
from coopagents.zcode_plugin import plugin_files, validate_plugin, write_plugin


class PluginContentTests(unittest.TestCase):
    def setUp(self):
        self.files = plugin_files('https://team.example/mcp')

    def test_bundle_has_exactly_the_documented_files(self):
        self.assertEqual(set(self.files), {'.zcode-plugin/plugin.json', 'hooks/hooks.json',
                                           '.mcp.json', 'README.md'})

    def test_manifest_is_valid_and_names_the_plugin(self):
        manifest = json.loads(self.files['.zcode-plugin/plugin.json'])
        self.assertEqual(manifest['name'], 'coopagents')
        self.assertRegex(manifest['name'], r'^[a-z0-9][a-z0-9._-]{0,127}$')
        self.assertIn('version', manifest)
        self.assertIn('description', manifest)

    def test_hooks_carry_the_checkpoint_process_hooks(self):
        document = json.loads(self.files['hooks/hooks.json'])
        self.assertEqual(set(document['hooks']), {'SessionStart', 'PostToolUse', 'UserPromptSubmit'})
        argv = hook_argv('zcode')
        for event, groups in document['hooks'].items():
            self.assertEqual(len(groups), 1)
            hook = groups[0]['hooks'][0]
            self.assertEqual(hook, {'type': 'process', 'command': argv[0], 'args': argv[1:]})
        self.assertEqual(document['hooks']['SessionStart'][0]['matcher'], 'startup')
        self.assertNotIn('matcher', document['hooks']['PostToolUse'][0])

    def test_mcp_entry_has_no_header_or_credential(self):
        document = json.loads(self.files['.mcp.json'])
        entry = document['mcpServers']['coopagents']
        self.assertEqual(entry, {'type': 'http', 'url': 'https://team.example/mcp', 'enabled': True})
        for text in self.files.values():
            self.assertNotIn('Bearer', text)
            self.assertNotIn('COOPAGENTS_AGENT_TOKEN', text)

    def test_readme_explains_user_scope_auth_and_wake(self):
        readme = self.files['README.md']
        self.assertIn('~/.zcode/cli/config.json', readme)
        self.assertIn('space_wake', readme)
        self.assertIn('https://team.example/mcp', readme)

    def test_bad_urls_and_names_are_rejected(self):
        with self.assertRaises(ValueError):
            plugin_files('https://user:pass@team.example/mcp')
        with self.assertRaises(ValueError):
            plugin_files('https://team.example/mcp', server_name='')


class ValidationTests(unittest.TestCase):
    def test_generated_bundle_validates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'bundle'
            write_plugin(root, 'https://team.example/mcp')
            self.assertEqual(validate_plugin(root), [])

    def test_validation_reports_each_structural_problem(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIn('missing .zcode-plugin/plugin.json', validate_plugin(root))
            (root / '.zcode-plugin').mkdir()
            (root / '.zcode-plugin' / 'plugin.json').write_text('{"name": "Bad Name!"}', encoding='utf-8')
            problems = validate_plugin(root)
            self.assertTrue(any('manifest name' in problem for problem in problems))
            (root / 'hooks').mkdir()
            (root / 'hooks' / 'hooks.json').write_text(
                '{"hooks": {"SessionEnd": [{"hooks": [{"command": "x"}]}]}}', encoding='utf-8')
            problems = validate_plugin(root)
            self.assertTrue(any('undocumented hook event' in problem for problem in problems))
            (root / '.mcp.json').write_text(
                '{"mcpServers": {"coopagents": {"type": "http", "url": "https://x.example", "bogus": 1}}}',
                encoding='utf-8')
            problems = validate_plugin(root)
            self.assertTrue(any('outside the ZCode entry schema' in problem for problem in problems))

    def test_write_refuses_non_empty_directories_and_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'bundle'
            root.mkdir()
            (root / 'existing.txt').write_text('keep me', encoding='utf-8')
            with self.assertRaises(ValueError):
                write_plugin(root, 'https://team.example/mcp')
            self.assertEqual((root / 'existing.txt').read_text(), 'keep me')
            link = Path(folder) / 'link'
            try:
                link.symlink_to(root, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation unavailable')
            with self.assertRaises(ValueError):
                write_plugin(link, 'https://team.example/mcp')


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'coopagents.zcode_plugin', *args],
                              capture_output=True, text=True, timeout=30)

    def test_cli_export_and_validate_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            target = str(Path(folder) / 'bundle')
            exported = self.run_cli('--service-url', 'https://team.example/mcp', '--export', target)
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(json.loads(exported.stdout)['status'], 'exported')
            validated = self.run_cli('--validate', target)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(json.loads(validated.stdout)['status'], 'valid')
            again = self.run_cli('--service-url', 'https://team.example/mcp', '--export', target)
            self.assertNotEqual(again.returncode, 0)

    def test_cli_rejects_a_bad_url(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_cli('--service-url', 'http://localhost.evil/mcp',
                                  '--export', str(Path(folder) / 'bundle'))
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
