"""Native prerequisites and owner diagnostics use only explicit read-only probes."""
import json
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from coopagents import onboarding_doctor as doctor


class NativePrerequisiteTests(unittest.TestCase):
    def check(self, tool, code=0, stdout='', stderr=''):
        with patch.object(doctor, '_tool_and_cli', return_value=(tool, [['native-cli']], None)), \
                patch.object(doctor.space_connect, '_run', return_value=CompletedProcess(
                    [], code, stdout, stderr)) as run:
            result = doctor.native_agent_check(tool)
        run.assert_called_once_with(['native-cli', 'auth' if tool == 'claude' else 'login', 'status'], timeout=10)
        return result

    def test_codex_logged_out_is_actionable_and_does_not_echo_output(self):
        result = self.check('codex', 1, stderr='Not logged in\nprivate detail')
        self.assertEqual(result['status'], 'needs_user')
        self.assertIn('Log in', result['next'])
        self.assertNotIn('private detail', json.dumps(result))

    def test_codex_login_does_not_claim_backend_or_model_availability(self):
        result = self.check('codex', stderr='Logged in using ChatGPT')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['evidence']['login_state'], 'authenticated')
        self.assertEqual(result['evidence']['backend_reachability'], 'unimplemented')
        self.assertEqual(result['evidence']['model_turn'], 'not_run')

    def test_claude_json_login_presence_does_not_prove_backend_or_model_access(self):
        for logged_in in (True, False):
            with self.subTest(logged_in=logged_in):
                result = self.check('claude', stdout=json.dumps({'loggedIn': logged_in, 'email': 'private@example.com'}))
                self.assertEqual(result['status'], 'unknown' if logged_in else 'needs_user')
                self.assertEqual(result['evidence']['backend_reachability'], 'unimplemented')
                self.assertEqual(result['evidence']['model_turn'], 'not_run')
                self.assertNotIn('private@example.com', json.dumps(result))

    def test_unsupported_or_ambiguous_status_never_passes(self):
        for tool, stdout in (('codex', 'unauthenticated'), ('codex', 'authenticated: false'),
                             ('claude', '{"loggedIn":"false"}'), ('claude', 'unexpected native output')):
            with self.subTest(tool=tool, stdout=stdout):
                result = self.check(tool, stdout=stdout)
                self.assertEqual(result['status'], 'unknown')

    def test_native_cli_timeout_is_unknown_without_a_model_request(self):
        with patch.object(doctor, '_tool_and_cli', return_value=('codex', [['native-cli']], None)), \
                patch.object(doctor.space_connect, '_run', side_effect=doctor.space_connect.ConnectError('unavailable')):
            result = doctor.native_agent_check('codex')
        self.assertEqual(result['status'], 'unknown')

    def test_unknown_next_steps_are_visible_in_text(self):
        result = doctor.aggregate([doctor.make_check('native_agent', 'unknown', 'Not verified.', 'Run one turn with permission.')])
        self.assertIn('Next: Run one turn with permission.', doctor.render_text(result))


class OwnerDiagnosticsTests(unittest.TestCase):
    profile = {'room_id': 'room', 'control_origin': 'http://127.0.0.1:8769', 'control_token': 'synthetic-control'}

    def test_owner_reports_endpoint_independently_of_loopback(self):
        for reason, expected in (('network_mode_local', 'skipped'), ('udp_send_denied', 'fail'),
                                 ('starting', 'unknown'), ('relay_unavailable', 'unknown')):
            with self.subTest(reason=reason), patch('coopagents.space_runtime.request', return_value={
                    'room_id': 'room', 'p2p': {'online': False, 'reason': reason}}):
                result = doctor.owner_p2p_check(self.profile)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['evidence']['reason'], reason)
                self.assertTrue(result['next'])

    def test_owner_with_home_relay_does_not_claim_remote_access(self):
        with patch('coopagents.space_runtime.request', return_value={'room_id': 'room', 'p2p': {'online': True}}):
            result = doctor.owner_p2p_check(self.profile)
        self.assertEqual(result['status'], 'pass')
        self.assertIn('remote access is not tested', result['summary'])

    def test_wrong_control_identity_or_older_host_is_unknown(self):
        for response in ({'room_id': 'different', 'p2p': {'online': True}}, {'room_id': 'room'}):
            with self.subTest(response=response), patch('coopagents.space_runtime.request', return_value=response):
                self.assertEqual(doctor.owner_p2p_check(self.profile)['status'], 'unknown')

    def test_binding_check_requires_actual_binding_not_room_label(self):
        for binding, expected in ((None, 'needs_user'), ({'repository': 'github.com/example/repo'}, 'pass')):
            with self.subTest(binding=binding), patch.object(doctor, '_request_profile', return_value={'binding': binding}) as request:
                result = doctor.repository_binding_check({})
            request.assert_called_once_with({}, '/api/git')
            self.assertEqual(result['status'], expected)

    def test_missing_binding_endpoint_or_malformed_response_is_unknown(self):
        with patch.object(doctor, '_request_profile', return_value={}):
            self.assertEqual(doctor.repository_binding_check({})['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
