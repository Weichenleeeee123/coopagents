import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'agent-integration'))

from dsh_sandbox.manifest import validate_manifest


class RunManifestTests(unittest.TestCase):
    def manifest(self):
        return {
            'schema_version': 1,
            'run_id': 'run-123',
            'source_commit': 'a' * 40,
            'dsh_version': '1.2.3',
            'os_image': 'agent-image-7',
            'model_config_fingerprint': 'f' * 64,
            'scenario_seed': 'seed-123',
            'arm_order': ['control', 'coopagents'],
            'cost_limit_usd': 5.0,
            'timeout_seconds': 600,
            'roles': {
                'frontend': {'member_alias': 'member-a', 'vm_alias': 'vm-a', 'nat_alias': 'nat-a'},
                'backend': {'member_alias': 'member-b', 'vm_alias': 'vm-b', 'nat_alias': 'nat-b'},
                'integration': {'member_alias': 'member-c', 'vm_alias': 'vm-c', 'nat_alias': 'nat-c'},
            },
        }

    def test_accepts_three_distinct_members_vms_and_nat_egresses(self):
        validated = validate_manifest(self.manifest())
        self.assertEqual(validated['schema_version'], 1)
        self.assertEqual(validated['region'], 'ap-southeast-1')

    def test_rejects_duplicate_member_vm_or_nat_identity(self):
        for field in ('member_alias', 'vm_alias', 'nat_alias'):
            with self.subTest(field=field):
                manifest = self.manifest()
                manifest['roles']['backend'][field] = manifest['roles']['frontend'][field]
                with self.assertRaisesRegex(ValueError, 'distinct'):
                    validate_manifest(manifest)

    def test_rejects_missing_roles_or_incomplete_run_identity(self):
        manifest = self.manifest()
        del manifest['roles']['integration']
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_rejects_model_mismatch_and_bad_budgets(self):
        for field, value in (('model_config_fingerprint', ''), ('cost_limit_usd', 0),
                             ('timeout_seconds', True), ('arm_order', ['control', 'control'])):
            with self.subTest(field=field):
                manifest = self.manifest()
                manifest[field] = value
                with self.assertRaises(ValueError):
                    validate_manifest(manifest)


if __name__ == '__main__':
    unittest.main()
