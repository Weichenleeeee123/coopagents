import json
import os
from pathlib import Path
import sys
from uuid import uuid4
import unittest
from unittest.mock import patch
from contextlib import nullcontext, contextmanager


@contextmanager
def retained_directory():
    path = (Path('.local/doctor-tests') / uuid4().hex).resolve()
    path.mkdir(parents=True)
    yield str(path)

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
            ])['overall'], 'needs_user')

    def test_incomplete_checks_cannot_report_ready(self):
        for checks in ([], [onboarding_doctor.make_check('python_runtime', 'pass', 'OK')],
                       [onboarding_doctor.make_check(key, 'skipped', 'Not checked')
                        for key in onboarding_doctor.REQUIRED_CHECKS]):
            self.assertEqual(onboarding_doctor.aggregate(checks)['overall'], 'unknown')

    def test_failed_transport_blocks_and_failure_next_takes_priority(self):
        checks = [onboarding_doctor.make_check('native_tool', 'needs_user', 'Missing', 'Install CLI'),
                  onboarding_doctor.make_check('transport_path', 'fail', 'Offline', 'Start host')]
        self.assertEqual(onboarding_doctor.aggregate(checks)['overall'], 'blocked')
        self.assertEqual(onboarding_doctor.aggregate(checks)['next'], 'Start host')

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

    def test_tool_check_reads_version_but_does_not_echo_cli_output(self):
        fake = str(Path(__file__).with_name('fake_mcp_cli.py').resolve())
        with patch.dict(os.environ, {'FAKE_TOOL': 'codex', 'FAKE_MCP_STATE': str(Path('.local/doctor-fake-state.json'))}):
            result = onboarding_doctor.tool_check('codex', cli=[sys.executable, fake])
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['evidence']['version'], '2.0.0')
        self.assertNotIn('Codex CLI 2.0.0', json.dumps(result))

    def test_skill_check_is_read_only_and_distinguishes_missing_and_matching_copy(self):
        source = Path(onboarding_doctor.__file__).resolve().parent / 'skills' / 'coopagents-space'
        with retained_directory() as directory:
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

    def test_profile_checks_verify_identity_and_complete_challenge_without_secrets(self):
        with retained_directory() as directory:
            profile_path = Path(directory) / 'profile.json'
            profile = {
                'schema_version': 1,
                'origin': 'http://127.0.0.1:8765',
                'room_id': 'room-1',
                'member_id': 'member-1',
                'agent_token': 'agent-secret-value',
            }
            from coopagents.spaces import private_write
            private_write(profile_path, profile)
            responses = {
                '/api/me': {'me': {'room_id': 'room-1', 'member_id': 'member-1', 'kind': 'agent'}},
                '/api/diagnostics/start': {'diagnostic_id': 'diagnostic-1', 'status': 'sent'},
                '/api/diagnostics/read': {'diagnostic_id': 'diagnostic-1', 'challenge': 'challenge-value',
                                           'proof': 'proof-value', 'status': 'read_back'},
                '/api/diagnostics/complete': {'diagnostic_id': 'diagnostic-1', 'status': 'completed'},
            }
            calls = []

            def request(origin, path, **kwargs):
                calls.append((path, kwargs.get('data')))
                return responses[path]

            with patch('coopagents.onboarding_doctor.member_link', return_value=nullcontext()), \
                    patch('coopagents.onboarding_doctor.secrets.token_urlsafe', return_value='challenge-value'), \
                    patch('coopagents.space_runtime.request', side_effect=request):
                result = onboarding_doctor.profile_checks(profile_path)
        self.assertEqual(next(item for item in result['checks'] if item['id'] == 'project_context')['status'], 'pass')
        self.assertEqual(next(item for item in result['checks'] if item['id'] == 'runtime_reachability')['status'], 'pass')
        self.assertEqual(next(item for item in result['checks'] if item['id'] == 'challenge_round_trip')['status'], 'pass')
        self.assertEqual([path for path, _ in calls], [
            '/api/me', '/api/diagnostics/start', '/api/diagnostics/read', '/api/diagnostics/complete'])
        encoded = json.dumps(result)
        self.assertNotIn('agent-secret-value', encoded)
        self.assertNotIn('challenge-value', encoded)
        self.assertNotIn('proof-value', encoded)

    def test_profile_checks_warm_the_member_link_before_verifying(self):
        with retained_directory() as directory:
            profile_path = Path(directory) / 'profile.json'
            profile = {
                'schema_version': 1,
                'origin': 'http://127.0.0.1:8765',
                'room_id': 'room-1',
                'member_id': 'member-1',
                'agent_token': 'agent-secret-value',
            }
            from coopagents.spaces import private_write
            private_write(profile_path, profile)
            responses = {
                '/api/me': {'me': {'room_id': 'room-1', 'member_id': 'member-1', 'kind': 'agent'}},
                '/api/diagnostics/start': {'diagnostic_id': 'diagnostic-1', 'status': 'sent'},
                '/api/diagnostics/read': {'diagnostic_id': 'diagnostic-1', 'challenge': 'challenge-value',
                                           'proof': 'proof-value', 'status': 'read_back'},
                '/api/diagnostics/complete': {'diagnostic_id': 'diagnostic-1', 'status': 'completed'},
            }

            def request(origin, path, **kwargs):
                return responses[path]

            with patch.object(onboarding_doctor, 'member_link', return_value=nullcontext()) as network, \
                    patch('coopagents.onboarding_doctor.secrets.token_urlsafe', return_value='challenge-value'), \
                    patch('coopagents.space_runtime.request', side_effect=request):
                result = onboarding_doctor.profile_checks(profile_path)
        network.assert_called_once_with(profile, warm=True)
        self.assertEqual(next(item for item in result['checks'] if item['id'] == 'runtime_reachability')['status'], 'pass')

    def test_profile_checks_retry_transient_identity_failure_once(self):
        with retained_directory() as directory:
            profile_path = Path(directory) / 'profile.json'
            profile = {
                'schema_version': 1,
                'origin': 'http://127.0.0.1:8765',
                'room_id': 'room-1',
                'member_id': 'member-1',
                'agent_token': 'agent-secret-value',
            }
            from coopagents.spaces import private_write
            private_write(profile_path, profile)
            responses = [
                OSError('transient'),
                {'me': {'room_id': 'room-1', 'member_id': 'member-1', 'kind': 'agent'}},
                {'diagnostic_id': 'diagnostic-1', 'status': 'sent'},
                {'diagnostic_id': 'diagnostic-1', 'challenge': 'challenge-value',
                 'proof': 'proof-value', 'status': 'read_back'},
                {'diagnostic_id': 'diagnostic-1', 'status': 'completed'},
            ]
            with patch.object(onboarding_doctor, 'member_link', return_value=nullcontext()) as network, \
                    patch('coopagents.onboarding_doctor.secrets.token_urlsafe', return_value='challenge-value'), \
                    patch('coopagents.space_runtime.request', side_effect=responses) as fetch, \
                    patch('time.sleep') as slept:
                result = onboarding_doctor.profile_checks(profile_path)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(fetch.call_count, 5)
        slept.assert_called_once_with(2)
        self.assertEqual(next(item for item in result['checks'] if item['id'] == 'runtime_reachability')['status'], 'pass')
        self.assertEqual(next(item for item in result['checks'] if item['id'] == 'challenge_round_trip')['status'], 'pass')

    def test_profile_checks_raise_last_error_after_retry_exhausted(self):
        from coopagents.spaces import private_write
        with retained_directory() as directory:
            path = Path(directory) / 'profile.json'
            private_write(path, dict(schema_version=1, origin='http://127.0.0.1:8765',
                                     room_id='r', member_id='m', agent_token='secret-fixture'))
            with patch.object(onboarding_doctor, 'member_link', return_value=nullcontext()) as network, \
                    patch('coopagents.space_runtime.request', side_effect=TimeoutError('private')), \
                    patch('time.sleep') as slept:
                result = onboarding_doctor.profile_checks(path)
        self.assertEqual(network.call_count, 2)
        slept.assert_called_once_with(2)
        check = next(c for c in result['checks'] if c['id'] == 'runtime_reachability')
        self.assertEqual(check['status'], 'fail')
        self.assertEqual(check['evidence']['reason'], 'unreachable')

    def test_profile_checks_reports_challenge_failure_without_overwriting_reachability(self):
        with retained_directory() as directory:
            profile_path = Path(directory) / 'profile.json'
            profile = {'schema_version': 1, 'origin': 'http://127.0.0.1:8765',
                       'room_id': 'room-1', 'member_id': 'member-1', 'agent_token': 'agent-secret-value'}
            from coopagents.spaces import private_write
            private_write(profile_path, profile)
            responses = {
                '/api/me': {'me': {'room_id': 'room-1', 'member_id': 'member-1', 'kind': 'agent'}},
                '/api/diagnostics/start': {'diagnostic_id': 'diagnostic-1', 'status': 'sent'},
                '/api/diagnostics/read': {'diagnostic_id': 'diagnostic-1', 'challenge': 'wrong',
                                           'proof': 'proof-value', 'status': 'read_back'},
            }
            with patch('coopagents.onboarding_doctor.member_link', return_value=nullcontext()), \
                    patch('coopagents.onboarding_doctor.secrets.token_urlsafe', return_value='challenge-value'), \
                    patch('coopagents.space_runtime.request', side_effect=lambda origin, path, **kwargs: responses[path]):
                result = onboarding_doctor.profile_checks(profile_path)
        statuses = [item for item in result['checks'] if item['id'] == 'runtime_reachability']
        self.assertEqual([item['status'] for item in statuses], ['pass'])
        self.assertEqual(next(item for item in result['checks'] if item['id'] == 'challenge_round_trip')['status'], 'fail')

    def test_global_interpreter_is_not_reported_as_isolated(self):
        with patch.object(sys, 'prefix', sys.base_prefix), patch.object(onboarding_doctor, '_check_imports', return_value=[]):
            result = onboarding_doctor.python_runtime_check()
        self.assertEqual(result['status'], 'needs_user')
        self.assertFalse(result['evidence']['isolated'])

    def test_other_agent_tool_is_rejected_before_cli_execution(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'x', 'CLAUDECODE': ''}), \
                patch.object(onboarding_doctor.space_connect, 'cli_candidates') as candidates:
            result = onboarding_doctor.tool_check('claude')
        self.assertEqual(result['status'], 'needs_user')
        candidates.assert_not_called()

    def test_codex_desktop_alias_reports_codex(self):
        from subprocess import CompletedProcess
        with patch.object(onboarding_doctor.space_connect, 'cli_candidates', return_value=[['good']]), \
                patch.object(onboarding_doctor.space_connect, '_run',
                             return_value=CompletedProcess([], 0, 'codex 1.2.3', '')):
            result = onboarding_doctor.tool_check('codex-desktop')
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['evidence']['tool'], 'codex')

    def test_version_probe_falls_back_to_working_cli(self):
        from subprocess import CompletedProcess
        with patch.object(onboarding_doctor.space_connect, 'cli_candidates', return_value=[['bad'], ['good']]), \
                patch.object(onboarding_doctor.space_connect, '_run', side_effect=[
                    CompletedProcess([], 1, '', 'private failure'), CompletedProcess([], 0, 'codex 1.2.3', '')]):
            result = onboarding_doctor.tool_check('codex')
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['evidence']['version'], '1.2.3')

    def test_no_profile_discovers_entries_but_never_contacts_them(self):
        entry = {'server': 'coopagents_existing', 'python': sys.executable, 'profile': '/private/existing.json'}
        with patch.object(onboarding_doctor.space_connect, 'registered_spaces', return_value=[entry]), \
                patch.object(onboarding_doctor, 'member_link') as network:
            result = onboarding_doctor.run(tool='codex')
        network.assert_not_called()
        self.assertEqual(result['connections'], [entry])
        self.assertNotEqual(result['overall'], 'ready')

    def test_default_discovery_includes_current_claude_project(self):
        with retained_directory() as directory:
            root = Path(directory)
            profile = str(root/'member.json')
            (root/'.claude.json').write_text(json.dumps({'projects': {str(root): {'mcpServers': {
                'coopagents_project': {'command':sys.executable, 'args':[
                    '-m','coopagents.space_bridge','--profile',profile]}}}}}), encoding='utf-8')
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(root)}), \
                    patch.object(os, 'getcwd', return_value=str(root)), \
                    patch.object(onboarding_doctor, 'tool_check', return_value=onboarding_doctor.make_check(
                        'native_tool','pass','Available',evidence={'tool':'claude'})), \
                    patch.object(onboarding_doctor, 'member_link') as network:
                result = onboarding_doctor.run(tool='claude')
            network.assert_not_called()
            self.assertEqual([e['profile'] for e in result['connections']], [profile])

    def test_missing_project_folder_does_not_contact_profile(self):
        with retained_directory() as directory, patch.object(onboarding_doctor, 'member_link') as network:
            result = onboarding_doctor.run(tool='codex', profile_path=Path(directory)/'profile.json',
                                           project_dir=Path(directory)/'absent')
        network.assert_not_called()
        self.assertEqual(next(c for c in result['checks'] if c['id']=='project_context')['status'], 'fail')

    def test_mcp_inspection_reuses_helper_and_custom_name(self):
        with patch.object(onboarding_doctor.space_connect, 'inspect_configuration', return_value={
                'config':'matching', 'server':'custom', 'tool':'codex', 'skill':'present'}) as inspect:
            result = onboarding_doctor.mcp_check('codex', 'profile.json', name='custom')
        inspect.assert_called_once()
        self.assertEqual(inspect.call_args.kwargs['name'], 'custom')
        self.assertEqual(result['status'], 'pass')

    def test_profile_checks_classify_identity_and_challenge_errors(self):
        from urllib.error import HTTPError
        from coopagents.spaces import private_write
        with retained_directory() as directory:
            path = Path(directory)/'profile.json'
            private_write(path, dict(schema_version=1, origin='http://127.0.0.1:8765',
                                     room_id='r', member_id='m', agent_token='secret-fixture'))
            for error, reason in [(HTTPError('http://x',401,'private',{},None), 'credential_rejected'),
                                  (TimeoutError('private'), 'unreachable')]:
                with patch('coopagents.space_runtime.request', side_effect=error):
                    result = onboarding_doctor.profile_checks(path)
                check = next(c for c in result['checks'] if c['id']=='runtime_reachability')
                self.assertEqual(check['evidence']['reason'], reason)
                self.assertNotIn('secret-fixture', json.dumps(result))

    def test_reused_p2p_link_path_is_unknown_not_loopback(self):
        from coopagents.spaces import private_write
        with retained_directory() as directory:
            path = Path(directory)/'profile.json'
            private_write(path, dict(schema_version=1, origin='http://127.0.0.1:8765', room_id='r',
                                     member_id='m', agent_token='secret-fixture', p2p={'endpoint_id':'a'*64}))
            with patch.object(onboarding_doctor, 'member_link', return_value=nullcontext()), \
                    patch('coopagents.space_runtime.request', return_value={'me':{'room_id':'r','member_id':'m','kind':'agent'}}):
                result = onboarding_doctor.profile_checks(path)
        check = next(c for c in result['checks'] if c['id']=='transport_path')
        self.assertEqual(check['status'], 'unknown')
        self.assertEqual(check['evidence']['state'], 'unknown')

    def test_wake_inspection_reports_matching_hooks_without_trusting_or_writing(self):
        from coopagents.space_wake import hook_config
        with retained_directory() as directory:
            repo = Path(directory)
            settings = repo/'.codex/hooks.json'
            settings.parent.mkdir()
            profile = repo/'profile.json'
            settings.write_text(json.dumps({'hooks': hook_config(profile, 'codex')}), encoding='utf-8')
            before = settings.read_bytes()
            result = onboarding_doctor.wake_check('codex', profile, repo)
            self.assertEqual(settings.read_bytes(), before)
            self.assertFalse((repo/'wake-state.sqlite3').exists())
        self.assertEqual(result['status'], 'needs_user')
        self.assertTrue(result['evidence']['configured'])
        self.assertEqual(result['evidence']['trusted'], 'unknown')

    def test_completed_challenge_must_match_the_started_id(self):
        from coopagents.spaces import private_write
        with retained_directory() as directory:
            path = Path(directory)/'profile.json'
            private_write(path, dict(schema_version=1, origin='http://127.0.0.1:8765',
                                     room_id='r', member_id='m', agent_token='secret-fixture'))
            replies = [{'me': {'room_id':'r','member_id':'m','kind':'agent'}},
                       {'diagnostic_id':'first'}, {'diagnostic_id':'first','challenge':'fixed','proof':'proof'},
                       {'diagnostic_id':'second','status':'completed'}]
            with patch('coopagents.space_runtime.request', side_effect=replies), \
                    patch.object(onboarding_doctor.secrets, 'token_urlsafe', return_value='fixed'):
                result = onboarding_doctor.profile_checks(path)
        self.assertEqual(next(c for c in result['checks'] if c['id']=='challenge_round_trip')['status'], 'fail')


class WakeCheckExtensionTests(DoctorTestCase):
    def test_cursor_project_hooks_report_configured_without_writing(self):
        from coopagents.space_wake import hook_config
        with retained_directory() as directory:
            repo = Path(directory)
            hooks = repo / '.cursor' / 'hooks.json'
            hooks.parent.mkdir()
            profile = repo / 'profile.json'
            hooks.write_text(json.dumps({'version': 1, 'hooks': hook_config(profile, 'cursor')}), encoding='utf-8')
            before = hooks.read_bytes()
            result = onboarding_doctor.wake_check('cursor', profile, repo)
            self.assertEqual(hooks.read_bytes(), before)
            self.assertFalse((repo / 'wake-state.sqlite3').exists())
        self.assertEqual(result['status'], 'needs_user')
        self.assertTrue(result['evidence']['configured'])
        self.assertEqual(result['evidence']['execution'], 'unknown')

    def test_cursor_user_hooks_report_configured(self):
        from coopagents.space_wake import hook_config
        with retained_directory() as directory:
            repo = Path(directory)
            home = repo / 'home'
            hooks = home / '.cursor' / 'hooks.json'
            hooks.parent.mkdir(parents=True)
            profile = repo / 'profile.json'
            hooks.write_text(json.dumps({'version': 1, 'hooks': hook_config(profile, 'cursor')}), encoding='utf-8')
            with patch.dict('os.environ', {'HOME': str(home)}):
                result = onboarding_doctor.wake_check('cursor', profile, repo)
        self.assertEqual(result['status'], 'needs_user')
        self.assertTrue(result['evidence']['configured'])

    def test_cursor_partial_hooks_are_unknown_and_foreign_hooks_skipped(self):
        from coopagents.space_wake import hook_config
        with retained_directory() as directory:
            repo = Path(directory)
            hooks = repo / '.cursor' / 'hooks.json'
            hooks.parent.mkdir()
            profile = repo / 'profile.json'
            config = hook_config(profile, 'cursor')
            hooks.write_text(json.dumps({'version': 1, 'hooks': {'stop': config['stop']}}), encoding='utf-8')
            partial = onboarding_doctor.wake_check('cursor', profile, repo)
            hooks.write_text(json.dumps({'version': 1, 'hooks': {'stop': [{'command': 'echo hi'}]}}), encoding='utf-8')
            foreign = onboarding_doctor.wake_check('cursor', profile, repo)
        self.assertEqual(partial['status'], 'unknown')
        self.assertFalse(partial['evidence']['configured'])
        self.assertEqual(foreign['status'], 'skipped')

    def test_cursor_malformed_hooks_are_unknown(self):
        with retained_directory() as directory:
            repo = Path(directory)
            hooks = repo / '.cursor' / 'hooks.json'
            hooks.parent.mkdir()
            hooks.write_text('{"hooks": "nope"}', encoding='utf-8')
            result = onboarding_doctor.wake_check('cursor', repo / 'profile.json', repo)
        self.assertEqual(result['status'], 'unknown')

    def test_zcode_user_hooks_report_configured_without_writing(self):
        from coopagents.space_wake import hook_config, merge_zcode_hooks
        with retained_directory() as directory:
            repo = Path(directory)
            home = repo / 'home'
            config = home / '.zcode' / 'cli' / 'config.json'
            config.parent.mkdir(parents=True)
            profile = repo / 'profile.json'
            config.write_text(json.dumps(merge_zcode_hooks({}, hook_config(profile, 'zcode'))), encoding='utf-8')
            before = config.read_bytes()
            with patch.dict('os.environ', {'HOME': str(home)}):
                result = onboarding_doctor.wake_check('zcode', profile, repo)
            self.assertEqual(config.read_bytes(), before)
        self.assertEqual(result['status'], 'needs_user')
        self.assertTrue(result['evidence']['configured'])
        self.assertTrue(result['evidence']['hooks_enabled'])

    def test_zcode_hooks_present_but_disabled_are_unknown(self):
        from coopagents.space_wake import hook_config, merge_zcode_hooks
        with retained_directory() as directory:
            repo = Path(directory)
            home = repo / 'home'
            config = home / '.zcode' / 'cli' / 'config.json'
            config.parent.mkdir(parents=True)
            profile = repo / 'profile.json'
            document = merge_zcode_hooks({}, hook_config(profile, 'zcode'))
            document['hooks']['enabled'] = False
            config.write_text(json.dumps(document), encoding='utf-8')
            with patch.dict('os.environ', {'HOME': str(home)}):
                result = onboarding_doctor.wake_check('zcode', profile, repo)
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['evidence']['configured'])
        self.assertFalse(result['evidence']['hooks_enabled'])

    def test_zcode_project_hooks_are_ignored_and_missing_config_is_skipped(self):
        from coopagents.space_wake import hook_config, merge_zcode_hooks
        with retained_directory() as directory:
            repo = Path(directory)
            home = repo / 'home'
            home.mkdir()
            project_config = repo / '.zcode' / 'config.json'
            project_config.parent.mkdir()
            profile = repo / 'profile.json'
            project_config.write_text(json.dumps(merge_zcode_hooks({}, hook_config(profile, 'zcode'))), encoding='utf-8')
            with patch.dict('os.environ', {'HOME': str(home)}):
                result = onboarding_doctor.wake_check('zcode', profile, repo)
        self.assertEqual(result['status'], 'skipped')

    def test_codex_desktop_alias_inspects_codex_hooks(self):
        from coopagents.space_wake import hook_config
        with retained_directory() as directory:
            repo = Path(directory)
            settings = repo / '.codex' / 'hooks.json'
            settings.parent.mkdir()
            profile = repo / 'profile.json'
            settings.write_text(json.dumps({'hooks': hook_config(profile, 'codex')}), encoding='utf-8')
            result = onboarding_doctor.wake_check('codex-desktop', profile, repo)
        self.assertEqual(result['status'], 'needs_user')
        self.assertTrue(result['evidence']['configured'])

    def test_run_reports_cursor_wake_hooks_for_a_requested_tool(self):
        from coopagents.space_wake import hook_config
        with retained_directory() as directory:
            repo = Path(directory)
            hooks = repo / '.cursor' / 'hooks.json'
            hooks.parent.mkdir()
            profile = repo / 'profile.json'
            hooks.write_text(json.dumps({'version': 1, 'hooks': hook_config(profile, 'cursor')}), encoding='utf-8')
            result = onboarding_doctor.run(profile_path=str(profile), tool='cursor', project_dir=str(repo))
        check = next(item for item in result['checks'] if item['id'] == 'wake_up')
        self.assertEqual(check['status'], 'needs_user')
        self.assertTrue(check['evidence']['configured'])

    def test_unknown_tool_wake_check_is_skipped(self):
        self.assertEqual(onboarding_doctor.wake_check('pi', '/tmp/profile.json')['status'], 'skipped')
        self.assertEqual(onboarding_doctor.wake_check('cursor', None)['status'], 'skipped')


class HarnessCliCheckTests(DoctorTestCase):
    def test_inventory_reports_presence_and_versions(self):
        from subprocess import CompletedProcess

        def fake_which(binary):
            return {'claude': '/usr/bin/claude', 'kimi': '/home/u/.kimi-code/bin/kimi'}.get(binary)

        def fake_run(argv, **kw):
            versions = {'/usr/bin/claude': 'claude 1.2.3\n', '/home/u/.kimi-code/bin/kimi': 'kimi 2.4.1\n'}
            return CompletedProcess(argv, 0, stdout=versions.get(argv[0], ''), stderr='')

        with patch.object(onboarding_doctor.shutil, 'which', side_effect=fake_which), \
                patch.object(onboarding_doctor.subprocess, 'run', side_effect=fake_run):
            check = onboarding_doctor.harness_cli_check()
        self.assertEqual(check['id'], 'harness_clis')
        self.assertEqual(check['status'], 'pass')
        evidence = check['evidence']['harnesses']
        self.assertEqual(set(evidence), {'claude-code', 'codex', 'deepseek', 'cursor', 'opencode', 'pi', 'kimi-code', 'zcode'})
        self.assertEqual(evidence['claude-code'], {'present': True, 'path': '/usr/bin/claude', 'version': '1.2.3'})
        self.assertEqual(evidence['kimi-code']['version'], '2.4.1')
        self.assertEqual(evidence['codex'], {'present': False})
        self.assertIn('claude-code', check['summary'])

    def test_version_failures_stay_present_and_pass(self):
        with patch.object(onboarding_doctor.shutil, 'which', return_value='/usr/bin/pi'), \
                patch.object(onboarding_doctor.subprocess, 'run', side_effect=OSError('no exec')):
            check = onboarding_doctor.harness_cli_check()
        self.assertEqual(check['status'], 'pass')
        self.assertTrue(all(info['present'] for info in check['evidence']['harnesses'].values()))
        self.assertTrue(all(info['version'] == 'unknown' for info in check['evidence']['harnesses'].values()))

    def test_run_includes_the_inventory_without_changing_overall(self):
        result = onboarding_doctor.run(project_dir='/nonexistent-dir-for-doctor-test')
        check = next(item for item in result['checks'] if item['id'] == 'harness_clis')
        self.assertEqual(check['status'], 'pass')
        self.assertEqual(result['overall'], 'blocked')


class DeepseekMcpCheckTests(DoctorTestCase):
    def test_absent_install_is_skipped(self):
        with retained_directory() as directory:
            home = Path(directory) / 'no-dsh'
            with patch.object(onboarding_doctor.shutil, 'which', return_value=None):
                check = onboarding_doctor.deepseek_mcp_check(home=str(home))
        self.assertEqual(check['status'], 'skipped')
        self.assertFalse(check['evidence']['dsh_on_path'])

    def test_row_present_in_a_patch_layer_passes_without_quoting_contents(self):
        from coopagents.deepseek_harness import mcp_client_row
        with retained_directory() as directory:
            home = Path(directory)
            layer = home / 'cordis.patch.yml'
            layer.write_text(mcp_client_row('https://team.example/mcp') + '# secret-shaped line: token hunter2\n',
                             encoding='utf-8')
            with patch.object(onboarding_doctor.shutil, 'which', return_value='/usr/bin/dsh'):
                check = onboarding_doctor.deepseek_mcp_check(home=str(home))
        self.assertEqual(check['status'], 'pass')
        self.assertTrue(check['evidence']['row_found'])
        self.assertNotIn('hunter2', json.dumps(check))

    def test_home_without_a_row_needs_the_user(self):
        with retained_directory() as directory:
            home = Path(directory)
            (home / 'cordis.patch.yml').write_text('- insert:\n  - id: "other"\n', encoding='utf-8')
            with patch.object(onboarding_doctor.shutil, 'which', return_value=None):
                check = onboarding_doctor.deepseek_mcp_check(home=str(home))
        self.assertEqual(check['status'], 'needs_user')
        self.assertFalse(check['evidence']['row_found'])

    def test_profile_layer_is_checked_before_the_home_layer(self):
        from coopagents.deepseek_harness import mcp_client_row
        with retained_directory() as directory:
            home = Path(directory)
            profile_layer = home / 'profiles' / 'web' / 'cordis.patch.yml'
            profile_layer.parent.mkdir(parents=True)
            profile_layer.write_text(mcp_client_row('https://team.example/mcp'), encoding='utf-8')
            with patch.object(onboarding_doctor.shutil, 'which', return_value=None):
                check = onboarding_doctor.deepseek_mcp_check(profile='web', home=str(home))
        self.assertEqual(check['status'], 'pass')

    def test_oversized_layer_is_unknown(self):
        with retained_directory() as directory:
            home = Path(directory)
            layer = home / 'cordis.patch.yml'
            layer.write_text('# padding\n' * (1024 * 1024 // 10 + 10), encoding='utf-8')
            with patch.object(onboarding_doctor.shutil, 'which', return_value=None):
                check = onboarding_doctor.deepseek_mcp_check(home=str(home))
        self.assertEqual(check['status'], 'unknown')

    def test_run_includes_the_deepseek_check(self):
        result = onboarding_doctor.run(project_dir='/nonexistent-dir-for-doctor-test')
        check = next(item for item in result['checks'] if item['id'] == 'deepseek_mcp')
        self.assertIn(check['status'], ('skipped', 'needs_user', 'pass', 'unknown'))


if __name__ == '__main__':
    unittest.main()
