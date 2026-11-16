"""Harness-only tests for the provider-neutral DSH scenario coordinator."""
import asyncio
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / 'experiments' / 'agent-integration' / 'dsh_sandbox'
sys.path.insert(0, str(SANDBOX))

import runner


def manifest():
    return {
        'schema_version': 1, 'run_id': 'run-123', 'source_commit': 'a' * 40,
        'dsh_version': '0.2.2-rc1', 'os_image': 'test-image-1',
        'model_config_fingerprint': 'f' * 64, 'scenario_seed': 'paired-seed',
        'arm_order': ['control', 'coopagents'], 'cost_limit_usd': 5.0,
        'timeout_seconds': 30,
        'roles': {
            role: {'member_alias': f'm-{role}', 'vm_alias': f'v-{role}', 'nat_alias': f'n-{role}'}
            for role in ('frontend', 'backend', 'integration')
        },
    }


class FakeCloud:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.calls = []

    async def trigger(self, *, arm, scenario_id, transition, timeout_seconds, run_id):
        self.calls.append((arm, scenario_id, transition, timeout_seconds))
        if transition == self.fail_at:
            return {'status': 'failed', 'source': 'fixture', 'evidence_ref': 'fake:failure'}
        return {'status': 'observed', 'source': 'fixture', 'evidence_ref': 'fake:' + transition}


class FakeDsh:
    def __init__(self, cost=0.1):
        self.calls = []
        self.cost = cost

    async def run_turn(self, *, arm, role, prompt, session_id, fresh_session,
                       workspace, timeout_seconds, budget_remaining_usd):
        self.calls.append((arm, role, session_id, fresh_session, workspace, timeout_seconds))
        return {'status': 'completed', 'source': 'fixture', 'evidence_ref': 'fake:turn',
                'session_id': session_id, 'cost_usd': self.cost}


class FakeOperator:
    async def decide(self, *, run_id, arm, scenario_id, decision_prompt, timeout_seconds):
        return {'status': 'decided', 'source': 'human', 'evidence_ref': 'fake:operator',
                'decision': 'approve', 'actor_alias': 'operator-test'}


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def output_root(self):
        root = ROOT / '.local' / 'ds' / uuid4().hex[:8]
        root.mkdir(parents=True, exist_ok=False)
        return root

    async def test_runs_randomized_paired_arms_with_identical_fixture_seed_and_fresh_workspaces(self):
        root = self.output_root()
        cloud, dsh = FakeCloud(), FakeDsh()
        result = await runner.run_scenarios(manifest(), cloud=cloud, dsh=dsh,
                                            operator=FakeOperator(), output_root=root)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(set(result['arm_order']), {'control', 'coopagents'})
        self.assertEqual(result['evidence_classification'], 'harness_only')
        self.assertEqual(len(set(result['fixture_fingerprints'].values())), 1)
        self.assertTrue(Path(result['artifact_dir']).is_dir())
        self.assertTrue((Path(result['artifact_dir']) / 'run.json').is_file())
        self.assertTrue(all(call[4] for call in dsh.calls))
        sessions = [call[2] for call in dsh.calls]
        self.assertEqual(len(sessions), len(set(sessions)))
        self.assertTrue(all(call[5] <= 30 for call in dsh.calls))

    async def test_stops_on_failed_trigger_and_retains_partial_evidence(self):
        root = self.output_root()
        result = await runner.run_scenarios(manifest(), cloud=FakeCloud('teammate_unavailable'),
                                            dsh=FakeDsh(), operator=FakeOperator(), output_root=root)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['stop_reason'], 'trigger_failed')
        record = json.loads((Path(result['artifact_dir']) / 'run.json').read_text())
        self.assertTrue(record['attempts'])
        self.assertTrue(record['partial'])

    async def test_never_manufactures_approval_or_human_decision(self):
        class NoDecision:
            async def decide(self, **kwargs):
                return {'status': 'unavailable', 'source': 'fixture', 'evidence_ref': 'fake:none'}

        result = await runner.run_scenarios(manifest(), cloud=FakeCloud(), dsh=FakeDsh(),
                                            operator=NoDecision(), output_root=self.output_root())
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['stop_reason'], 'operator_decision_unavailable')
        record = json.loads((Path(result['artifact_dir']) / 'run.json').read_text())
        encoded = json.dumps(record)
        self.assertNotIn('operator_decision_recorded', encoded)

    async def test_cost_budget_stop_preserves_run_and_later_attempt_never_overwrites(self):
        data = manifest()
        data['cost_limit_usd'] = 0.05
        root = self.output_root()
        first = await runner.run_scenarios(data, cloud=FakeCloud(), dsh=FakeDsh(cost=0.1),
                                           operator=FakeOperator(), output_root=root)
        second = await runner.run_scenarios(data, cloud=FakeCloud(), dsh=FakeDsh(cost=0),
                                            operator=FakeOperator(), output_root=root)
        self.assertEqual(first['stop_reason'], 'budget_exhausted')
        self.assertNotEqual(first['artifact_dir'], second['artifact_dir'])
        self.assertTrue((Path(first['artifact_dir']) / 'run.json').exists())


if __name__ == '__main__':
    unittest.main()
