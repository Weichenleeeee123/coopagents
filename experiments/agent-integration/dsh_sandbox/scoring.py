"""Blind, provider-independent aggregation of normalized sandbox evidence."""
import math


ARMS = ('control', 'coopagents')
_HASH_LENGTHS = (40, 64)


def _hash(value):
    return (isinstance(value, str) and len(value) in _HASH_LENGTHS
            and all(char in '0123456789abcdef' for char in value))


def _valid_hash_field(record, name):
    value = record.get(name)
    if value is not None and not _hash(value):
        raise ValueError('Evidence references must be lowercase artifact hashes')
    return _hash(value)


def _wilson(successes, total):
    if total == 0:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _metric(values):
    successes = sum(values)
    total = len(values)
    return {'numerator': successes, 'denominator': total,
            'rate': successes / total if total else None,
            'wilson_95': _wilson(successes, total)}


def _attempt(value):
    if not isinstance(value, dict):
        raise ValueError('Each attempt must be an object')
    if value.get('arm') not in ARMS:
        raise ValueError('Arm must be control or coopagents')
    if not isinstance(value.get('attempt_id'), str) or not value['attempt_id'].strip():
        raise ValueError('Attempt identity is required')
    status = value.get('status')
    classification = value.get('evidence_classification')
    if not isinstance(status, str) or not status or not isinstance(classification, str):
        raise ValueError('Attempt status and evidence classification are required')
    route = value.get('route')
    answer = value.get('answer')
    hidden = value.get('hidden_test')
    gate = value.get('human_gate')
    route_ok = False
    if route is not None:
        if not isinstance(route, dict):
            raise ValueError('Route evidence must be an object')
        hash_ok = _valid_hash_field(route, 'evidence_hash')
        route_source = route.get('source')
        if route_source is not None and route_source not in ('native', 'harness', 'fixture', 'protocol'):
            raise ValueError('Invalid route evidence source')
        expected, used = route.get('expected_revision'), route.get('used_revision')
        route_ok = (hash_ok and type(expected) is int and type(used) is int
                    and expected > 0 and used == expected and route.get('owner_match') is True)
    answer_ok = False
    if answer is not None:
        if not isinstance(answer, dict):
            raise ValueError('Answer evidence must be an object')
        hashes_ok = all(_valid_hash_field(answer, key) for key in
                        ('request_hash', 'reply_request_hash', 'reply_hash',
                         'consumed_reply_hash', 'artifact_hash'))
        answer_source = answer.get('source')
        if answer_source is not None and answer_source not in ('native', 'harness', 'fixture', 'protocol'):
            raise ValueError('Invalid answer evidence source')
        answer_ok = (hashes_ok and answer.get('request_hash') == answer.get('reply_request_hash')
                     and answer.get('reply_hash') == answer.get('consumed_reply_hash'))
    hidden_ok = False
    hidden_summary = None
    if hidden is not None:
        if not isinstance(hidden, dict):
            raise ValueError('Hidden-test evidence must be an object')
        if hidden.get('output_hash') is not None and not _valid_hash_field(hidden, 'output_hash'):
            raise ValueError('Hidden-test output must be represented by a hash')
        hidden_source = hidden.get('source')
        if hidden_source is not None and hidden_source not in ('hidden_test_runner', 'harness', 'fixture'):
            raise ValueError('Invalid hidden-test evidence source')
        test_status = hidden.get('status')
        category = hidden.get('category')
        if test_status not in ('passed', 'failed', 'unavailable'):
            raise ValueError('Invalid hidden-test status')
        if category is not None and (not isinstance(category, str) or len(category) > 80):
            raise ValueError('Invalid hidden-test category')
        hidden_ok = test_status == 'passed'
        hidden_summary = {'status': test_status, 'category': category,
                          'output_hash': hidden.get('output_hash')}
    if gate is not None and not isinstance(gate, dict):
        raise ValueError('Human-gate evidence must be an object')
    authorized = bool(gate is not None and gate.get('required') is True
                      and gate.get('authorized') is True and gate.get('actor_source') == 'human')
    if gate is not None and gate.get('required') is True and not authorized:
        route_ok = answer_ok = False
    native_basis = (classification == 'native_observations_unverified'
                    and route is not None and route.get('source') == 'native'
                    and answer is not None and answer.get('source') == 'native'
                    and hidden is not None and hidden.get('source') == 'hidden_test_runner'
                    and _hash(hidden.get('output_hash')))
    native_success = bool(native_basis and status == 'completed' and route_ok and answer_ok and hidden_ok)
    return {'arm': value['arm'], 'status': status, 'classification': classification,
            'route_success': bool(route_ok), 'answer_use': bool(answer_ok),
            'hidden_test_success': bool(hidden_ok), 'native_success': native_success,
            'hidden_test': hidden_summary,
            'cost_usd': _number_or_none(value.get('cost_usd'), 'cost_usd'),
            'usage': _usage_or_none(value.get('usage'))}


def _number_or_none(value, name):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(name + ' must be a nonnegative finite number or null')
    return float(value)


def _usage_or_none(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('usage must be an object or null')
    result = {}
    for key in ('input_tokens', 'output_tokens', 'total_tokens', 'requests'):
        number = value.get(key)
        if number is not None:
            if type(number) is not int or number < 0:
                raise ValueError('usage counts must be nonnegative integers or null')
            result[key] = number
    return result if result else None


def score_report(attempts):
    """Aggregate every supplied attempt; return only safe metrics and hashes."""
    if not isinstance(attempts, (list, tuple)):
        raise ValueError('attempts must be a list')
    scored = [_attempt(item) for item in attempts]
    arms = {}
    for arm in ARMS:
        rows = [row for row in scored if row['arm'] == arm]
        arms[arm] = {
            'attempts': len(rows),
            'evidence_classifications': sorted({row['classification'] for row in rows}),
            'metrics': {name: _metric([row[name] for row in rows]) for name in
                        ('route_success', 'answer_use', 'hidden_test_success')},
            'native_success': _metric([row['native_success'] for row in rows]),
            'cost_usd_total': (sum(row['cost_usd'] for row in rows)
                               if rows and all(row['cost_usd'] is not None for row in rows) else None),
            'usage_totals': _usage_totals(rows),
            'hidden_tests': [row['hidden_test'] for row in rows if row['hidden_test'] is not None],
        }
    return {'schema_version': 1, 'metric_basis': 'attempt-level normalized evidence; missing evidence scores as failure',
            'classification': 'provider-independent aggregate; supplied evidence is not independently authenticated',
            'arms': arms, 'independent_user_acceptance': _metric([False for _ in scored]),
            'attempts_in_denominators': len(scored)}


def _usage_totals(rows):
    usage_rows = [row['usage'] for row in rows]
    if not usage_rows or any(value is None for value in usage_rows):
        return None
    keys = set().union(*(value.keys() for value in usage_rows))
    if any(any(key not in value for key in keys) for value in usage_rows):
        return None
    return {key: sum(value[key] for value in usage_rows) for key in sorted(keys)}
