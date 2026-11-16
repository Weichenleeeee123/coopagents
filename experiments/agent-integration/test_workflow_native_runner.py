"""Native-free runner regressions; none of these are native-model evidence."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

MODULE = Path(__file__).with_name('workflow_native_runner.py')
ROOT = Path(__file__).resolve().parents[2]


def load_runner():
    spec = importlib.util.spec_from_file_location('workflow_native_runner', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), 'real native workflow runner is required')
        self.runner = load_runner()
        self.root = ROOT / '.local/test-evidence/native-runner-tests' / uuid4().hex

    def test_native_execution_requires_explicit_opt_in(self):
        with self.assertRaises(SystemExit) as result:
            self.runner.main(['run', '--output', str(self.root)])
        self.assertNotEqual(result.exception.code, 0)
        self.assertFalse(self.root.exists())

    def test_both_arms_use_real_mcp_and_identical_tool_neutral_instructions(self):
        observed = {}
        for arm in ('primitive', 'composite'):
            runtime = self.runner.NativeRuntime(self.root / arm, arm)
            try:
                async def inspect():
                    member = runtime.members['requester']
                    async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + member['agent_token']}) as http:
                        async with Client(streamable_http_client(runtime.url + '/mcp', http_client=http), cache=None) as client:
                            tools = (await client.list_tools()).tools
                            descriptions = {tool.name: tool.description for tool in tools}
                            who = await client.call_tool('whoami', {})
                            self.assertFalse(who.is_error)
                            return descriptions
                observed[arm] = asyncio.run(inspect())
                self.assertEqual(set(observed[arm]), set(runtime.tool_names))
                self.assertNotIn('decision', observed[arm])
                self.assertNotIn('force_handoff', observed[arm])
            finally:
                runtime.stop()
        self.assertEqual(set(observed['composite']) - set(observed['primitive']), {'ask_owner', 'read_replies'})
        self.assertEqual(set(observed['primitive']) - set(observed['composite']), set())
        for name, description in observed['primitive'].items():
            self.assertEqual(description, observed['composite'][name])
        for forbidden in ('ask_owner', 'send_request', 'checkpoint', 'read_team', 'read_replies'):
            self.assertNotIn(forbidden, self.runner.EVALUATION_INSTRUCTIONS)

    def test_ordinary_continuation_does_not_teach_protocol_or_reveal_answer(self):
        for stage in ('initial', 'continue', 'waiting', 'reopen'):
            goal = self.runner.stage_goal('Business goal without an answer.', stage)
            for forbidden in ('ask_owner', 'read_team', 'reply', 'checkpoint', 'send_request', 'profile_secret'):
                self.assertNotIn(forbidden, goal)
        with self.assertRaises(ValueError):
            self.runner.stage_goal('goal', 'invented')

    def test_no_exchange_pass_from_artifact_or_receipt_alone(self):
        result = self.runner.audit_exchange(
            expected_field='profile_secret', requester='front', responder='back',
            turns=[], requests=[{'id': 1, 'sender_member_id': 'front', 'receiver_member_id': 'back',
                'read_at': 'observed', 'replies': [{'id': 2, 'author_member_id': 'back', 'body': 'profile_secret'}]}],
            before={'payload_correct': False}, after={'payload_correct': True, 'artifact_correct': True})
        self.assertFalse(result['native_success'])
        self.assertFalse(result['model_reply'])
        self.assertFalse(result['answer_used'])

    def test_wrong_recipient_or_missing_source_read_cannot_pass(self):
        request = {'id': 1, 'sender_member_id': 'front', 'receiver_member_id': 'wrong', 'context_version': 1,
                   'replies': [{'id': 2, 'author_member_id': 'back', 'body': 'profile_secret'}]}
        result = self.runner.audit_exchange(expected_field='profile_secret', requester='front', responder='back',
            turns=[], requests=[request], before={'payload_correct': False},
            after={'payload_correct': True, 'artifact_correct': True})
        self.assertFalse(result['correct_route'])
        self.assertFalse(result['native_success'])

    def test_comparison_keeps_failures_unknown_cost_and_denominators(self):
        common = dict(pair_id='p1', scenario_id='frontend-backend', source_commit='commit',
                      source_content_fingerprint='source-bytes',
                      configuration_fingerprint='config', model_fingerprint='model', case_fingerprint='case',
                      execution_kind='native', status='completed', metrics={'tool_call_count': 2,
                          'human_reminder_count': 0, 'input_tokens': 50, 'output_tokens': 5,
                          'cost_usd': None, 'reply_latency_seconds': None})
        runs = [dict(common, arm='primitive', native_success=False, correct_route=True, answer_used=False),
                dict(common, arm='composite', native_success=True, correct_route=True, answer_used=True)]
        report = self.runner.summarize_runs(runs)
        self.assertEqual(report['arms']['primitive']['native_successes'], 0)
        self.assertEqual(report['arms']['composite']['native_successes'], 1)
        self.assertEqual(report['arms']['primitive']['attempts'], 1)
        self.assertIsNone(report['arms']['composite']['cost_usd'])
        self.assertEqual(report['paired']['comparable_pairs'], 1)
        self.assertFalse(report['independent_user_acceptance'])
        runs[1]['configuration_fingerprint'] = 'different'
        self.assertEqual(self.runner.summarize_runs(runs)['paired']['comparable_pairs'], 0)
        runs[1]['configuration_fingerprint'] = 'config'
        runs[1]['source_content_fingerprint'] = 'modified-dirty-source'
        self.assertEqual(self.runner.summarize_runs(runs)['paired']['comparable_pairs'], 0)

    def test_incomplete_native_run_does_not_complete_the_gate(self):
        report = self.runner.summarize_runs([dict(pair_id='p', arm='composite', scenario_id='frontend-backend',
            execution_kind='native', status='timeout', native_success=False, metrics={})])
        self.assertFalse(report['foundation_1_complete'])
        self.assertEqual(report['arms']['composite']['incomplete_attempts'], 1)

    def test_linked_native_format_exchange_requires_ordered_source_read_and_later_artifact(self):
        request = {'id': 1, 'sender_member_id': 'front', 'receiver_member_id': 'back', 'context_version': 1,
                   'replies': [{'id': 2, 'request_id': 1, 'author_member_id': 'back', 'body': 'profile_secret'}]}
        def turn(role, calls):
            return dict(role=role, execution_kind='native', trace={'tool_calls': [dict(call, is_error=False) for call in calls]})
        turns = [turn('requester', [dict(name='send_request', at=10, result=dict(request, replies=[]))]),
                 turn('responder', [dict(name='Read', at=12, arguments={'file_path': 'backend/schema.json'},
                                         result='profile_secret'), dict(name='reply', at=15, result=request)]),
                 turn('requester', [dict(name='read_team', at=18, result={'requests': [request]})])]
        kwargs = dict(expected_field='profile_secret', requester='front', responder='back', turns=turns,
                      requests=[request], before={'payload_correct': False}, after={'artifact_correct': True})
        result = self.runner.audit_exchange(**kwargs)
        self.assertTrue(result['native_success'])
        self.assertEqual(result['reply_latency_seconds'], 5)
        turns[0]['trace']['tool_calls'].append(dict(name='command_execution', at=11,
            is_error=False, arguments={'command': 'Read another participant'}, result='profile_secret'))
        self.assertFalse(self.runner.audit_exchange(**kwargs)['native_success'])
        turns[0]['trace']['tool_calls'].pop()
        turns[1]['trace']['tool_calls'][0]['at'] = 20
        self.assertFalse(self.runner.audit_exchange(**kwargs)['native_success'])

    def test_case_execution_is_real_adapter_and_preserves_incomplete_results(self):
        from types import SimpleNamespace
        args = SimpleNamespace(requester='codex', responder='codex', codex='codex', claude='claude', timeout=10)
        with patch('workflow_native_process.prepare_native', return_value={'harness': 'codex', 'run_dir': str(self.root)}), \
             patch('workflow_native_process.run_turn', return_value={'exit_code': 1, 'timed_out': False,
                 'events': [], 'started_at': 10, 'finished_at': 11,
                 'event_path': str(self.root / 'absent.jsonl'), 'stderr_path': str(self.root / 'absent.log')}):
            result = self.runner.run_case(self.root, 'frontend-backend', 'primitive', 'same-seed', 'pair', args)
        self.assertNotEqual(result['status'], 'completed')
        self.assertFalse(result['native_success'])
        self.assertTrue((self.root / 'result.json').exists())
        self.assertEqual(len(list((self.root / 'turns').glob('*.json'))), 1)

    def test_normal_schedule_starts_responder_while_requester_is_still_working(self):
        question, answered = threading.Event(), threading.Event()
        observed = []
        def execute(role, stage='initial', **kwargs):
            observed.append((role, stage))
            if role == 'requester' and stage == 'initial':
                question.set()
                return answered.wait(2)
            if role == 'responder':
                self.assertTrue(question.is_set())
                answered.set()
            return True
        result = self.runner.schedule_case('frontend-backend', execute,
            lambda: {'outstanding_request_ids': [1] if question.is_set() else [],
                     'independent_work_correct': True}, lambda: True, ('requester', 'responder'), 3)
        self.assertTrue(result['healthy'])
        self.assertEqual(observed, [('requester', 'initial'), ('responder', 'initial')])

    def test_reopen_closes_old_worker_before_starting_fresh_conversation(self):
        closed, fresh = threading.Event(), threading.Event()
        def execute(role, stage='initial', cancel_event=None, **kwargs):
            if role == 'requester' and stage == 'initial':
                self.assertTrue(cancel_event.wait(2))
                closed.set()
            elif role == 'responder':
                self.assertTrue(closed.is_set())
            elif role == 'requester' and stage == 'reopen':
                self.assertTrue(closed.is_set())
                self.assertTrue(kwargs['fresh'])
                fresh.set()
            return True
        result = self.runner.schedule_case('session-reopen', execute,
            lambda: {'outstanding_request_ids': [1], 'independent_work_correct': True},
            lambda: fresh.is_set(), ('requester', 'responder'), 3)
        self.assertTrue(result['healthy'])
        self.assertTrue(fresh.is_set())


if __name__ == '__main__':
    unittest.main()
