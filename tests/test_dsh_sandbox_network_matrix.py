import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments' / 'agent-integration'))
from dsh_sandbox.network_matrix import CASES, score_network_observation


class NetworkMatrixTests(unittest.TestCase):
    def observation(self, case_id, **overrides):
        base = {
            'schema_version': 1,
            'case_id': case_id,
            'source': 'native',
            'evidence_ref': 'private:runtime',
            'agent_nat_alias': 'nat-agent-1',
            'owner_nat_alias': 'nat-owner-1',
            'owner_service_observed': True,
            'business_route': 'member-bridge-p2p',
            'selected_path': 'direct',
            'cursor_gap_count': 0,
            'duplicate_event_count': 0,
            'revoked_credential_accepted': False,
        }
        base.update(overrides)
        return base

    def test_declares_deterministic_path_and_recovery_cases(self):
        self.assertEqual(set(CASES), {
            'direct', 'relay-only', 'udp-blocked', 'nat-mapping-change',
            'member-restart', 'owner-restart',
        })

    def test_direct_and_relay_require_runtime_selected_path(self):
        direct = score_network_observation(self.observation('direct'))
        relay = score_network_observation(self.observation('relay-only', selected_path='relay'))
        self.assertTrue(direct['passed'])
        self.assertTrue(relay['passed'])
        self.assertEqual(direct['observed_path'], 'direct')

    def test_configuration_or_owner_claim_cannot_substitute_for_runtime_observation(self):
        for observation in (
            self.observation('direct', source='fixture'),
            self.observation('direct', selected_path='relay'),
            self.observation('direct', evidence_ref=''),
            self.observation('direct', agent_nat_alias='nat-owner-1'),
            self.observation('direct', business_route='control-plane-proxy'),
            self.observation('direct', owner_service_observed=False),
        ):
            with self.subTest(observation=observation):
                self.assertFalse(score_network_observation(observation)['passed'])

    def test_udp_blocked_is_negative_control_and_must_be_unreachable(self):
        self.assertTrue(score_network_observation(self.observation(
            'udp-blocked', selected_path='unreachable'))['passed'])
        self.assertFalse(score_network_observation(self.observation(
            'udp-blocked', selected_path='direct'))['passed'])

    def test_recovery_requires_gap_free_cursor_no_duplicates_and_revocation(self):
        self.assertTrue(score_network_observation(self.observation(
            'member-restart', selected_path='relay', resumed_cursor=42))['passed'])
        for overrides in ({'cursor_gap_count': 1}, {'duplicate_event_count': 1},
                          {'revoked_credential_accepted': True}, {'resumed_cursor': -1}):
            with self.subTest(overrides=overrides):
                observation = self.observation('member-restart', selected_path='relay', resumed_cursor=42)
                observation.update(overrides)
                self.assertFalse(score_network_observation(observation)['passed'])

    def test_invalid_shapes_do_not_echo_private_observation(self):
        observation = self.observation('direct', prompt='must-not-appear')
        result = score_network_observation(observation)
        self.assertNotIn('prompt', result)
        with self.assertRaises(ValueError):
            score_network_observation({'case_id': 'unknown', 'prompt': 'secret'})


if __name__ == '__main__':
    unittest.main()
