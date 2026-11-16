import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coopagents.deepseek_harness import (CHECKPOINT_PLUGIN_FILE, CHECKPOINT_PLUGIN_NAME,
                                         MCP_CLIENT_PLUGIN, checkpoint_plugin_present,
                                         checkpoint_plugin_row, checkpoint_plugin_text, dsh_home,
                                         export_checkpoint_plugin, mcp_client_row, patch_layers, plan,
                                         row_present)


class RowTests(unittest.TestCase):
    def test_row_follows_the_documented_mcp_client_shape(self):
        row = mcp_client_row('https://team.example/mcp')
        lines = row.splitlines()
        self.assertIn('- insert:', lines)
        self.assertIn('  - id: "coopagents-mcp-client"', lines)
        self.assertIn("    name: '%s'" % MCP_CLIENT_PLUGIN, lines)
        self.assertIn('    config:', lines)
        self.assertIn('      serverName: "coopagents"', lines)
        self.assertIn('      transport: "streamable-http"', lines)
        self.assertIn('      url: "https://team.example/mcp"', lines)
        self.assertNotIn('headers:', row, 'No header key is emitted; auth is a manual step')
        self.assertNotIn('Bearer', row)
        self.assertNotIn('${', row)

    def test_row_escapes_values_and_accepts_custom_names(self):
        row = mcp_client_row('https://team.example/mcp?x=1&y=2', 'team-1')
        self.assertIn('serverName: "team-1"', row)
        self.assertIn('url: "https://team.example/mcp?x=1&y=2"', row)
        with self.assertRaises(ValueError):
            mcp_client_row('https://team.example/mcp', 'bad name!')
        with self.assertRaises(ValueError):
            mcp_client_row('https://team.example/mcp', 'x' * 65)

    def test_row_rejects_non_https_and_lookalike_hosts(self):
        for url in ('http://team.example/mcp', 'http://localhost.evil/mcp',
                    'https://user:pass@team.example/mcp', 'https:///mcp', 'https://team.example:99999/mcp'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                mcp_client_row(url)
        self.assertIn('http://127.0.0.1:8765/mcp', mcp_client_row('http://127.0.0.1:8765/mcp'))


class LayerTests(unittest.TestCase):
    def test_home_prefers_dsh_home_env(self):
        with patch.dict('os.environ', {'DSH_HOME': '/tmp/dsh-home'}):
            self.assertEqual(dsh_home(), Path('/tmp/dsh-home'))

    def test_home_defaults_to_dot_dsh(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict('os.environ', {'HOME': folder, 'USERPROFILE': folder}, clear=True):
                self.assertEqual(dsh_home(), Path(folder) / '.dsh')

    def test_profile_layer_precedes_the_home_layer(self):
        layers = patch_layers('web', home=Path('/tmp/dsh'))
        self.assertEqual(layers, [Path('/tmp/dsh/profiles/web/cordis.patch.yml'),
                                  Path('/tmp/dsh/cordis.patch.yml')])

    def test_row_presence_needs_both_markers(self):
        row = mcp_client_row('https://team.example/mcp')
        self.assertTrue(row_present(row))
        self.assertTrue(row_present('# comment\n' + row + '\n- insert:\n  - id: "other"\n'))
        self.assertFalse(row_present('serverName: "coopagents"\n'))
        self.assertFalse(row_present("name: '%s'\n" % MCP_CLIENT_PLUGIN))
        self.assertFalse(row_present(row, 'other-server'))
        self.assertFalse(row_present(''))
        self.assertTrue(row_present(row.replace('"coopagents"', "'coopagents'")))


class PlanTests(unittest.TestCase):
    def test_plan_names_the_layers_and_carries_no_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            result = plan('https://team.example/mcp', profile='web', home=folder)
        self.assertEqual(result['harness'], 'deepseek')
        self.assertEqual(result['profile'], 'web')
        self.assertEqual(result['transport'], 'streamable-http')
        self.assertIn('cordis.patch.yml', result['patch_layers'][0])
        self.assertIn('mcp-client', result['row'])
        self.assertNotIn('Bearer', str(result))
        self.assertIn('developer preview', result['notes'])

    def test_plan_notes_record_live_acceptance_and_the_proven_header_shape(self):
        result = plan('https://team.example/mcp')
        self.assertIn('verified 2026-11-15', result['notes'])
        self.assertIn('literal Authorization header', result['notes'])
        self.assertIn('local-only --patch', result['notes'])
        # The row itself still carries no header key or credential value.
        self.assertNotIn('headers:', result['row'])
        self.assertNotIn('Bearer', result['row'])


class CheckpointPluginTests(unittest.TestCase):
    def test_plugin_text_wires_the_three_checkpoint_events(self):
        text = checkpoint_plugin_text()
        self.assertIn("export const name = '%s'" % CHECKPOINT_PLUGIN_NAME, text)
        self.assertIn("ctx.on('agent/created'", text)
        self.assertIn("ctx.on('agent/inbox/inserted'", text)
        self.assertIn("ctx.on('tools/result'", text)
        self.assertIn("'SessionStart'", text)
        self.assertIn("'UserPromptSubmit'", text)
        self.assertIn("'PostToolUse'", text)
        self.assertIn('agent.inject(createUserMessage(', text)
        self.assertIn("from '@deepseek-ai/dsh-llm'", text)
        self.assertIn('BEGIN COOPAGENTS EXTERNAL DATA', text)
        self.assertIn('COOPAGENTS_SERVICE_URL', text)
        self.assertIn('COOPAGENTS_AGENT_TOKEN', text)
        self.assertNotIn('http://', text)
        self.assertNotIn('https://', text)

    def test_plugin_text_is_fail_open_and_throttles_post_tool_use(self):
        text = checkpoint_plugin_text()
        self.assertIn('THROTTLE_MS = 30000', text)
        self.assertIn("if (event === 'PostToolUse')", text)
        self.assertIn('REQUEST_TIMEOUT_MS', text)
        self.assertIn('room_id !== PROJECT_ID', text)
        self.assertIn("me.kind !== 'agent'", text)

    def test_plugin_text_ignores_injected_inbox_messages(self):
        # Injected context also fires agent/inbox/inserted; without the
        # source-kind guard the plugin would re-inject forever.
        text = checkpoint_plugin_text()
        self.assertIn("payload.message.source.kind === 'user'", text)

    def test_plugin_row_names_a_relative_path_and_carries_no_config(self):
        row = checkpoint_plugin_row()
        lines = row.splitlines()
        self.assertIn('- insert:', lines)
        self.assertIn('  - id: "%s-plugin"' % CHECKPOINT_PLUGIN_NAME, lines)
        self.assertIn('    name: "./%s"' % CHECKPOINT_PLUGIN_FILE, lines)
        self.assertIn('./%s' % CHECKPOINT_PLUGIN_FILE, checkpoint_plugin_row('./' + CHECKPOINT_PLUGIN_FILE))
        self.assertNotIn('config:', row)
        self.assertNotIn('Bearer', row)
        self.assertTrue(checkpoint_plugin_present(row))
        self.assertFalse(checkpoint_plugin_present(mcp_client_row('https://team.example/mcp')))
        with self.assertRaises(ValueError):
            checkpoint_plugin_row('/abs/path/plugin.mjs')
        with self.assertRaises(ValueError):
            checkpoint_plugin_row('../escape.mjs')
        with self.assertRaises(ValueError):
            checkpoint_plugin_row('plugin.txt')

    def test_export_writes_the_file_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'sub' / CHECKPOINT_PLUGIN_FILE
            row = export_checkpoint_plugin(target)
            self.assertEqual(target.read_text(encoding='utf-8'), checkpoint_plugin_text())
            self.assertIn(CHECKPOINT_PLUGIN_FILE, row)
            with self.assertRaises(ValueError):
                export_checkpoint_plugin(target)


class CliTests(unittest.TestCase):
    def test_cli_prints_a_plan_and_rejects_a_bad_url(self):
        import json
        result = subprocess.run([sys.executable, '-m', 'coopagents.deepseek_harness',
                                 '--service-url', 'https://team.example/mcp', '--profile', 'web'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        printed = json.loads(result.stdout)
        self.assertEqual(printed['harness'], 'deepseek')
        self.assertIn('dsh-mcp-client', printed['row'])
        bad = subprocess.run([sys.executable, '-m', 'coopagents.deepseek_harness',
                              '--service-url', 'http://team.example/mcp'],
                             capture_output=True, text=True, timeout=30)
        self.assertNotEqual(bad.returncode, 0)


if __name__ == '__main__':
    unittest.main()
