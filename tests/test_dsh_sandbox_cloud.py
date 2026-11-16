"""Offline safety and CLI contract tests for the Alibaba Cloud adapter."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / 'experiments' / 'agent-integration' / 'dsh_sandbox'
sys.path.insert(0, str(SANDBOX))

import cloud


def inventory():
    return {
        'run_id': 'run-123',
        'agents': [
            {'agent_id': alias, 'lifecycle': {'instance_id': 'i-' + alias, 'run_id': 'run-123'}}
            for alias in ('front', 'back', 'integration')
        ],
    }


def describe_instances(*, frontend_status='Running', backend_status='Running'):
    return {'RequestId': 'request-123', 'Instances': {'Instance': [
        {'InstanceId': 'i-' + alias,
         'Status': {'front': frontend_status, 'back': backend_status}.get(alias, 'Running'),
         'Tags': {'Tag': [
            {'TagKey': 'Project', 'TagValue': 'dsh-sandbox'},
            {'TagKey': 'RunId', 'TagValue': 'run-123'},
            {'TagKey': 'Workload', 'TagValue': alias},
        ]}}
        for alias in ('front', 'back', 'integration')
    ]}}


class FakeProcess:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        value = self.responses.pop(0)
        return subprocess.CompletedProcess(argv, value[0], value[1], value[2])


class AlibabaCloudAdapterTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, process=None, **kwargs):
        return cloud.AlibabaCloudAdapter(
            region='ap-southeast-1', inventory=inventory(), process=process,
            poll_interval_seconds=0, **kwargs)

    async def test_cloud_execution_is_disabled_by_default(self):
        process = FakeProcess([])
        adapter = self.adapter(process)
        result = await adapter.trigger(arm='coopagents', scenario_id='teammate_unavailable',
                                       transition='unavailable_teammate', timeout_seconds=2,
                                       run_id='run-123')
        self.assertEqual(result['status'], 'cloud_execution_disabled')
        self.assertEqual(process.calls, [])

    async def test_real_role_dispatch_requires_cloud_opt_in(self):
        process = FakeProcess([])
        result = await self.adapter(process).execute_role(
            run_id='run-123', arm='coopagents', role='backend',
            config_path='/var/lib/dsh-sandbox/runs/run-123/coopagents/backend/config.json',
            timeout_seconds=20)
        self.assertEqual(result['status'], 'cloud_execution_disabled')
        self.assertEqual(process.calls, [])

    async def test_preflight_checks_tagged_inventory_against_exact_expected_ids(self):
        process = FakeProcess([(0, json.dumps(describe_instances()), '')])
        result = await self.adapter(process, execute_cloud=True).preflight()
        self.assertEqual(result['status'], 'validated')
        args = process.calls[0][0]
        self.assertIn('--Tag.1.Key', args)
        self.assertIn('RunId', args)
        self.assertIn('run-123', args)

    async def test_preflight_rejects_an_instance_with_a_different_run_tag(self):
        data = describe_instances()
        data['Instances']['Instance'][1]['Tags']['Tag'][1]['TagValue'] = 'another-run'
        process = FakeProcess([(0, json.dumps(data), '')])
        result = await self.adapter(process, execute_cloud=True).preflight()
        self.assertEqual(result['status'], 'inventory_mismatch')

    async def test_unavailable_transition_stops_only_the_validated_backend_vm(self):
        process = FakeProcess([
            (0, json.dumps(describe_instances()), ''),
            (0, '{}', ''),
            (0, json.dumps(describe_instances(backend_status='Stopped')), ''),
        ])
        result = await self.adapter(process, execute_cloud=True).trigger(
            arm='coopagents', scenario_id='teammate_unavailable',
            transition='unavailable_teammate', timeout_seconds=10, run_id='run-123')
        self.assertEqual(result['status'], 'completed')
        self.assertIn('i-back', process.calls[1][0])
        self.assertNotIn('i-front', process.calls[1][0])
        self.assertEqual(process.calls[1][0][1:3], ['ecs', 'StopInstance'])

    async def test_owner_stop_requires_the_explicit_owner_restart_transition(self):
        process = FakeProcess([])
        result = await self.adapter(process, execute_cloud=True).trigger(
            arm='coopagents', scenario_id='teammate_unavailable',
            transition='owner_restart_stop', timeout_seconds=10, run_id='run-123')
        self.assertEqual(result['status'], 'unsupported_transition')
        self.assertEqual(process.calls, [])

    async def test_business_trigger_returns_await_observation_without_faking_success(self):
        result = await self.adapter().trigger(
            arm='coopagents', scenario_id='agreement_approval',
            transition='agreement_approved', timeout_seconds=10, run_id='run-123')
        self.assertEqual(result['status'], 'await_observation')
        self.assertEqual(result['source'], 'operator_or_native_observation')

    async def test_explicit_owner_restart_targets_only_the_owner_member(self):
        process = FakeProcess([
            (0, json.dumps(describe_instances()), ''), (0, '{}', ''),
            (0, json.dumps(describe_instances(frontend_status='Stopped')), ''),
        ])
        result = await self.adapter(process, execute_cloud=True).trigger(
            arm='coopagents', scenario_id='owner_restart',
            transition='owner_restart_stop', timeout_seconds=10, run_id='run-123')
        self.assertEqual(result['status'], 'completed')
        self.assertIn('i-front', process.calls[1][0])
        self.assertNotIn('i-back', process.calls[1][0])

    async def test_execute_role_uses_only_fixed_runner_and_private_config_path(self):
        process = FakeProcess([
            (0, json.dumps(describe_instances()), ''),
            (0, json.dumps({'InvokeId': 't-invoke-123'}), ''),
            (0, json.dumps({'Invocation': {'InvocationResults': {'InvocationResult': [
                {'InvocationStatus': 'Success', 'ExitCode': 0, 'Output': 'private output'}]}}}), ''),
        ])
        result = await self.adapter(process, execute_cloud=True).execute_role(
            run_id='run-123', arm='coopagents', role='backend',
            config_path='/var/lib/dsh-sandbox/runs/run-123/coopagents/backend/config.json',
            timeout_seconds=20)
        self.assertEqual(result['status'], 'completed')
        self.assertNotIn('private output', json.dumps(result))
        self.assertRegex(result['evidence_ref'], r'/result-[0-9a-f]{32}\.json$')
        run_args = next(argv for argv, _ in process.calls if 'RunCommand' in argv)
        body = base64.b64decode(run_args[run_args.index('--CommandContent') + 1]).decode()
        self.assertIn(cloud.REMOTE_RUNNER, body)
        self.assertIn('config.json', body)
        self.assertNotIn('prompt', body.lower())
        self.assertNotIn('model', body.lower())
        self.assertNotIn('python -c', body)

    async def test_execute_role_rejects_arbitrary_paths_and_never_returns_cli_error_text(self):
        process = FakeProcess([])
        with self.assertRaises(ValueError):
            await self.adapter(process, execute_cloud=True).execute_role(
                run_id='run-123', arm='coopagents', role='backend',
                config_path='/tmp/../../etc/passwd', timeout_seconds=20)
        self.assertEqual(process.calls, [])

        failing = FakeProcess([(1, '', 'secret-token raw provider output')])
        result = await self.adapter(failing, execute_cloud=True).preflight()
        self.assertEqual(result['status'], 'cli_error')
        self.assertNotIn('secret-token', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
