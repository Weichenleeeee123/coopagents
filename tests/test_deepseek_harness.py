import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coopagents.deepseek_harness import (MCP_CLIENT_PLUGIN, dsh_home, mcp_client_row,
                                         patch_layers, plan, row_present)


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
            with patch.dict('os.environ', {'HOME': folder}, clear=True):
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
