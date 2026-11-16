"""Conservative scoring for runtime-observed Coopagents P2P network cases."""


CASES = {
    'direct': {'paths': {'direct'}, 'recovery': False},
    'relay-only': {'paths': {'relay'}, 'recovery': False},
    'udp-blocked': {'paths': {'unreachable'}, 'recovery': False},
    'nat-mapping-change': {'paths': {'direct', 'relay'}, 'recovery': True},
    'member-restart': {'paths': {'direct', 'relay'}, 'recovery': True},
    'owner-restart': {'paths': {'direct', 'relay'}, 'recovery': True},
}


def score_network_observation(observation):
    """Score one private normalized runtime observation.

    Network config alone is insufficient. A native selected path, two distinct
    NAT aliases, and an owner-service observation on the member bridge route are
    required. Missing or malformed measurements fail conservatively.
    """
    if not isinstance(observation, dict) or observation.get('schema_version') != 1:
        raise ValueError('Expected network observation schema_version 1')
    case_id = observation.get('case_id')
    if case_id not in CASES:
        raise ValueError('Unknown network matrix case')
    path = observation.get('selected_path')
    recovery = CASES[case_id]['recovery']
    valid = (
        observation.get('source') == 'native'
        and isinstance(observation.get('evidence_ref'), str)
        and bool(observation['evidence_ref'].strip())
        and isinstance(observation.get('agent_nat_alias'), str)
        and bool(observation['agent_nat_alias'])
        and isinstance(observation.get('owner_nat_alias'), str)
        and bool(observation['owner_nat_alias'])
        and observation['agent_nat_alias'] != observation['owner_nat_alias']
        and observation.get('owner_service_observed') is True
        and observation.get('business_route') == 'member-bridge-p2p'
        and path in CASES[case_id]['paths']
        and observation.get('revoked_credential_accepted') is False
    )
    if recovery:
        gap_count = observation.get('cursor_gap_count')
        duplicate_count = observation.get('duplicate_event_count')
        resumed_cursor = observation.get('resumed_cursor')
        valid = valid and type(gap_count) is int and gap_count == 0
        valid = valid and type(duplicate_count) is int and duplicate_count == 0
        valid = valid and type(resumed_cursor) is int and resumed_cursor >= 0
    return {
        'schema_version': 1,
        'case_id': case_id,
        'passed': bool(valid),
        'observed_path': path if observation.get('source') == 'native' else None,
        'evidence_basis': 'Runtime observation required; config is not path evidence.',
    }
