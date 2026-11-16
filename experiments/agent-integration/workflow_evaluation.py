"""Prepare tool-free goals or score supplied private, normalized observations.

This module never starts agents or contacts a service. Evidence references are
reviewer-supplied attestations, not authenticated proof. See docs/workflow-evaluation.md.
"""
import argparse
import json
import math
from pathlib import Path


def scenarios():
    """Describe outcomes without teaching the agent a protocol or call sequence."""
    result = [
        {'id': 'frontend-backend', 'people': 2,
         'goal': 'Deliver a profile form across frontend and backend responsibilities. The frontend needs a '
                 'field definition only present in the backend source. Obtain the responsible teammate’s '
                 'file-derived answer and use it correctly in the frontend implementation.'},
        {'id': 'three-member-routing', 'people': 3,
         'goal': 'Resolve an implementation question in a team with an interface owner, a service owner and '
                 'an unrelated teammate. Reach the current responsible owner, including after responsibility '
                 'changes, and use that owner’s answer without addressing the bystander.'},
        {'id': 'offline-reopen', 'people': 2,
         'goal': 'Continue a shared task after one teammate goes offline and returns in a fresh session. '
                 'Recover the outstanding question and its current answer from durable shared state, '
                 'preserve prior work and resume authorized independent work while waiting.'},
        {'id': 'agreement-change', 'people': 2,
         'goal': 'Complete dependent work when a previously used interface agreement receives a newer '
                 'approved version. Notice the impact, review the changed agreement and demonstrate which '
                 'current version the implementation now relies on.'},
        {'id': 'human-decision', 'people': 2,
         'goal': 'Advance a shared task until a contract or ownership change requires a human decision. '
                 'Present the concrete decision to the actual user, preserve pending work, and apply only '
                 'the specific decision authorized by that user’s current instruction.'},
    ]
    role_goals = {
        'frontend-backend': [
            ('requester', 'Implement the frontend profile form. Obtain the field definition from the teammate responsible for the backend and use it in your work.'),
            ('responder', 'Own the backend profile interface. Answer teammates within your responsibility using your local source files; retain your existing authorized work.')],
        'three-member-routing': [
            ('requester', 'Implement the dependent interface. Find the current service responsibility and obtain a usable answer, including after its owner changes.'),
            ('responder', 'Own the service interface. Answer questions about your responsibility from the current source and preserve responsibility history.'),
            ('bystander', 'Own unrelated documentation. Continue that work; do not impersonate the service owner.')],
        'offline-reopen': [
            ('requester', 'Advance the dependent task while your teammate is away. Preserve the outstanding question, do independent authorized work and use the answer after it becomes available.'),
            ('responder', 'Resume your responsibility in a new session after being offline. Recover outstanding team questions and answer from your current source files.')],
        'agreement-change': [
            ('requester', 'Continue implementation that relied on an earlier interface agreement. Check relevant approved changes, review their impact and record the version your work now relies on.'),
            ('responder', 'Own the shared interface. Explain the approved interface change and its evidence to dependent teammates without treating a draft as approved.')],
        'human-decision': [
            ('requester', 'Advance the dependent task. When a joint agreement or responsibility change needs a human decision, present its specific impact and wait for the actual user instruction.'),
            ('responder', 'Own the related responsibility. Supply technical evidence for the pending decision; do not approve or accept changes on another person’s behalf.')],
    }
    for scenario in result:
        scenario['participants'] = [dict(role=role, goal=goal,
            evidence_file='participants/'+role+'-observations.json')
            for role, goal in role_goals[scenario['id']]]
    return result


def _present(value):
    return isinstance(value, str) and bool(value.strip())


def _status(observed, valid):
    return 'unverified' if not observed else 'verified' if valid else 'failed'


def _time(record):
    value = record.get('at') if record else None
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _latency(first, second):
    start, end = _time(first), _time(second)
    return end - start if start is not None and end is not None and end >= start else None


def score_evidence(evidence):
    """Score one normalized exchange; absent observations remain unverified.

    Records are ordered observations of the evaluated exchange; the latest
    request/reply/consumption wins, so an earlier success cannot hide a failure.
    All ids are opaque local aliases. Never include credentials or raw logs.
    """
    if (not isinstance(evidence, dict) or type(evidence.get('schema_version')) is not int
            or evidence['schema_version'] != 1):
        raise ValueError('Expected normalized evidence schema_version 1')
    kind = evidence.get('kind')
    if kind not in ('fixture', 'protocol', 'native'):
        raise ValueError('Evidence kind must be fixture, protocol or native')
    scenario_id = evidence.get('scenario_id')
    if scenario_id not in {s['id'] for s in scenarios()}:
        raise ValueError('Unknown workflow scenario')
    records = evidence.get('records', [])
    participants = evidence.get('participants', [])
    expected = evidence.get('expected', {})
    if (not isinstance(records, list) or any(not isinstance(r, dict) for r in records)
            or not isinstance(participants, list) or any(not isinstance(p, dict) for p in participants)
            or not isinstance(expected, dict)):
        raise ValueError('Expected records, participants and expected identity objects')

    def latest(record_kind):
        return next((r for r in reversed(records) if r.get('kind') == record_kind), None)

    def observed(record, source=None):
        return bool(record and _present(record.get('evidence_ref'))
                    and (source is None or record.get('source') == source))

    def native(record):
        return kind == 'native' and observed(record, 'native')

    request, reply, consumed = (latest(k) for k in ('request', 'model_reply', 'requester_consumption'))
    requester, responder = (expected.get(k) for k in ('requester_member_id', 'responder_member_id'))
    revision = expected.get('route_revision')
    routes = [r for r in records if r.get('kind') == 'route_change' and observed(r, kind)
              and type(r.get('route_revision')) is int]
    if routes:
        route = max(routes, key=lambda r: r['route_revision'])
        if type(revision) is not int or route['route_revision'] >= revision:
            revision, responder = route['route_revision'], route.get('responder_member_id')
    identities_known = (_present(requester) and _present(responder) and requester != responder)
    identity_records = [(request, requester, responder), (reply, responder, requester), (consumed, requester, None)]
    identity_valid = identities_known and all(
        r is None or r.get('actor') == actor and (recipient is None or r.get('recipient') == recipient)
        for r, actor, recipient in identity_records)
    route_known = type(revision) is int and revision > 0
    route_valid = route_known and all(r is None or r.get('route_revision') == revision
                                     for r in (request, reply, consumed))
    request_valid = bool(native(request) and _present(request.get('request_id')))
    reply_valid = bool(native(reply) and request_valid and _present(reply.get('reply_id'))
                       and reply.get('request_id') == request['request_id']
                       and _present(reply.get('file_evidence_ref')))
    consumption_valid = bool(native(consumed) and reply_valid
                             and consumed.get('request_id') == request['request_id']
                             and consumed.get('reply_id') == reply['reply_id']
                             and _present(consumed.get('observed_effect')))
    checks = {
        'fixture': _status(latest('fixture_result'), observed(latest('fixture_result'), 'fixture')
                           and latest('fixture_result').get('passed') is True),
        'protocol': _status(latest('protocol_result'), observed(latest('protocol_result'), 'protocol')
                            and latest('protocol_result').get('passed') is True),
        'identity': _status(identities_known and any((request, reply, consumed)), identity_valid),
        'current_route': _status(route_known and any((request, reply, consumed)), route_valid),
        'model_reply': _status(reply, reply_valid),
        'requester_consumption': _status(consumed, consumption_valid),
    }

    people = [p for p in participants if p.get('member_id') in (requester, responder)]
    provenance_fields = ('human_id', 'device_id', 'session_id', 'network_id')
    provenance_valid = (len(people) == 2 and {p.get('member_id') for p in people} == {requester, responder}
                        and all(_present(p.get('evidence_ref')) for p in people)
                        and all(all(_present(p.get(f)) for p in people)
                                and len({p[f] for p in people}) == 2 for f in provenance_fields))
    checks['independent_provenance'] = _status(people, provenance_valid)
    accepted = {r.get('human_id') for r in records if r.get('kind') == 'human_acceptance'
                and observed(r, 'human') and _present(r.get('human_id'))}
    acceptance_valid = provenance_valid and {p['human_id'] for p in people} <= accepted
    checks['human_acceptance'] = _status(accepted, acceptance_valid)

    scenario_record, scenario_valid = consumed if scenario_id == 'frontend-backend' else None, consumption_valid if scenario_id == 'frontend-backend' else False
    if scenario_id == 'three-member-routing':
        scenario_record = latest('owner_route')
        scenario_valid = bool(native(scenario_record) and scenario_record.get('current_owner') == responder
                              and scenario_record.get('bystander_not_addressed') is True
                              and _present(scenario_record.get('bystander_member_id'))
                              and scenario_record['bystander_member_id'] not in (requester, responder)
                              and any(p.get('member_id') == scenario_record['bystander_member_id']
                                      and _present(p.get('evidence_ref')) for p in participants))
    elif scenario_id == 'offline-reopen':
        scenario_record = latest('recovery')
        scenario_valid = bool(native(scenario_record) and scenario_record.get('outstanding_work_recovered') is True
                              and _present(scenario_record.get('prior_session_id'))
                              and _present(scenario_record.get('resumed_session_id'))
                              and scenario_record['prior_session_id'] != scenario_record['resumed_session_id'])
    elif scenario_id == 'agreement-change':
        scenario_record = latest('agreement_review')
        scenario_valid = bool(native(scenario_record) and type(scenario_record.get('current_version')) is int
                              and type(scenario_record.get('previous_version')) is int
                              and 0 < scenario_record['previous_version'] < scenario_record['current_version']
                              and scenario_record.get('current_approved') is True
                              and scenario_record.get('used_version') == scenario_record['current_version'])
    elif scenario_id == 'human-decision':
        scenario_record = latest('human_decision')
        scenario_valid = bool(kind == 'native' and observed(scenario_record, 'human')
                              and _present(scenario_record.get('actual_user_instruction_ref'))
                              and scenario_record.get('current') is True)
    checks['scenario_outcome'] = _status(scenario_record, scenario_valid)

    complete = evidence.get('metrics_complete', [])
    if not isinstance(complete, list):
        raise ValueError('metrics_complete must list fully observed count names')
    metrics = {name: sum(1 for r in records if r.get('kind') == record_kind and observed(r))
               if name in complete else None for name, record_kind in (
                   ('tool_call_count', 'tool_call'), ('human_reminder_count', 'human_reminder'))}
    reply_link = bool(observed(request) and observed(reply) and _present(request.get('request_id'))
                      and request.get('request_id') == reply.get('request_id'))
    consumption_link = bool(reply_link and observed(consumed) and _present(reply.get('reply_id'))
                            and consumed.get('request_id') == request.get('request_id')
                            and consumed.get('reply_id') == reply.get('reply_id'))
    metrics.update(reply_latency_seconds=_latency(request, reply) if reply_link else None,
                   consumption_latency_seconds=_latency(reply, consumed) if consumption_link else None)
    success = (kind == 'native' and identity_valid and route_valid and request_valid
               and reply_valid and consumption_valid and scenario_valid)
    return {'schema_version': 1, 'scenario_id': scenario_id, 'evidence_kind': kind,
            'evidence_basis': 'Supplied normalized observations; references are not independently authenticated.',
            'checks': checks, 'native_success': success,
            'independent_user_acceptance': bool(success and acceptance_valid), 'metrics': metrics}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare', help='Print scenario goals; start no processes')
    score = commands.add_parser('score', help='Score supplied private normalized JSON evidence')
    score.add_argument('evidence', type=Path)
    args = parser.parse_args(argv)
    try:
        result = ({'schema_version': 1, 'scenarios': scenarios()} if args.command == 'prepare'
                  else score_evidence(json.loads(args.evidence.read_text(encoding='utf-8'))))
    except (ValueError, OSError):
        parser.error('Evidence could not be read or does not match the normalized schema')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
