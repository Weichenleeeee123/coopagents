"""Tool-free goals and conservative scoring of supplied normalized evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4


MODULE_PATH = Path(__file__).with_name('workflow_evaluation.py')


def exchange(kind='native'):
    return {
        'schema_version': 1, 'kind': kind, 'scenario_id': 'frontend-backend',
        'expected': {'requester_member_id': 'front', 'responder_member_id': 'back', 'route_revision': 2},
        'participants': [
            {'member_id': 'front', 'human_id': 'person-1', 'device_id': 'device-1',
             'session_id': 'native-1', 'network_id': 'network-1', 'evidence_ref': 'private:provenance-front'},
            {'member_id': 'back', 'human_id': 'person-2', 'device_id': 'device-2',
             'session_id': 'native-2', 'network_id': 'network-2', 'evidence_ref': 'private:provenance-back'}],
        'records': [
            {'kind': 'request', 'request_id': 'q1', 'actor': 'front', 'recipient': 'back',
             'route_revision': 2, 'source': kind, 'evidence_ref': 'private:request', 'at': 10},
            {'kind': 'model_reply', 'request_id': 'q1', 'reply_id': 'r1', 'actor': 'back', 'recipient': 'front',
             'route_revision': 2, 'source': kind, 'evidence_ref': 'private:native-turn',
             'file_evidence_ref': 'private:source-file-and-observation', 'at': 15},
            {'kind': 'requester_consumption', 'request_id': 'q1', 'reply_id': 'r1', 'actor': 'front',
             'route_revision': 2, 'source': kind, 'evidence_ref': 'private:requester-turn',
             'observed_effect': 'The requester used the returned field name in its implementation.', 'at': 18},
        ],
    }


class WorkflowEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE_PATH.exists(), 'a tool-independent workflow evaluator is required')
        spec = importlib.util.spec_from_file_location('workflow_evaluation', MODULE_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_scenario_goals_are_tool_free_and_cover_the_five_workflows(self):
        scenarios = self.module.scenarios()
        self.assertEqual({s['id'] for s in scenarios}, {
            'frontend-backend', 'three-member-routing', 'offline-reopen', 'agreement-change', 'human-decision'})
        forbidden = ('checkpoint', 'read_team', 'send_request', 'read_replies', 'read_inbox',
                     'ask_owner', 'lookup_owner', 'read_dependency', 'record_agreement_use', 'work_brief')
        for scenario in scenarios:
            self.assertTrue(scenario['goal'])
            for name in forbidden:
                self.assertNotIn(name, scenario['goal'])
        self.assertNotIn('then call', json.dumps(scenarios).lower())

    def test_missing_evidence_stays_unverified_and_metrics_unknown(self):
        result = self.module.score_evidence({'schema_version': 1, 'kind': 'native',
                                              'scenario_id': 'frontend-backend'})
        self.assertEqual(result['checks']['model_reply'], 'unverified')
        self.assertEqual(result['checks']['requester_consumption'], 'unverified')
        self.assertEqual(result['checks']['scenario_outcome'], 'unverified')
        self.assertFalse(result['native_success'])
        self.assertIsNone(result['metrics']['tool_call_count'])
        self.assertIsNone(result['metrics']['human_reminder_count'])
        self.assertIsNone(result['metrics']['reply_latency_seconds'])

    def test_preparation_separates_participant_goals_and_private_evidence_files(self):
        for scenario in self.module.scenarios():
            participants = scenario.get('participants', [])
            self.assertEqual(len(participants), scenario['people'])
            self.assertEqual(len({p['evidence_file'] for p in participants}), scenario['people'])
            self.assertEqual(len({p['role'] for p in participants}), scenario['people'])
            for participant in participants:
                self.assertTrue(participant['goal'])
                self.assertNotIn('send_request', participant['goal'])
                self.assertNotIn('read_team', participant['goal'])

    def test_independent_acceptance_requires_distinct_referenced_networks(self):
        evidence = exchange()
        evidence['records'] += [dict(kind='human_acceptance', source='human', evidence_ref='private:accepted',
            human_id=p['human_id']) for p in evidence['participants']]
        for value in (None, 'same-network'):
            for participant in evidence['participants']:
                if value is None:
                    participant.pop('network_id', None)
                else:
                    participant['network_id'] = value
            self.assertFalse(self.module.score_evidence(evidence)['independent_user_acceptance'])

    def test_protocol_owner_change_invalidates_an_older_native_exchange(self):
        evidence = exchange()
        evidence['records'].append(dict(kind='route_change', source='protocol', evidence_ref='private:owner-change',
            route_revision=3, responder_member_id='new-owner'))
        result = self.module.score_evidence(evidence)
        self.assertEqual(result['checks']['current_route'], 'failed')
        self.assertFalse(result['native_success'])

    def test_boolean_observation_revisions_cannot_equal_integer_route_one(self):
        evidence = exchange()
        evidence['expected']['route_revision'] = 1
        for record in evidence['records']:
            record['route_revision'] = True
        result = self.module.score_evidence(evidence)
        self.assertEqual(result['checks']['current_route'], 'failed')
        self.assertFalse(result['native_success'])

    def test_actual_file_derived_model_reply_and_requester_effect_are_separate(self):
        evidence = exchange()
        result = self.module.score_evidence(evidence)
        self.assertTrue(result['native_success'])
        self.assertEqual(result['checks']['model_reply'], 'verified')
        self.assertEqual(result['checks']['requester_consumption'], 'verified')
        evidence['records'][1].pop('file_evidence_ref')
        self.assertFalse(self.module.score_evidence(evidence)['native_success'])

    def test_receipt_cannot_invent_model_consumption(self):
        evidence = exchange()
        evidence['records'][2] = {'kind': 'read_receipt', 'actor': 'front', 'reply_id': 'r1',
                                  'source': 'native', 'evidence_ref': 'private:receipt', 'at': 18}
        result = self.module.score_evidence(evidence)
        self.assertEqual(result['checks']['requester_consumption'], 'unverified')
        self.assertFalse(result['native_success'])

    def test_protocol_and_fixture_results_cannot_claim_native_acceptance(self):
        for kind in ('fixture', 'protocol'):
            evidence = exchange(kind)
            evidence['records'].append({'kind': kind + '_result', 'passed': True,
                                         'source': kind, 'evidence_ref': 'private:check'})
            result = self.module.score_evidence(evidence)
            self.assertEqual(result['checks'][kind], 'verified')
            self.assertFalse(result['native_success'])
            self.assertFalse(result['independent_user_acceptance'])

    def test_wrong_or_missing_sender_and_recipient_fail_identity_checks(self):
        for record_index, field in ((0, 'actor'), (0, 'recipient'), (1, 'actor'), (1, 'recipient'), (2, 'actor')):
            for wrong in (None, 'someone-else'):
                evidence = exchange()
                evidence['records'][record_index][field] = wrong
                result = self.module.score_evidence(evidence)
                with self.subTest(record_index=record_index, field=field, wrong=wrong):
                    self.assertEqual(result['checks']['identity'], 'failed')
                    self.assertFalse(result['native_success'])

    def test_stale_reply_route_and_wrong_reply_link_do_not_succeed(self):
        for index, field, value in ((1, 'route_revision', 1), (2, 'route_revision', 1),
                                    (1, 'request_id', 'other'), (2, 'reply_id', 'other')):
            evidence = exchange()
            evidence['records'][index][field] = value
            self.assertFalse(self.module.score_evidence(evidence)['native_success'])
        evidence = exchange()
        evidence['records'].append({'kind': 'route_change', 'route_revision': 3,
                                    'responder_member_id': 'third', 'source': 'native',
                                    'evidence_ref': 'private:new-owner'})
        self.assertEqual(self.module.score_evidence(evidence)['checks']['current_route'], 'failed')

    def test_one_old_exchange_cannot_mask_a_later_wrong_sender(self):
        evidence = exchange()
        evidence['records'].append({**evidence['records'][1], 'actor': 'wrong', 'reply_id': 'r2', 'at': 20})
        self.assertFalse(self.module.score_evidence(evidence)['native_success'])

    def test_independent_humans_devices_and_acceptance_need_explicit_provenance(self):
        evidence = exchange()
        result = self.module.score_evidence(evidence)
        self.assertEqual(result['checks']['independent_provenance'], 'verified')
        self.assertFalse(result['independent_user_acceptance'])
        for participant in evidence['participants']:
            evidence['records'].append({'kind': 'human_acceptance', 'human_id': participant['human_id'],
                                         'source': 'human', 'evidence_ref': 'private:approval-' + participant['human_id']})
        self.assertTrue(self.module.score_evidence(evidence)['independent_user_acceptance'])
        for field in ('human_id', 'device_id', 'session_id'):
            duplicate = copy.deepcopy(evidence)
            duplicate['participants'][1][field] = duplicate['participants'][0][field]
            self.assertFalse(self.module.score_evidence(duplicate)['independent_user_acceptance'])

    def test_explicit_metrics_are_reported_without_upgrading_correctness(self):
        evidence = exchange('fixture')
        evidence['records'] += [
            {'kind': 'tool_call', 'evidence_ref': 'private:call-1'},
            {'kind': 'tool_call', 'evidence_ref': 'private:call-2'},
            {'kind': 'human_reminder', 'evidence_ref': 'private:reminder'}]
        evidence['metrics_complete'] = ['tool_call_count', 'human_reminder_count']
        result = self.module.score_evidence(evidence)
        self.assertEqual(result['metrics'], {'tool_call_count': 2, 'human_reminder_count': 1,
                                             'reply_latency_seconds': 5, 'consumption_latency_seconds': 3})
        self.assertFalse(result['native_success'])

    def test_human_decision_needs_current_real_user_instruction(self):
        evidence = exchange()
        evidence['scenario_id'] = 'human-decision'
        self.assertFalse(self.module.score_evidence(evidence)['native_success'])
        evidence['records'].append({'kind': 'human_decision', 'source': 'human', 'evidence_ref': 'private:applied',
                                     'actual_user_instruction_ref': 'private:current-instruction', 'current': True})
        self.assertTrue(self.module.score_evidence(evidence)['native_success'])

    def test_scenario_specific_recovery_and_agreement_observations_are_required(self):
        for scenario, kind, extra in (
                ('offline-reopen', 'recovery', {'outstanding_work_recovered': True,
                                               'prior_session_id': 'old-session', 'resumed_session_id': 'native-1'}),
                ('agreement-change', 'agreement_review', {'previous_version': 1, 'current_version': 2,
                                                          'used_version': 2, 'current_approved': True}),
                ('three-member-routing', 'owner_route', {'current_owner': 'back', 'bystander_member_id': 'third',
                                                        'bystander_not_addressed': True})):
            evidence = exchange()
            evidence['scenario_id'] = scenario
            if scenario == 'three-member-routing':
                evidence['participants'].append({'member_id': 'third', 'evidence_ref': 'private:bystander'})
            self.assertFalse(self.module.score_evidence(evidence)['native_success'])
            evidence['records'].append({'kind': kind, 'source': 'native', 'evidence_ref': 'private:observation', **extra})
            self.assertTrue(self.module.score_evidence(evidence)['native_success'])

    def test_unchanged_unapproved_agreement_or_same_session_cannot_pass_recovery_goals(self):
        evidence = exchange()
        evidence['scenario_id'] = 'agreement-change'
        evidence['records'].append({'kind': 'agreement_review', 'source': 'native', 'evidence_ref': 'private:review',
                                     'previous_version': 1, 'current_version': 1, 'used_version': 1,
                                     'current_approved': True})
        self.assertFalse(self.module.score_evidence(evidence)['native_success'])
        evidence['records'][-1].update(current_version=2, used_version=2, current_approved=False)
        self.assertFalse(self.module.score_evidence(evidence)['native_success'])
        evidence['scenario_id'] = 'offline-reopen'
        evidence['records'].append({'kind': 'recovery', 'source': 'native', 'evidence_ref': 'private:recovery',
                                     'prior_session_id': 'same', 'resumed_session_id': 'same',
                                     'outstanding_work_recovered': True})
        self.assertFalse(self.module.score_evidence(evidence)['native_success'])

    def test_invalid_schema_is_rejected_and_missing_native_reference_cannot_pass(self):
        for data in ({}, {**exchange(), 'schema_version': True}, {**exchange(), 'kind': 'simulation'},
                     {**exchange(), 'records': ['raw log']}, {**exchange(), 'scenario_id': 'unknown'}):
            with self.assertRaises(ValueError):
                self.module.score_evidence(data)
        for index in (0, 1, 2):
            evidence = exchange()
            evidence['records'][index].pop('evidence_ref')
            self.assertFalse(self.module.score_evidence(evidence)['native_success'])

    def test_unrelated_or_unreferenced_timestamps_do_not_supply_latency(self):
        for field, value in (('request_id', 'another'), ('evidence_ref', '')):
            evidence = exchange()
            evidence['records'][1][field] = value
            self.assertIsNone(self.module.score_evidence(evidence)['metrics']['reply_latency_seconds'])

    def test_cli_only_prepares_goals_or_scores_private_supplied_evidence(self):
        prepared = subprocess.run([sys.executable, str(MODULE_PATH), 'prepare'], check=True,
                                  capture_output=True, text=True)
        self.assertEqual(len(json.loads(prepared.stdout)['scenarios']), 5)
        path = Path('.local/test-evidence') / uuid4().hex / 'normalized.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(exchange('fixture')), encoding='utf-8')
        scored = subprocess.run([sys.executable, str(MODULE_PATH), 'score', str(path)], check=True,
                               capture_output=True, text=True)
        self.assertFalse(json.loads(scored.stdout)['native_success'])


if __name__ == '__main__':
    unittest.main()
