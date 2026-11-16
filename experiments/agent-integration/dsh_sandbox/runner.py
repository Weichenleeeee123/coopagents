"""Provider-neutral, adapter-injected coordinator for retained DSH sandbox runs.

This module makes no cloud, DSH, or network calls. Adapter output is retained as
observations; fake adapter evidence is never promoted to native acceptance.
"""
import asyncio
import hashlib
import json
import math
from pathlib import Path
import random
import secrets
from uuid import uuid4

try:
    from .fixture_repo import prepare_fixture
    from .manifest import validate_manifest
    from .scenario_state import ScenarioState
except ImportError:
    from fixture_repo import prepare_fixture
    from manifest import validate_manifest
    from scenario_state import ScenarioState


SCENARIOS = (
    ('teammate_unavailable', 'unavailable_teammate'),
    ('new_session_recovery', 'new_session_recovery'),
    ('handoff_stale_route_rejection', 'handoff_stale_route_rejection'),
    ('agreement_approval', 'agreement_approval'),
    ('human_decision', 'human_decision'),
)
MAX_TRANSITION_SECONDS = 120
_SAFE_FIELDS = ('status', 'source', 'evidence_ref', 'session_id', 'cost_usd',
                'decision', 'actor_alias', 'request_id', 'reply_id', 'route_revision')


def _safe_result(value):
    if not isinstance(value, dict):
        return {'status': 'invalid_adapter_result'}
    safe = {key: value[key] for key in _SAFE_FIELDS if key in value
            and isinstance(value[key], (str, int, float, bool, type(None)))}
    cost = safe.get('cost_usd')
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        safe.pop('cost_usd')
    return safe


def _write_artifact(path, state):
    path.write_text(json.dumps(state, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


async def _invoke(adapter, method, *, call_timeout_seconds, **kwargs):
    callback = getattr(adapter, method, None)
    if callback is None:
        raise RuntimeError('missing_adapter_method:' + method)
    result = callback(**kwargs)
    if not asyncio.iscoroutine(result):
        raise RuntimeError('adapter_methods_must_be_async:' + method)
    return await asyncio.wait_for(result, timeout=call_timeout_seconds)


async def run_scenarios(manifest, *, cloud, dsh, operator, output_root):
    """Run a paired attempt using injected async adapters and retain every stop.

    Required adapter methods are ``cloud.trigger(...)``, ``dsh.run_turn(...)``
    and ``operator.decide(...)``. Each receives a bounded timeout. Adapter
    results are data, not proof: only adapter-sourced ``native`` observations
    retain that label, and the final evidence classification remains
    ``harness_only`` unless every observation is native (which still does not
    independently authenticate it).
    """
    run = validate_manifest(manifest)
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    attempt_dir = root / (run['run_id'] + '-' + uuid4().hex)
    attempt_dir.mkdir(exist_ok=False)

    order = ['control', 'coopagents']
    random.Random(run['scenario_seed']).shuffle(order)
    record = {
        'schema_version': 1, 'run_id': run['run_id'], 'status': 'running',
        'evidence_classification': 'harness_only', 'arm_order': order,
        'manifest': run, 'attempts': [], 'outcomes': {}, 'partial': True,
        'fixture_fingerprints': {}, 'stop_reason': None,
    }
    artifact = attempt_dir / 'run.json'
    _write_artifact(artifact, record)
    deadline = asyncio.get_running_loop().time() + run['timeout_seconds']
    spent = 0.0
    observed_sources = []

    def persist():
        _write_artifact(artifact, record)

    def stop(reason):
        record['status'] = 'stopped'
        record['stop_reason'] = reason
        persist()
        return {key: value for key, value in record.items() if key != 'manifest'} | {
            'artifact_dir': str(attempt_dir)}

    def timeout_left():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        return min(remaining, MAX_TRANSITION_SECONDS)

    async def trigger(arm, scenario_id, transition):
        try:
            value = await _invoke(cloud, 'trigger', call_timeout_seconds=timeout_left(),
                                  arm=arm, scenario_id=scenario_id, transition=transition,
                                  timeout_seconds=timeout_left(), run_id=run['run_id'])
        except (asyncio.TimeoutError, Exception) as exc:
            return None, 'trigger_timeout' if isinstance(exc, asyncio.TimeoutError) else 'trigger_failed'
        safe = _safe_result(value)
        observed_sources.append(safe.get('source'))
        record['attempts'].append({'arm': arm, 'scenario_id': scenario_id,
                                   'transition': transition, 'observation': safe})
        persist()
        if safe.get('status') not in ('observed', 'completed') or not safe.get('evidence_ref'):
            return safe, 'provider_failed' if safe.get('status') == 'provider_failed' else 'trigger_failed'
        return safe, None

    async def decide(arm, scenario_id, decision_prompt):
        try:
            value = await _invoke(operator, 'decide', call_timeout_seconds=timeout_left(),
                                  run_id=run['run_id'], arm=arm, scenario_id=scenario_id,
                                  decision_prompt=decision_prompt, timeout_seconds=timeout_left())
        except asyncio.TimeoutError:
            return None, 'operator_decision_timeout'
        except Exception:
            return None, 'operator_decision_unavailable'
        safe = _safe_result(value)
        observed_sources.append(safe.get('source'))
        if (safe.get('status') != 'decided' or safe.get('source') != 'human'
                or not safe.get('evidence_ref') or safe.get('decision') not in ('approve', 'reject')
                or not safe.get('actor_alias')):
            return safe, 'operator_decision_unavailable'
        record['attempts'].append({'arm': arm, 'scenario_id': scenario_id,
                                   'transition': 'operator_decision', 'observation': safe})
        persist()
        return safe, None

    async def turn(arm, role, prompt, workspace, fresh=False):
        nonlocal spent
        session_id = 'session-' + secrets.token_hex(12)
        try:
            value = await _invoke(dsh, 'run_turn', call_timeout_seconds=timeout_left(),
                                  arm=arm, role=role, prompt=prompt, session_id=session_id,
                                  fresh_session=fresh, workspace=workspace,
                                  timeout_seconds=timeout_left(),
                                  budget_remaining_usd=max(0.0, run['cost_limit_usd'] - spent))
        except asyncio.TimeoutError:
            return None, 'dsh_timeout'
        except Exception:
            return None, 'dsh_failed'
        safe = _safe_result(value)
        observed_sources.append(safe.get('source'))
        record['attempts'].append({'arm': arm, 'scenario_id': 'agent_turn', 'role': role,
                                   'transition': 'fresh_session' if fresh else 'turn',
                                   'observation': safe})
        cost = safe.get('cost_usd')
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            spent += float(cost)
        record['cost_usd'] = spent
        persist()
        if safe.get('status') != 'completed' or not safe.get('evidence_ref'):
            return safe, 'provider_failed' if safe.get('status') == 'provider_failed' else 'dsh_failed'
        if spent >= run['cost_limit_usd']:
            return safe, 'budget_exhausted'
        return safe, None

    try:
        for arm in order:
            fixture_root = attempt_dir / arm / 'fixture'
            fixture = prepare_fixture(fixture_root, seed=run['scenario_seed'])
            fingerprint = hashlib.sha256()
            for role in ('frontend', 'backend', 'integration'):
                project = Path(fixture['participants'][role]['project'])
                for source in sorted(path for path in project.rglob('*') if path.is_file() and '.git' not in path.parts):
                    fingerprint.update(source.relative_to(project).as_posix().encode())
                    fingerprint.update(source.read_bytes())
            record['fixture_fingerprints'][arm] = fingerprint.hexdigest()
            persist()
            workspaces = {role: fixture['participants'][role]['project']
                          for role in ('frontend', 'backend', 'integration')}
            for role in ('frontend', 'backend', 'integration'):
                _, failure = await turn(arm, role, fixture['participants'][role]['goal'], workspaces[role])
                if failure:
                    return stop(failure)

            for scenario_id, outcome in SCENARIOS:
                if scenario_id == 'new_session_recovery':
                    result, failure = await trigger(arm, scenario_id, 'teammate_available')
                    if failure:
                        return stop(failure)
                    _, failure = await turn(arm, 'backend', fixture['participants']['backend']['goal'],
                                            workspaces['backend'], fresh=True)
                elif scenario_id == 'handoff_stale_route_rejection':
                    decision, failure = await decide(arm, scenario_id, 'Approve or reject the proposed backend ownership handoff.')
                    if failure:
                        return stop(failure)
                    if decision['decision'] == 'reject':
                        record['outcomes'][outcome] = {
                            'status': 'rejected_by_operator', 'source': 'human',
                            'evidence_ref': decision['evidence_ref']}
                        persist()
                        continue
                    _, failure = await trigger(arm, scenario_id, 'handoff_accepted')
                    if not failure:
                        _, failure = await trigger(arm, scenario_id, 'stale_route_reply')
                    if not failure:
                        _, failure = await trigger(arm, scenario_id, 'stale_route_rejected')
                elif scenario_id == 'agreement_approval':
                    decision, failure = await decide(arm, scenario_id, 'Approve or reject the proposed interface agreement update.')
                    if failure:
                        return stop(failure)
                    if decision['decision'] == 'reject':
                        record['outcomes'][outcome] = {
                            'status': 'rejected_by_operator', 'source': 'human',
                            'evidence_ref': decision['evidence_ref']}
                        persist()
                        continue
                    _, failure = await trigger(arm, scenario_id, 'agreement_approved')
                elif scenario_id == 'human_decision':
                    state = ScenarioState(scenario_id)
                    presented, failure = await trigger(arm, scenario_id, 'decision_presented')
                    if not failure and presented.get('source') == 'native':
                        state.observe('decision_presented', source='native',
                                      evidence_ref=presented['evidence_ref'])
                    if not failure:
                        decision, failure = await decide(arm, scenario_id, 'Record the actual operator choice for the pending project decision.')
                        if not failure and state.events:
                            state.observe('operator_decision', source='human',
                                          evidence_ref=decision['evidence_ref'],
                                          decision=decision['decision'], actor_alias=decision['actor_alias'])
                    if not failure:
                        applied, failure = await trigger(arm, scenario_id, 'decision_applied')
                        if not failure and applied.get('decision') not in (None, decision['decision']):
                            failure = 'operator_decision_mismatch'
                        if (not failure and state.events and applied.get('source') == 'native'
                                and applied.get('decision') == decision['decision']):
                            state.observe('decision_applied', source='native',
                                          evidence_ref=applied['evidence_ref'],
                                          decision=applied['decision'])
                else:
                    _, failure = await trigger(arm, scenario_id, scenario_id)
                    if not failure:
                        _, failure = await turn(arm, 'frontend', fixture['participants']['frontend']['goal'],
                                                workspaces['frontend'])
                if failure:
                    return stop(failure)
                recent = record['attempts'][-1]['observation'] if record['attempts'] else {}
                record['outcomes'][outcome] = {
                    'status': 'native_observation_unverified' if recent.get('source') == 'native'
                    else 'harness_observation',
                    'source': recent.get('source'),
                    'evidence_ref': recent.get('evidence_ref'),
                }
                persist()
    except asyncio.TimeoutError:
        return stop('run_timeout')
    except Exception as exc:
        return stop('coordinator_failed:' + type(exc).__name__)

    record['status'] = 'completed'
    record['partial'] = False
    record['stop_reason'] = None
    record['evidence_classification'] = ('native_observations_unverified'
                                         if observed_sources and all(s == 'native' for s in observed_sources)
                                         else 'harness_only')
    persist()
    return {key: value for key, value in record.items() if key != 'manifest'} | {
        'artifact_dir': str(attempt_dir)}
