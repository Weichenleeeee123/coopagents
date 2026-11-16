import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'agent-integration'))

from dsh_sandbox.scoring import score_report


def attempt(arm='coopagents', **updates):
    value = {
        'attempt_id': 'run-1', 'arm': arm, 'status': 'completed',
        'evidence_classification': 'native_observations_unverified',
        'route': {'source': 'native', 'expected_revision': 2, 'used_revision': 2, 'owner_match': True,
                  'evidence_hash': 'a' * 64},
        'answer': {'source': 'native', 'request_hash': 'b' * 64, 'reply_request_hash': 'b' * 64,
                   'reply_hash': 'c' * 64, 'consumed_reply_hash': 'c' * 64,
                   'artifact_hash': 'd' * 64},
        'hidden_test': {'source': 'hidden_test_runner', 'status': 'passed',
                        'category': 'functional', 'output_hash': 'e' * 64},
        'human_gate': {'required': False, 'authorized': None, 'actor_source': None},
        'cost_usd': None, 'usage': None,
    }
    value.update(updates)
    return value


class SandboxScoringTests(unittest.TestCase):
    def test_all_attempts_are_denominators_and_missing_cost_stays_null(self):
        result = score_report([attempt(), attempt('control', status='startup_failed',
                                                  route=None, answer=None, hidden_test=None)])
        arm = result['arms']['control']
        self.assertEqual(arm['attempts'], 1)
        self.assertEqual(arm['metrics']['hidden_test_success']['denominator'], 1)
        self.assertEqual(arm['metrics']['hidden_test_success']['numerator'], 0)
        self.assertIsNone(result['arms']['coopagents']['cost_usd_total'])
        self.assertIsNone(result['arms']['coopagents']['usage_totals'])

    def test_stale_route_and_mismatched_request_reply_do_not_score(self):
        stale = attempt(route={'source': 'native', 'expected_revision': 3, 'used_revision': 2,
                               'owner_match': True, 'evidence_hash': 'a' * 64})
        mismatch = attempt(answer={'source': 'native', 'request_hash': 'b' * 64, 'reply_request_hash': 'f' * 64,
                                   'reply_hash': 'c' * 64, 'consumed_reply_hash': 'c' * 64,
                                   'artifact_hash': 'd' * 64})
        stale_metrics = score_report([stale])['arms']['coopagents']['metrics']
        mismatch_metrics = score_report([mismatch])['arms']['coopagents']['metrics']
        self.assertEqual(stale_metrics['route_success']['numerator'], 0)
        self.assertEqual(mismatch_metrics['answer_use']['numerator'], 0)

    def test_unauthorized_human_decision_fails_route_and_answer_metric_not_hidden_test(self):
        item = attempt(human_gate={'required': True, 'authorized': False,
                                   'actor_source': 'agent'})
        metrics = score_report([item])['arms']['coopagents']['metrics']
        self.assertEqual(metrics['hidden_test_success']['numerator'], 1)
        self.assertEqual(metrics['route_success']['numerator'], 0)

    def test_hidden_output_and_oracle_marker_are_never_projected(self):
        item = attempt(hidden_test={'source': 'hidden_test_runner', 'status': 'failed', 'category': 'schema_mismatch',
                                    'output_hash': '1' * 64,
                                    'content': 'ORACLE_SECRET random schema marker'})
        report = repr(score_report([item]))
        self.assertNotIn('ORACLE_SECRET', report)
        self.assertNotIn('random schema marker', report)
        self.assertIn('schema_mismatch', report)

    def test_harness_only_never_becomes_native_success_or_user_acceptance(self):
        item = attempt(evidence_classification='harness_only',
                       independent_user_acceptance=True)
        result = score_report([item])
        self.assertEqual(result['arms']['coopagents']['native_success']['numerator'], 0)
        self.assertEqual(result['independent_user_acceptance']['numerator'], 0)

    def test_harness_source_cannot_claim_native_success(self):
        item = attempt(route={'source': 'harness', 'expected_revision': 2, 'used_revision': 2,
                              'owner_match': True, 'evidence_hash': 'a' * 64})
        self.assertEqual(score_report([item])['arms']['coopagents']['native_success']['numerator'], 0)

    def test_invalid_arm_and_non_hash_evidence_are_rejected(self):
        with self.assertRaises(ValueError):
            score_report([attempt(arm='treatment')])
        bad = attempt(route={'source': 'native', 'expected_revision': 1, 'used_revision': 1,
                             'owner_match': True, 'evidence_hash': 'not-a-hash'})
        with self.assertRaises(ValueError):
            score_report([bad])


if __name__ == '__main__':
    unittest.main()
