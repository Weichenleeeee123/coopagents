import json
import os
from pathlib import Path
import tempfile
import unittest

from coopagents.harness_adapters import ConfigConflict, SUPPORTED_HARNESSES, adapter_for


class HarnessAdapterTests(unittest.TestCase):
    def test_all_five_adapters_report_shared_mcp_contract_and_conservative_capabilities(self):
        self.assertEqual(SUPPORTED_HARNESSES, ('cursor', 'opencode', 'pi', 'kimi-code', 'zcode'))
        for name in SUPPORTED_HARNESSES:
            report = adapter_for(name).capabilities(project_root=Path('.'))
            with self.subTest(name=name):
                self.assertEqual(report['harness'], name)
                self.assertEqual(report['mcp'], 'supported')
                self.assertIn(report['config_scope'], ('project', 'user', 'project_or_user', 'extension'))
                self.assertIn(report['native_hook'], ('supported', 'unsupported', 'unknown'))
                self.assertIn(report['idle_wake'], ('supported', 'unsupported', 'unknown'))
                self.assertNotIn('transcript', report)

    def test_json_config_merge_preserves_unrelated_entries_and_is_idempotent(self):
        adapter = adapter_for('cursor')
        existing = {'mcpServers': {'other': {'command': 'other'}}, 'editor': {'fontSize': 14}}
        merged = adapter.merge(existing, 'coopagents', 'python', ['-m', 'coopagents.mcp_service'])
        self.assertEqual(merged['editor'], existing['editor'])
        self.assertEqual(merged['mcpServers']['other'], existing['mcpServers']['other'])
        self.assertEqual(merged['mcpServers']['coopagents']['command'], 'python')
        self.assertEqual(adapter.merge(merged, 'coopagents', 'python', ['-m', 'coopagents.mcp_service']), merged)

    def test_existing_different_entry_is_not_overwritten(self):
        adapter = adapter_for('cursor')
        with self.assertRaises(ConfigConflict):
            adapter.merge({'mcpServers': {'coopagents': {'command': 'evil'}}},
                          'coopagents', 'python', ['-m', 'coopagents.mcp_service'])

    def test_install_refuses_symlink_and_out_of_root_paths(self):
        adapter = adapter_for('cursor')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / '.cursor' / 'mcp.json'
            adapter.install(target, 'coopagents', 'python', ['-m', 'coopagents.mcp_service'], project_root=root)
            self.assertTrue(target.is_file())
            self.assertEqual(json.loads(target.read_text())['mcpServers']['coopagents']['args'],
                             ['-m', 'coopagents.mcp_service'])
            outside = root.parent / 'outside-mcp.json'
            with self.assertRaises(ValueError):
                adapter.install(outside, 'coopagents', 'python', [], project_root=root)
            link = root / 'link.json'
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation unavailable')
            with self.assertRaises(ValueError):
                adapter.install(link, 'coopagents', 'python', [], project_root=root)

    def test_plan_does_not_claim_native_hooks_when_the_adapter_does_not_have_them(self):
        for name in ('pi', 'kimi-code', 'zcode'):
            report = adapter_for(name).capabilities(project_root=Path('.'))
            self.assertNotEqual(report['native_hook'], 'supported')
            self.assertNotEqual(report['idle_wake'], 'supported')

    def test_remote_plan_requires_a_real_service_url_and_rejects_host_lookalikes(self):
        adapter = adapter_for('cursor')
        self.assertIsNone(adapter.plan(Path('.'))['entry'])
        self.assertEqual(adapter.plan(Path('.'))['transport'], 'manual')
        for url in ('http://localhost.evil/mcp', 'http://127.0.0.1.evil/mcp',
                    'https://user:pass@team.example/mcp', 'https://team.example:99999/mcp',
                    'https:///mcp', 'https://?server=mcp'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                adapter.plan(Path('.'), service_url=url)
        with self.assertRaises(ValueError):
            adapter.plan(Path('.'), service_url='https://team.example/mcp', token_env='TOKEN-NAME')

    def test_each_official_project_config_shape_can_install_remote_mcp_without_a_token_value(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in SUPPORTED_HARNESSES:
                adapter = adapter_for(name)
                result = adapter.install_remote(adapter.config_target(root), 'coopagents',
                                                'https://team.example/mcp', project_root=root)
                self.assertEqual(result['status'], 'installed', name)
                document = json.loads(adapter.config_target(root).read_text(encoding='utf-8'))
                if name == 'zcode':
                    entry = document['mcp']['servers']['coopagents']
                elif name == 'opencode':
                    entry = document['mcp']['coopagents']
                else:
                    entry = document['mcpServers']['coopagents']
                self.assertEqual(entry['url'], 'https://team.example/mcp')
                if name == 'kimi-code':
                    self.assertEqual(entry['bearerTokenEnvVar'], 'COOPAGENTS_AGENT_TOKEN')
                elif name in ('cursor', 'zcode'):
                    self.assertIn('${env:COOPAGENTS_AGENT_TOKEN}', entry['headers']['Authorization'])
                else:
                    self.assertIn('${COOPAGENTS_AGENT_TOKEN}', entry['headers']['Authorization'])


if __name__ == '__main__':
    unittest.main()
