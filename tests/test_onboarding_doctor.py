import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from coopagents import onboarding_doctor
except ImportError:
    onboarding_doctor = None


class DoctorTestCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(onboarding_doctor, 'onboarding doctor module is missing')


class ResultContractTests(DoctorTestCase):
    def test_make_check_has_stable_fields_and_rejects_unknown_status(self):
        result = onboarding_doctor.make_check(
            'python_runtime', 'pass', 'Python is ready', 'Continue', {'version': '3.13'})
        self.assertEqual(
            set(result), {'id', 'status', 'summary', 'next', 'evidence'})
        self.assertEqual(result['id'], 'python_runtime')
        self.assertEqual(result['status'], 'pass')
        with self.assertRaises(ValueError):
            onboarding_doctor.make_check('python_runtime', 'done', 'bad')

    def test_aggregate_prioritizes_blocked_then_user_then_unknown(self):
        def item(identifier, status):
            return onboarding_doctor.make_check(identifier, status, identifier)

        self.assertEqual(
            onboarding_doctor.aggregate([
                item('python_runtime', 'pass'),
                item('native_tool', 'fail'),
                item('wake_up', 'skipped'),
            ])['overall'], 'blocked')
        self.assertEqual(
            onboarding_doctor.aggregate([
                item('python_runtime', 'pass'),
                item('native_tool', 'needs_user'),
                item('wake_up', 'skipped'),
            ])['overall'], 'needs_user')
        self.assertEqual(
            onboarding_doctor.aggregate([
                item('python_runtime', 'pass'),
                item('native_tool', 'unknown'),
                item('wake_up', 'skipped'),
            ])['overall'], 'unknown')
        self.assertEqual(
            onboarding_doctor.aggregate([
                item('python_runtime', 'pass'),
                item('native_tool', 'pass'),
                item('mcp_configuration', 'pass'),
                item('skill_installation', 'pass'),
                item('project_context', 'pass'),
                item('runtime_reachability', 'pass'),
                item('challenge_round_trip', 'pass'),
                item('session_reload', 'needs_user'),
                item('wake_up', 'skipped'),
            ])['overall'], 'ready')

    def test_secret_redaction_covers_summary_next_and_evidence(self):
        secret = 'agent-secret-value'
        profile = json.dumps({'agent_token': secret, 'room_id': 'room-1'})
        result = onboarding_doctor.make_check(
            'runtime_reachability', 'fail',
            'failed with ' + secret,
            'replace ' + secret,
            {'profile': profile, 'token': secret},
            secrets=(secret, profile),
        )
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result['evidence']['token'], '[redacted]')


class LocalChecksTests(DoctorTestCase):
    def test_python_runtime_reports_isolated_install_without_environment_dump(self):
        result = onboarding_doctor.python_runtime_check()
        self.assertEqual(result['id'], 'python_runtime')
        self.assertIn('version', result['evidence'])
        self.assertIn('interpreter', result['evidence'])
        self.assertNotIn('COOPAGENTS_AGENT_TOKEN', json.dumps(result))

    def test_tool_check_requires_explicit_tool_when_agent_cannot_be_identified(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': '', 'CODEX_SESSION_ID': '', 'CLAUDECODE': ''}, clear=False), \
                patch('coopagents.space_connect.cli_candidates', side_effect=AssertionError('must not guess')):
            result = onboarding_doctor.tool_check()
        self.assertEqual(result['status'], 'needs_user')
        self.assertIn('tool', result['id'])

    def test_skill_check_is_read_only_and_distinguishes_missing_and_matching_copy(self):
        source = Path(onboarding_doctor.__file__).resolve().parent / 'skills' / 'coopagents-space'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = onboarding_doctor.skill_check('codex', root=root)
            self.assertEqual(missing['status'], 'needs_user')
            target = root / 'coopagents-space'
            for path in source.rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    destination = target / path.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(path.read_bytes())
            before = sorted(str(path.relative_to(root)) for path in root.rglob('*'))
            present = onboarding_doctor.skill_check('codex', root=root)
            after = sorted(str(path.relative_to(root)) for path in root.rglob('*'))
        self.assertEqual(present['status'], 'pass')
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
