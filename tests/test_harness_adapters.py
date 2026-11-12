import json
import os
from pathlib import Path
import tempfile
import unittest

from coopagents.harness_adapters import ConfigConflict, SUPPORTED_HARNESSES, adapter_for


class HarnessAdapterTests(unittest.TestCase):
    def test_all_adapters_report_shared_mcp_contract_and_conservative_capabilities(self):
        self.assertEqual(SUPPORTED_HARNESSES, ('cursor', 'opencode', 'pi', 'kimi-code', 'zcode', 'windsurf'))
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

    def test_opencode_remote_plan_uses_native_environment_substitution_syntax(self):
        # OpenCode expands {env:NAME}; ${NAME} is sent literally.
        plan = adapter_for('opencode').plan(
            Path('.'), service_url='https://team.example/mcp', token_env='ACCEPTANCE_TOKEN')
        self.assertEqual(plan['entry']['headers']['Authorization'], 'Bearer {env:ACCEPTANCE_TOKEN}')
        self.assertEqual(plan['config_variant'], 'v2')

    def test_opencode_v1_variant_keeps_the_legacy_shape(self):
        adapter = adapter_for('opencode', 'v1')
        self.assertEqual(adapter.capabilities()['config_variant'], 'v1')
        merged = adapter.merge_remote({}, 'coopagents', 'https://team.example/mcp')
        entry = merged['mcp']['coopagents']
        self.assertTrue(entry['enabled'])
        self.assertNotIn('oauth', entry)
        self.assertNotIn('servers', merged['mcp'])
        local = adapter.merge({}, 'coopagents', 'python', ['-m', 'coopagents.mcp_service'])
        self.assertEqual(local['mcp']['coopagents'],
                         {'type': 'local', 'command': ['python', '-m', 'coopagents.mcp_service'], 'enabled': True})

    def test_opencode_v2_local_entry_has_no_enabled_field(self):
        merged = adapter_for('opencode').merge({}, 'coopagents', 'python', ['-m', 'coopagents.mcp_service'])
        self.assertEqual(merged['mcp']['servers']['coopagents'],
                         {'type': 'local', 'command': ['python', '-m', 'coopagents.mcp_service']})

    def test_config_variants_are_opencode_only_and_validated(self):
        with self.assertRaises(ValueError):
            adapter_for('cursor', 'v1')
        with self.assertRaises(ValueError):
            adapter_for('opencode', 'v3')
        with self.assertRaises(ValueError):
            adapter_for('opencode').merge({'mcp': {'servers': 'nope'}}, 'coopagents', 'python', [])

    def test_each_generated_config_shape_can_install_remote_mcp_without_a_token_value(self):
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
                    entry = document['mcp']['servers']['coopagents']
                else:
                    entry = document['mcpServers']['coopagents']
                self.assertEqual(entry['url'], 'https://team.example/mcp')
                if name == 'kimi-code':
                    self.assertEqual(entry['bearerTokenEnvVar'], 'COOPAGENTS_AGENT_TOKEN')
                elif name == 'zcode':
                    # ZCode config files do not expand ${env:}; a placeholder
                    # would reach the server literally, so no header is written.
                    self.assertEqual(entry['type'], 'http')
                    self.assertTrue(entry['enabled'])
                    self.assertNotIn('headers', entry)
                    self.assertNotIn('${env:', json.dumps(entry))
                elif name == 'cursor':
                    self.assertIn('${env:COOPAGENTS_AGENT_TOKEN}', entry['headers']['Authorization'])
                elif name == 'opencode':
                    # Native V2 shape: grouped under mcp.servers, no enabled
                    # field, oauth off so the bearer header is used as-is.
                    self.assertEqual(entry['headers']['Authorization'], 'Bearer {env:COOPAGENTS_AGENT_TOKEN}')
                    self.assertNotIn('enabled', entry)
                    self.assertIs(entry['oauth'], False)
                elif name == 'windsurf':
                    # Header expansion is disputed across sources and the
                    # project file is committed, so no header is written.
                    self.assertEqual(entry, {'url': 'https://team.example/mcp'})
                    self.assertNotIn('${', json.dumps(entry))
                else:
                    self.assertIn('${COOPAGENTS_AGENT_TOKEN}', entry['headers']['Authorization'])
                    self.assertEqual(entry['exposure'], 'direct')
                    self.assertIn('Coopagents', entry['description'])

    def test_zcode_remote_plan_explains_user_scope_auth(self):
        plan = adapter_for('zcode').plan(Path('.'), service_url='https://team.example/mcp')
        self.assertNotIn('headers', plan['entry'])
        self.assertIn('~/.zcode/cli/config.json', plan['notes'])
        self.assertIn('does not expand', plan['notes'])

    def test_zcode_stdio_entry_declares_its_transport(self):
        entry = adapter_for('zcode').merge({}, 'coopagents', 'python', ['-m', 'coopagents.mcp_service'])
        server = entry['mcp']['servers']['coopagents']
        self.assertEqual(server, {'type': 'stdio', 'command': 'python', 'args': ['-m', 'coopagents.mcp_service']})

    def test_pi_entries_declare_tools_directly_to_the_model(self):
        # Pi's default codemode exposure hides MCP tools from the model; direct
        # exposure declares them like built-in tools, for both transports.
        stdio = adapter_for('pi').merge({}, 'coopagents', 'python', ['-m', 'coopagents.mcp_service'])
        self.assertEqual(stdio['mcpServers']['coopagents']['exposure'], 'direct')
        remote = adapter_for('pi').plan(Path('.'), service_url='https://team.example/mcp')
        self.assertEqual(remote['entry']['exposure'], 'direct')

    def test_kimi_and_cursor_notes_record_verified_interpolation(self):
        kimi = adapter_for('kimi-code').capabilities(project_root=Path('.'))
        self.assertIn('bearerTokenEnvVar', kimi['notes'])
        self.assertIn('workspace trust', kimi['notes'])
        cursor = adapter_for('cursor').capabilities(project_root=Path('.'))
        self.assertIn('${env:NAME}', cursor['notes'])
        self.assertIn('official Cursor MCP docs', cursor['notes'])

    def test_windsurf_spec_names_the_devin_config_and_rename(self):
        report = adapter_for('windsurf').capabilities(project_root=Path('.'))
        self.assertEqual(report['config_path'], str(Path('.').resolve() / '.devin' / 'mcp_config.json'))
        self.assertEqual(report['config_scope'], 'project')
        self.assertEqual(report['native_hook'], 'unsupported')
        self.assertEqual(report['idle_wake'], 'unsupported')
        self.assertIn('Devin Desktop', report['notes'])
        self.assertIn('serverUrl', report['notes'])
        self.assertIn('.devin/mcp_config.local.json', report['notes'])
        self.assertIn('~/.codeium/windsurf/mcp_config.json', report['notes'])
        self.assertIn('unverified', report['notes'])

    def test_windsurf_stdio_entry_is_a_plain_command(self):
        entry = adapter_for('windsurf').merge({}, 'coopagents', 'python', ['-m', 'coopagents.mcp_service'])
        server = entry['mcpServers']['coopagents']
        self.assertEqual(server, {'command': 'python', 'args': ['-m', 'coopagents.mcp_service']})

    def test_windsurf_remote_plan_points_auth_at_the_local_override(self):
        plan = adapter_for('windsurf').plan(Path('.'), service_url='https://team.example/mcp')
        self.assertEqual(plan['entry'], {'url': 'https://team.example/mcp'})
        self.assertIn('.devin/mcp_config.local.json', plan['notes'])
        self.assertIn('devin mcp add -s local', plan['notes'])

    def test_zcode_capabilities_report_hook_install_without_claiming_live_acceptance(self):
        report = adapter_for('zcode').capabilities(project_root=Path('.'))
        self.assertEqual(report['native_hook'], 'unknown')
        self.assertEqual(report['idle_wake'], 'unsupported')
        self.assertIn('user config only', report['notes'])
        self.assertIn('unverified', report['notes'])


if __name__ == '__main__':
    unittest.main()
