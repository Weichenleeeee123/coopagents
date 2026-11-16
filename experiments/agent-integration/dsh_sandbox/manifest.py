"""Validation and safe projection for one controlled sandbox run."""
import math
import re


DEFAULT_REGION = 'ap-southeast-1'
ROLES = ('frontend', 'backend', 'integration')
ARMS = {'control', 'coopagents'}
_ALIAS = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
_SHA = re.compile(r'^[0-9a-f]{40}$')
_FINGERPRINT = re.compile(r'^[0-9a-f]{64}$')


def _alias(value, field):
    if not isinstance(value, str) or not _ALIAS.fullmatch(value):
        raise ValueError('Invalid ' + field)
    return value


def validate_manifest(value):
    """Validate a secret-free run manifest and return only approved fields."""
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('Expected run manifest schema_version 1')
    run_id = _alias(value.get('run_id'), 'run_id')
    source_commit = value.get('source_commit')
    if not isinstance(source_commit, str) or not _SHA.fullmatch(source_commit):
        raise ValueError('Invalid source commit')
    for name in ('dsh_version', 'os_image', 'scenario_seed'):
        _alias(value.get(name), name)
    fingerprint = value.get('model_config_fingerprint')
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError('Invalid model configuration fingerprint')
    cost = value.get('cost_limit_usd')
    timeout = value.get('timeout_seconds')
    if type(cost) not in (int, float) or not math.isfinite(cost) or cost <= 0:
        raise ValueError('Cost limit must be a positive finite number')
    if type(timeout) is not int or timeout <= 0:
        raise ValueError('Timeout must be a positive integer')
    arms = value.get('arm_order')
    if not isinstance(arms, list) or len(arms) != 2 or set(arms) != ARMS:
        raise ValueError('Arm order must contain control and coopagents exactly once')
    roles = value.get('roles')
    if not isinstance(roles, dict) or set(roles) != set(ROLES):
        raise ValueError('Exactly frontend, backend and integration roles are required')
    projected_roles = {}
    for role in ROLES:
        entry = roles[role]
        if not isinstance(entry, dict):
            raise ValueError('Invalid role identity')
        projected_roles[role] = {field: _alias(entry.get(field), field)
                                  for field in ('member_alias', 'vm_alias', 'nat_alias')}
    for field in ('member_alias', 'vm_alias', 'nat_alias'):
        values = [entry[field] for entry in projected_roles.values()]
        if len(set(values)) != len(ROLES):
            raise ValueError('Role ' + field + ' identities must be distinct')
    region = value.get('region', DEFAULT_REGION)
    region = _alias(region, 'region')
    return {
        'schema_version': 1,
        'run_id': run_id,
        'source_commit': source_commit,
        'dsh_version': value['dsh_version'],
        'os_image': value['os_image'],
        'model_config_fingerprint': fingerprint,
        'scenario_seed': value['scenario_seed'],
        'arm_order': list(arms),
        'cost_limit_usd': float(cost),
        'timeout_seconds': timeout,
        'region': region,
        'roles': projected_roles,
    }
