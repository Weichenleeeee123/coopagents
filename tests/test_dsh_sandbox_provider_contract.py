import importlib.util
from pathlib import Path
import unittest


MODULE = (Path(__file__).resolve().parents[1] / 'experiments' / 'agent-integration'
          / 'dsh_sandbox' / 'provider_contract.py')
SPEC = importlib.util.spec_from_file_location('dsh_sandbox_provider_contract', MODULE)
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def valid_inventory():
    return {
        'run_id': 'run-synthetic-001',
        'agents': [
            {
                'agent_id': f'agent-{i}',
                'egress_network_id': f'nat-{i}',
                'public_ip': f'198.51.100.{i}',
                'subnet_id': f'subnet-{i}',
                'inbound_ports': [],
                'public_control_endpoint': False,
                'network_profile': 'direct',
                'network_policy': {'peer_udp': True, 'relay_udp': True},
                'lifecycle': {
                    'state': 'running', 'created_at': '2026-11-17T00:00:00Z',
                    'expires_at': '2026-11-17T06:00:00Z', 'run_id': 'run-synthetic-001',
                    'instance_id': f'instance-{i}',
                    'deallocation': {'run_id': 'run-synthetic-001', 'mode': 'stop',
                                     'preserve_disks': True, 'preserve_snapshots': True,
                                     'preserve_evidence': True, 'preview_required': True},
                },
                'snapshot': {
                    'snapshot_id': f'snapshot-{i}', 'created_at': '2026-11-16T00:00:00Z',
                    'source_image_id': 'agent-image-v1', 'image_digest': 'sha256:fixture',
                },
            }
            for i in range(1, 4)
        ],
    }


class DshSandboxProviderContractTests(unittest.TestCase):
    def test_accepts_isolated_agents_with_complete_lifecycle_evidence(self):
        self.assertEqual(contract.validate_inventory(valid_inventory()), [])

    def test_rejects_duplicate_egress_networks_public_ips_and_agent_subnets(self):
        inventory = valid_inventory()
        inventory['agents'][1]['egress_network_id'] = inventory['agents'][0]['egress_network_id']
        inventory['agents'][1]['public_ip'] = inventory['agents'][0]['public_ip']
        inventory['agents'][1]['subnet_id'] = inventory['agents'][0]['subnet_id']

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('egress_network_id' in error for error in errors))
        self.assertTrue(any('public_ip' in error for error in errors))
        self.assertTrue(any('subnet_id' in error for error in errors))

    def test_rejects_public_admin_ports_and_public_control_endpoints(self):
        inventory = valid_inventory()
        inventory['agents'][0]['inbound_ports'] = [22, 3389, 443]
        inventory['agents'][1]['public_control_endpoint'] = True

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('inbound' in error.lower() for error in errors))
        self.assertTrue(any('control' in error.lower() for error in errors))

    def test_requires_lifecycle_and_snapshot_metadata(self):
        inventory = valid_inventory()
        del inventory['agents'][0]['lifecycle']['expires_at']
        del inventory['agents'][1]['snapshot']['image_digest']

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('expires_at' in error for error in errors))
        self.assertTrue(any('image_digest' in error for error in errors))

    def test_accepts_direct_relay_only_and_udp_blocked_profiles(self):
        inventory = valid_inventory()
        inventory['agents'][1]['network_profile'] = 'relay-only'
        inventory['agents'][1]['network_policy'] = {'peer_udp': False, 'relay_udp': True}
        inventory['agents'][2]['network_profile'] = 'udp-blocked'
        inventory['agents'][2]['network_policy'] = {'peer_udp': False, 'relay_udp': False}

        self.assertEqual(contract.validate_inventory(inventory), [])

    def test_rejects_profile_policy_mismatch_and_unknown_profile(self):
        inventory = valid_inventory()
        inventory['agents'][0]['network_policy']['peer_udp'] = False
        inventory['agents'][1]['network_profile'] = 'permissive'

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('profile' in error.lower() for error in errors))

    def test_requires_three_agents_nonempty_identity_and_complete_isolation_evidence(self):
        inventory = valid_inventory()
        inventory['agents'] = inventory['agents'][:2]
        inventory['agents'][0]['agent_id'] = ''
        del inventory['agents'][1]['public_control_endpoint']

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('three' in error for error in errors))
        self.assertTrue(any('agent_id' in error for error in errors))
        self.assertTrue(any('public_control_endpoint' in error for error in errors))

    def test_requires_exact_run_bound_preserving_deallocation(self):
        inventory = valid_inventory()
        action = inventory['agents'][0]['lifecycle']['deallocation']
        action['run_id'] = 'other-run'
        action['mode'] = 'destroy'
        action['preserve_disks'] = False

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('deallocation.run_id' in error for error in errors))
        self.assertTrue(any('deallocation.mode' in error for error in errors))
        self.assertTrue(any('preserve_disks' in error for error in errors))

    def test_rejects_malformed_inputs_without_echoing_values(self):
        sentinel = 'private-secret-sentinel'
        for inventory in (None, [], {'run_id': sentinel, 'agents': [sentinel]},
                          {'run_id': sentinel, 'agents': 'not-an-array'}):
            with self.subTest(inventory=type(inventory).__name__):
                errors = contract.validate_inventory(inventory)
                self.assertTrue(errors)
                self.assertNotIn(sentinel, '\n'.join(errors))

    def test_rejects_invalid_public_ip_and_metadata_timestamps(self):
        inventory = valid_inventory()
        inventory['agents'][0]['public_ip'] = 'not-an-ip'
        inventory['agents'][1]['lifecycle']['expires_at'] = 'yesterday'
        inventory['agents'][2]['snapshot']['created_at'] = 'unknown'

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('public_ip' in error for error in errors))
        self.assertTrue(any('expires_at' in error for error in errors))
        self.assertTrue(any('created_at' in error for error in errors))

    def test_rejects_duplicate_agents_and_lifecycle_run_mismatch(self):
        inventory = valid_inventory()
        inventory['agents'][1]['agent_id'] = inventory['agents'][0]['agent_id']
        inventory['agents'][2]['lifecycle']['run_id'] = 'old-run'

        errors = contract.validate_inventory(inventory)

        self.assertTrue(any('agent_id' in error for error in errors))
        self.assertTrue(any('lifecycle.run_id' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
