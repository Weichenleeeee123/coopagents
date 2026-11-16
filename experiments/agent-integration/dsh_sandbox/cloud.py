"""Explicitly opted-in Alibaba CLI private management for a single retained run.

The operator stages role prompts and configuration on each VM using a private
setup artifact. Cloud Assistant receives only the fixed module and config path;
it never receives prompt text, provider keys, model configuration or a model
supplied shell command. The installed ``aliyun`` CLI owns its credential chain.

API contract (official Alibaba ECS documentation, checked 2026-11-17):
RunCommand / DescribeInvocationResults, DescribeInstances, StopInstance and
StartInstance. RunCommand is asynchronous; request acceptance is not completion.
No resource deletion, provisioning, credential reading or business mutation is
implemented. Business transitions return ``await_observation``.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
from pathlib import PurePosixPath
import re
import shlex
import subprocess
import sys
import time
from uuid import uuid4


REMOTE_RUNNER = '/opt/dsh-sandbox/venv/bin/python -m dsh_sandbox.dsh_runner'
REMOTE_ROOT = '/var/lib/dsh-sandbox/runs'
_ALIAS = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
_INSTANCE = re.compile(r'^i-[A-Za-z0-9]{1,64}$')
_INVOKE = re.compile(r'^t-[A-Za-z0-9-]{1,100}$')
_REQUEST = re.compile(r'^[A-Za-z0-9-]{8,80}$')
_ROLES = {'frontend': 'front', 'backend': 'back', 'integration': 'integration'}
_ARMS = {'control', 'coopagents'}
_TERMINAL_FAILURE = {'Failed', 'Stopped', 'Terminated', 'Invalid', 'Timeout',
                     'TimedOut', 'DeliveryFailed', 'ExecutionFailed', 'ExecutionTimeout',
                     'Aborted', 'Error', 'Cancelled', 'Stopping', 'PartialFailed', 'DeliveryTimeout'}


def _alias(value, field):
    if not isinstance(value, str) or not _ALIAS.fullmatch(value):
        raise ValueError('Invalid ' + field)
    return value


def _timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 86400:
        raise ValueError('Timeout must be between zero and 86400 seconds')
    return float(value)


class _CloudFailure(Exception):
    """Contain only a fixed classification, never CLI/SDK response text."""


class AlibabaCloudAdapter:
    def __init__(self, *, region, inventory, execute_cloud=False, process=None,
                 poll_interval_seconds=1, clock=None, sleep=None):
        self.region = _alias(region, 'region')
        if not isinstance(inventory, dict):
            raise ValueError('Run inventory is required')
        self.run_id = _alias(inventory.get('run_id'), 'run_id')
        agents = inventory.get('agents')
        if not isinstance(agents, list) or len(agents) != 3:
            raise ValueError('Exactly three run-bound agent instances are required')
        self.instances = {}
        for entry in agents:
            if not isinstance(entry, dict):
                raise ValueError('Invalid agent inventory')
            role = next((key for key, value in _ROLES.items() if value == entry.get('agent_id')), None)
            lifecycle = entry.get('lifecycle', {})
            instance = lifecycle.get('instance_id') if isinstance(lifecycle, dict) else None
            if (role is None or role in self.instances or not isinstance(instance, str)
                    or not _INSTANCE.fullmatch(instance) or lifecycle.get('run_id') != self.run_id):
                raise ValueError('Invalid run-bound member identity')
            self.instances[role] = instance
        if len(set(self.instances.values())) != 3:
            raise ValueError('Member instance identities must be distinct')
        if type(execute_cloud) is not bool:
            raise ValueError('execute_cloud must be an explicit boolean')
        self.execute_cloud = execute_cloud
        self.process = process or subprocess.run
        if (type(poll_interval_seconds) not in (int, float)
                or not math.isfinite(poll_interval_seconds) or poll_interval_seconds < 0):
            raise ValueError('Invalid poll interval')
        self.poll_interval_seconds = poll_interval_seconds
        self.clock = clock or time.monotonic
        self.sleep = sleep or asyncio.sleep

    def _result(self, status, *, reference=None):
        result = {'status': status, 'source': 'cloud_management'}
        if reference:
            result['evidence_ref'] = reference
        return result

    def _request_ref(self, request_id):
        if isinstance(request_id, str) and _REQUEST.fullmatch(request_id):
            return 'private:cloud/' + self.run_id + '/request/' + request_id
        return None

    async def _call(self, operation, parameters, deadline):
        if not self.execute_cloud:
            raise _CloudFailure('cloud_execution_disabled')
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise _CloudFailure('timeout')
        argv = ['aliyun', 'ecs', operation, '--RegionId', self.region]
        for name, value in parameters:
            argv.extend(['--' + name, str(value)])
        try:
            result = await asyncio.to_thread(self.process, argv, shell=False,
                                             capture_output=True, text=True,
                                             check=False, timeout=min(remaining, 30))
            if result.returncode != 0:
                raise _CloudFailure('cli_error')
            data = json.loads(result.stdout)
            if not isinstance(data, dict):
                raise _CloudFailure('invalid_cli_response')
            return data
        except _CloudFailure:
            raise
        except subprocess.TimeoutExpired:
            raise _CloudFailure('timeout') from None
        except Exception:
            # Includes injected process/SDK errors. Never surface their message,
            # stdout, stderr, command line, request ID or credential material.
            raise _CloudFailure('cli_error') from None

    async def _inventory(self, deadline):
        data = await self._call('DescribeInstances', [
            ('Tag.1.Key', 'Project'), ('Tag.1.Value', 'dsh-sandbox'),
            ('Tag.2.Key', 'RunId'), ('Tag.2.Value', self.run_id),
            ('InstanceIds', json.dumps(sorted(self.instances.values()), separators=(',', ':'))),
            ('PageSize', 100),
        ], deadline)
        container = data.get('Instances', {})
        rows = container.get('Instance', []) if isinstance(container, dict) else []
        if not isinstance(rows, list) or len(rows) != 3:
            raise _CloudFailure('inventory_mismatch')
        observed = {}
        for row in rows:
            if not isinstance(row, dict):
                raise _CloudFailure('inventory_mismatch')
            tags = row.get('Tags', {})
            tags = tags.get('Tag', []) if isinstance(tags, dict) else []
            if not isinstance(tags, list) or any(not isinstance(tag, dict) for tag in tags):
                raise _CloudFailure('inventory_mismatch')
            keys = [tag.get('TagKey') for tag in tags]
            if len(keys) != len(set(keys)):
                raise _CloudFailure('inventory_mismatch')
            tags = {tag.get('TagKey'): tag.get('TagValue') for tag in tags}
            role = next((r for r, workload in _ROLES.items() if workload == tags.get('Workload')), None)
            if (role is None or role in observed or tags.get('Project') != 'dsh-sandbox'
                    or tags.get('RunId') != self.run_id
                    or row.get('InstanceId') != self.instances[role]):
                raise _CloudFailure('inventory_mismatch')
            observed[role] = row.get('Status')
        observed['_request_id'] = data.get('RequestId')
        return observed

    async def preflight(self, *, timeout_seconds=30):
        """Read current cloud tags and exact expected VM IDs; performs no writes."""
        deadline = self.clock() + _timeout(timeout_seconds)
        try:
            observed = await self._inventory(deadline)
            return self._result('validated', reference=self._request_ref(observed.get('_request_id')))
        except _CloudFailure as exc:
            return self._result(str(exc))

    def _context(self, run_id, arm):
        if run_id != self.run_id or arm not in _ARMS:
            raise ValueError('Call must match the configured run and arm')

    async def trigger(self, *, run_id, arm, scenario_id, transition, timeout_seconds):
        """Operate infrastructure only; never create replies, approvals or receipts.

        Owner stop/start is available solely in the explicit owner_restart
        scenario. Network faults and business changes require an independent
        operator/native observation adapter; they are never reported successful.
        """
        self._context(run_id, arm)
        deadline = self.clock() + _timeout(timeout_seconds)
        _alias(scenario_id, 'scenario_id')
        _alias(transition, 'transition')
        action = {
            ('teammate_unavailable', 'teammate_unavailable'): ('backend', 'StopInstance'),
            ('teammate_unavailable', 'unavailable_teammate'): ('backend', 'StopInstance'),
            ('new_session_recovery', 'teammate_available'): ('backend', 'StartInstance'),
            ('owner_restart', 'owner_restart_stop'): ('frontend', 'StopInstance'),
            ('owner_restart', 'owner_restart_start'): ('frontend', 'StartInstance'),
        }.get((scenario_id, transition))
        if action is None:
            if transition.startswith('owner_restart'):
                return self._result('unsupported_transition')
            return {'status': 'await_observation', 'source': 'operator_or_native_observation'}
        role, operation = action
        try:
            current = await self._inventory(deadline)
            parameters = [('InstanceId', self.instances[role])]
            if operation == 'StopInstance':
                parameters.extend([('ForceStop', 'false'), ('StoppedMode', 'KeepCharging')])
                target = 'Stopped'
            else:
                target = 'Running'
            if current[role] == target:
                return self._result('completed', reference=self._request_ref(current.get('_request_id')))
            requested = await self._call(operation, parameters, deadline)
            while self.clock() < deadline:
                current = await self._inventory(deadline)
                if current[role] == target:
                    return self._result('completed', reference=(self._request_ref(requested.get('RequestId'))
                                                                or self._request_ref(current.get('_request_id'))))
                await self.sleep(min(max(0.05, self.poll_interval_seconds),
                                     max(0, deadline - self.clock())))
            return self._result('timeout')
        except _CloudFailure as exc:
            return self._result(str(exc))

    async def execute_role(self, *, run_id, arm, role, config_path,
                           timeout_seconds, workspace=None):
        """Run a staged path-only DSH request on its exact member VM.

        The config and any prompt/secret references must already be staged by
        the private VM setup process. Neither JSON configuration nor stdin is
        forwarded into Cloud Assistant. The remote runner stores all output in
        private VM evidence; its Cloud Assistant output is discarded here.
        """
        self._context(run_id, arm)
        if role not in _ROLES:
            raise ValueError('Invalid role')
        timeout = _timeout(timeout_seconds)
        root = PurePosixPath(REMOTE_ROOT) / self.run_id / arm / role
        if config_path != str(root / 'config.json'):
            raise ValueError('Config must be the fixed staged run/arm/role path')
        expected_workspace = str(root / 'project')
        if workspace is not None and workspace != expected_workspace:
            raise ValueError('Workspace must be the fixed role-local path')
        deadline = self.clock() + timeout
        try:
            state = await self._inventory(deadline)
            if state[role] != 'Running':
                return self._result('instance_not_running')
            result_path = root / ('result-' + uuid4().hex + '.json')
            command = ' '.join(shlex.quote(part) for part in [
                *shlex.split(REMOTE_RUNNER), 'run-config', '--config', config_path,
            ]) + ' > ' + shlex.quote(str(result_path)) + ' 2>/dev/null'
            data = await self._call('RunCommand', [
                ('Type', 'RunShellScript'), ('InstanceId.1', self.instances[role]),
                ('CommandContent', base64.b64encode(command.encode('utf-8')).decode('ascii')),
                ('ContentEncoding', 'Base64'), ('Timeout', max(1, math.ceil(deadline - self.clock()))),
                ('WorkingDir', expected_workspace), ('RepeatMode', 'Once'),
                ('EnableParameter', 'false'), ('Username', 'dsh'),
            ], deadline)
            invoke_id = data.get('InvokeId')
            if not isinstance(invoke_id, str) or not _INVOKE.fullmatch(invoke_id):
                raise _CloudFailure('invalid_cli_response')
            reference = 'private:vm/' + self.run_id + '/' + arm + '/' + role + '/' + result_path.name
            while self.clock() < deadline:
                response = await self._call('DescribeInvocationResults', [
                    ('InvokeId', invoke_id), ('InstanceId', self.instances[role]),
                ], deadline)
                container = response.get('Invocation', {})
                rows = container.get('InvocationResults', {}).get('InvocationResult', []) if isinstance(container, dict) else container
                if not isinstance(rows, list):
                    raise _CloudFailure('invalid_cli_response')
                if len(rows) > 1:
                    raise _CloudFailure('invalid_cli_response')
                if rows:
                    row = rows[0]
                    if (not isinstance(row, dict)
                            or row.get('InstanceId', self.instances[role]) != self.instances[role]
                            or row.get('InvokeId', invoke_id) != invoke_id):
                        raise _CloudFailure('invalid_cli_response')
                    status = row.get('InvocationStatus', row.get('InvokeStatus'))
                    if status == 'Success':
                        return self._result('completed' if row.get('ExitCode') == 0 else 'failed', reference=reference)
                    if status in _TERMINAL_FAILURE:
                        return self._result('timeout' if status in ('Timeout', 'TimedOut', 'ExecutionTimeout') else 'failed', reference=reference)
                await self.sleep(min(max(0.05, self.poll_interval_seconds),
                                     max(0, deadline - self.clock())))
            return self._result('timeout', reference=reference)
        except _CloudFailure as exc:
            return self._result(str(exc))


def main(argv=None):
    """Private operator CLI. Stdin is management metadata and path references only."""
    parser = argparse.ArgumentParser(description='Opt-in fixed DSH Alibaba Cloud management')
    parser.add_argument('--execute-cloud', action='store_true')
    args = parser.parse_args(argv)
    if not args.execute_cloud:
        print(json.dumps({'status': 'cloud_execution_disabled'}))
        return 2
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or set(request) - {'region', 'inventory', 'action', 'parameters'}:
            raise ValueError('Invalid request')
        adapter = AlibabaCloudAdapter(region=request['region'], inventory=request['inventory'], execute_cloud=True)
        action = request['action']
        if action not in ('preflight', 'trigger', 'execute_role'):
            raise ValueError('Unsupported action')
        result = asyncio.run(getattr(adapter, action)(**request.get('parameters', {})))
    except Exception:
        result = {'status': 'configuration_error'}
    print(json.dumps(result))
    return 0 if result['status'] in ('validated', 'accepted', 'completed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
