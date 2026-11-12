import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from uuid import uuid4

from coopagents.harness_extensions import (MARKER, extension_text, install_path, opencode_plugin_text,
                                           pi_extension_text, write_extension_file)

NODE = shutil.which('node')

OPENCODE_DRIVER = '''
import { Coopagents } from "./plugin.mjs";
const calls = { fetch: [], prompt: [] };
const brief = JSON.parse(process.env.DRIVER_BRIEF || "null");
globalThis.fetch = async (url, init) => {
  calls.fetch.push({ url, method: init?.method, auth: (init?.headers || {}).Authorization,
                     body: JSON.parse(init?.body || "{}") });
  return { ok: true, status: 200, json: async () => ({ brief }) };
};
const client = { session: { prompt: async (args) => { calls.prompt.push(args); } } };
const hooks = await Coopagents({ client });
const fire = async (type, sessionID) => {
  await hooks.event({ event: { type, properties: { sessionID } } });
};
await fire("session.created", "s1");
await fire("session.idle", "s1");
await fire("session.idle", "s1");
await fire("session.deleted", "s1");
console.log(JSON.stringify(calls));
'''

PI_DRIVER = '''
import coopagents from "./extension.mjs";
const calls = { fetch: [], messages: [] };
const brief = JSON.parse(process.env.DRIVER_BRIEF || "null");
globalThis.fetch = async (url, init) => {
  calls.fetch.push({ url, body: JSON.parse(init?.body || "{}") });
  return { ok: true, status: 200, json: async () => ({ brief }) };
};
const handlers = {};
const pi = {
  on: (event, fn) => { handlers[event] = fn; },
  sendUserMessage: (text, options) => { calls.messages.push({ text, options }); },
};
coopagents(pi);
await handlers["session_start"]({});
await handlers["agent_end"]({});
await handlers["agent_end"]({});
console.log(JSON.stringify({ ...calls, events: Object.keys(handlers) }));
'''


def evidence(name):
    root = Path('.local/test-evidence') / ('extensions-' + name + '-' + uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    return root


class ExtensionContentTests(unittest.TestCase):
    def test_generated_files_carry_the_marker_env_names_and_event_wiring(self):
        plugin = opencode_plugin_text()
        for needle in (MARKER, 'COOPAGENTS_SERVICE_URL', 'COOPAGENTS_PROJECT_ID', 'COOPAGENTS_AGENT_TOKEN',
                       'session.created', 'session.idle', 'noReply', 'export const Coopagents'):
            self.assertIn(needle, plugin)
        self.assertNotIn('coopagents.checkpoint_hook', plugin)
        extension = pi_extension_text()
        for needle in (MARKER, 'COOPAGENTS_SERVICE_URL', 'session_start', 'agent_end',
                       'sendUserMessage', 'followUp', 'export default function'):
            self.assertIn(needle, extension)
        self.assertNotIn('coopagents.checkpoint_hook', extension)
        self.assertNotIn('import ', extension, 'The Pi file must not depend on a package name')

    def test_generated_files_carry_no_credential_value(self):
        for text in (opencode_plugin_text(), pi_extension_text()):
            self.assertEqual(text.count('Bearer'), 1, 'Only the header construction may mention Bearer')
            self.assertIn('Bearer " + TOKEN', text)


@unittest.skipUnless(NODE, 'node is required to execute the generated files')
class ExtensionExecutionTests(unittest.TestCase):
    def run_driver(self, harness, brief, connected=True):
        root = evidence(harness).absolute()
        module = 'plugin.mjs' if harness == 'opencode' else 'extension.mjs'
        (root / module).write_text(extension_text(harness), encoding='utf-8')
        driver = OPENCODE_DRIVER if harness == 'opencode' else PI_DRIVER
        (root / 'driver.mjs').write_text(driver, encoding='utf-8')
        checked = subprocess.run([NODE, '--check', str(root / module)], capture_output=True, text=True, timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        run_env = {key: value for key, value in os.environ.items() if not key.startswith('COOPAGENTS_')}
        run_env['DRIVER_BRIEF'] = json.dumps(brief)
        if connected:
            run_env.update({'COOPAGENTS_SERVICE_URL': 'http://127.0.0.1:9',
                            'COOPAGENTS_PROJECT_ID': 'room-1', 'COOPAGENTS_AGENT_TOKEN': 'tok-1'})
        result = subprocess.run([NODE, str(root / 'driver.mjs')], cwd=root, capture_output=True,
                                text=True, timeout=30, env=run_env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_opencode_plugin_posts_checkpoints_and_injects_on_idle(self):
        calls = self.run_driver('opencode', {'tasks': [{'id': 1, 'title': 'Review the login flow'}],
                                             'content_is_untrusted': True})
        self.assertEqual([c['body']['event'] for c in calls['fetch']], ['SessionStart', 'PostToolUse'])
        for call in calls['fetch']:
            self.assertEqual(call['url'], 'http://127.0.0.1:9/api/checkpoints')
            self.assertEqual(call['method'], 'POST')
            self.assertEqual(call['auth'], 'Bearer tok-1')
            self.assertEqual(call['body']['session_key'], 's1')
            self.assertEqual(call['body']['tool'], 'opencode')
        self.assertEqual(len(calls['prompt']), 1)
        prompt = calls['prompt'][0]
        self.assertEqual(prompt['path'], {'id': 's1'})
        self.assertTrue(prompt['body']['noReply'])
        text = prompt['body']['parts'][0]['text']
        self.assertIn('BEGIN COOPAGENTS EXTERNAL DATA', text)
        self.assertIn('Review the login flow', text)
        self.assertLessEqual(len(text), 9000)

    def test_opencode_plugin_stays_silent_without_a_connection_or_content(self):
        calls = self.run_driver('opencode', {'tasks': [{'id': 1, 'title': 'x'}]}, connected=False)
        self.assertEqual(calls, {'fetch': [], 'prompt': []})
        calls = self.run_driver('opencode', {'tasks': [], 'content_is_untrusted': True})
        self.assertEqual(len(calls['fetch']), 2)
        self.assertEqual(calls['prompt'], [])

    def test_pi_extension_posts_checkpoints_and_sends_a_followup(self):
        calls = self.run_driver('pi', {'requests': [{'id': 7, 'body': 'Need the login format'}],
                                       'content_is_untrusted': True})
        self.assertEqual(calls['events'], ['session_start', 'agent_end'])
        self.assertEqual([c['body']['event'] for c in calls['fetch']], ['SessionStart', 'PostToolUse'])
        keys = [c['body']['session_key'] for c in calls['fetch']]
        self.assertEqual(keys[0], keys[1], 'One Pi process keeps one session key')
        for call in calls['fetch']:
            self.assertEqual(call['body']['tool'], 'pi')
            self.assertTrue(call['body']['session_key'].startswith('pi-'))
        self.assertEqual(len(calls['messages']), 1)
        message = calls['messages'][0]
        self.assertEqual(message['options'], {'deliverAs': 'followUp'})
        self.assertIn('Need the login format', message['text'])

    def test_pi_extension_stays_silent_without_a_connection_or_content(self):
        calls = self.run_driver('pi', {'tasks': [{'id': 1}]}, connected=False)
        self.assertEqual(calls['fetch'], [])
        self.assertEqual(calls['messages'], [])
        calls = self.run_driver('pi', {'tasks': [], 'content_is_untrusted': True})
        self.assertEqual(len(calls['fetch']), 2)
        self.assertEqual(calls['messages'], [])


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.root = evidence('install')

    def test_write_refuses_unmanaged_files_and_symlinks_and_is_idempotent(self):
        target = self.root / 'coopagents.js'
        target.write_text('// someone else\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            write_extension_file(target, opencode_plugin_text())
        self.assertEqual(target.read_text(), '// someone else\n')
        link = self.root / 'link.js'
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            write_extension_file(link, opencode_plugin_text())
        managed = self.root / 'managed.js'
        first = write_extension_file(managed, opencode_plugin_text())
        self.assertEqual(first['status'], 'installed')
        second = write_extension_file(managed, opencode_plugin_text())
        self.assertEqual(second['status'], 'already_configured')
        replaced = write_extension_file(managed, opencode_plugin_text().replace('THROTTLE_MS = 30000', 'THROTTLE_MS = 1000'))
        self.assertEqual(replaced['status'], 'installed')

    def test_install_paths_cover_project_and_user_scopes(self):
        from unittest.mock import patch
        home = (self.root / 'home').absolute()
        home.mkdir()
        project = (self.root / 'project').absolute()
        project.mkdir()
        with patch.dict('os.environ', {'HOME': str(home)}):
            self.assertEqual(install_path('opencode', 'user'), home / '.config/opencode/plugins/coopagents.js')
            self.assertEqual(install_path('pi', 'user'), home / '.pi/agent/extensions/coopagents.ts')
            self.assertEqual(install_path('opencode', 'project', project), project / '.opencode/plugins/coopagents.js')
            self.assertEqual(install_path('pi', 'project', project), project / '.pi/extensions/coopagents.ts')
            with self.assertRaises(ValueError):
                install_path('opencode', 'project', self.root / 'missing')
            with self.assertRaises(ValueError):
                install_path('opencode', 'project', home)

    def test_cli_export_and_install(self):
        from unittest.mock import patch
        home = (self.root / 'cli-home').absolute()
        home.mkdir()
        project = (self.root / 'cli-project').absolute()
        project.mkdir()
        target = self.root / 'exported.js'
        result = subprocess.run([sys.executable, '-m', 'coopagents.harness_extensions', '--harness', 'opencode',
                                 '--export', str(target)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), opencode_plugin_text())
        refused = subprocess.run([sys.executable, '-m', 'coopagents.harness_extensions', '--harness', 'opencode',
                                  '--export', str(target)], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(refused.returncode, 0)
        with patch.dict('os.environ', {'HOME': str(home)}):
            installed = subprocess.run([sys.executable, '-m', 'coopagents.harness_extensions', '--harness', 'pi',
                                        '--install', '--scope', 'project', '--project-dir', str(project)],
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual((project / '.pi/extensions/coopagents.ts').read_text(), pi_extension_text())
            installed = subprocess.run([sys.executable, '-m', 'coopagents.harness_extensions', '--harness', 'opencode',
                                        '--install', '--scope', 'user'],
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual((home / '.config/opencode/plugins/coopagents.js').read_text(), opencode_plugin_text())
            missing = subprocess.run([sys.executable, '-m', 'coopagents.harness_extensions', '--harness', 'pi',
                                      '--install', '--scope', 'project', '--project-dir', str(self.root / 'missing')],
                                     capture_output=True, text=True, timeout=30)
            self.assertNotEqual(missing.returncode, 0)
