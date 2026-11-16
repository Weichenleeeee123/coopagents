import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'agent-integration'))

from dsh_sandbox.scenario_state import ScenarioState


class ScenarioStateTests(unittest.TestCase):
    def test_requires_ordered_native_evidence_for_transitions(self):
        state = ScenarioState('frontend-backend')
        with self.assertRaisesRegex(ValueError, 'native'):
            state.observe('question_created', source='fixture', evidence_ref='e-1', request_id='r-1')
        state.observe('question_created', source='native', evidence_ref='e-1', request_id='r-1')
        state.observe('reply_created', source='native', evidence_ref='e-2', request_id='r-1', reply_id='rp-1')
        with self.assertRaisesRegex(ValueError, 'request'):
            state.observe('answer_consumed', source='native', evidence_ref='e-3', request_id='r-2', reply_id='rp-1')
        state.observe('answer_consumed', source='native', evidence_ref='e-3', request_id='r-1', reply_id='rp-1')
        self.assertTrue(state.complete)

    def test_human_gate_needs_external_operator_decision(self):
        state = ScenarioState('human-decision')
        state.observe('decision_presented', source='native', evidence_ref='agent-card')
        with self.assertRaisesRegex(ValueError, 'operator'):
            state.observe('decision_applied', source='native', evidence_ref='agent-action', decision='approve')
        state.observe('operator_decision', source='human', evidence_ref='operator-record', decision='approve', actor_alias='operator-1')
        state.observe('decision_applied', source='native', evidence_ref='agent-action', decision='approve')
        self.assertTrue(state.complete)

    def test_duplicate_or_unlinked_events_are_rejected(self):
        state = ScenarioState('frontend-backend')
        with self.assertRaises(ValueError):
            state.observe('reply_created', source='native', evidence_ref='e-1', request_id='r-1', reply_id='rp-1')
        state.observe('question_created', source='native', evidence_ref='e-1', request_id='r-1')
        with self.assertRaises(ValueError):
            state.observe('question_created', source='native', evidence_ref='e-2', request_id='r-2')

    def test_events_are_returned_without_sensitive_payload_fields(self):
        state = ScenarioState('frontend-backend')
        state.observe('question_created', source='native', evidence_ref='private:q', request_id='r-1', prompt='secret')
        self.assertNotIn('prompt', state.export()['events'][0])


if __name__ == '__main__':
    unittest.main()
