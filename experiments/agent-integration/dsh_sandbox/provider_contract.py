"""Validate synthetic/provider-exported inventory without contacting a provider.

This module reports contract defects, not observed network or native acceptance.
Diagnostics name fields and positional aliases only; they never echo inventory values.
"""

from datetime import datetime
from ipaddress import ip_address
from collections.abc import Mapping


PROFILE_UDP = {
    'direct': {'peer_udp': True, 'relay_udp': True},
    'relay-only': {'peer_udp': False, 'relay_udp': True},
    'udp-blocked': {'peer_udp': False, 'relay_udp': False},
}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value):
    if not _text(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_inventory(inventory):
    """Return safe field-level errors; an empty list means contract-valid only.

    ``agents`` contains exactly three member VMs. Their ``public_ip`` fields are
    NAT egress observations, never VM inbound addresses. See provider_contract.md.
    No files, network connections, credentials or cloud SDKs are used.
    """
    errors = []
    if not isinstance(inventory, Mapping):
        return ['inventory must be an object']
    run_id = inventory.get('run_id')
    if not _text(run_id):
        errors.append('run_id is required')
    agents = inventory.get('agents')
    if not isinstance(agents, list):
        return errors + ['agents must be an array of three agent records']
    if len(agents) != 3:
        errors.append('agents must contain exactly three agent records')

    unique_fields = ('agent_id', 'egress_network_id', 'public_ip', 'subnet_id')
    seen = {key: set() for key in unique_fields}
    for index, agent in enumerate(agents):
        prefix = f'agents[{index}]'
        if not isinstance(agent, Mapping):
            errors.append(f'{prefix} must be an object')
            continue
        for field in unique_fields:
            value = agent.get(field)
            if not _text(value):
                errors.append(f'{prefix}.{field} is required')
                continue
            canonical = value.strip()
            if field == 'public_ip':
                try:
                    canonical = str(ip_address(value))
                except ValueError:
                    errors.append(f'{prefix}.public_ip must be an IP address')
                    continue
            if canonical in seen[field]:
                errors.append(f'{prefix}.{field} must be unique across agents')
            seen[field].add(canonical)

        # All unsolicited public ingress is prohibited, including SSH and RDP.
        if agent.get('inbound_ports') != []:
            errors.append(f'{prefix}.inbound_ports must be an empty array')
        if agent.get('public_control_endpoint') is not False:
            errors.append(f'{prefix}.public_control_endpoint must be false')

        profile = agent.get('network_profile')
        expected = PROFILE_UDP.get(profile) if isinstance(profile, str) else None
        policy = agent.get('network_policy')
        if expected is None:
            errors.append(f'{prefix}.network_profile must be direct, relay-only or udp-blocked')
        elif not isinstance(policy, Mapping) or any(
                policy.get(key) is not value for key, value in expected.items()):
            errors.append(f'{prefix}.network_policy does not match network_profile')

        lifecycle = agent.get('lifecycle')
        if not isinstance(lifecycle, Mapping):
            errors.append(f'{prefix}.lifecycle metadata is required')
        else:
            for field in ('instance_id', 'state'):
                if not _text(lifecycle.get(field)):
                    errors.append(f'{prefix}.lifecycle.{field} is required')
            if lifecycle.get('run_id') != run_id or not _text(run_id):
                errors.append(f'{prefix}.lifecycle.run_id must match current run_id')
            times = {field: _timestamp(lifecycle.get(field))
                     for field in ('created_at', 'expires_at')}
            for field, timestamp in times.items():
                if timestamp is None:
                    errors.append(f'{prefix}.lifecycle.{field} must be a timezone-aware timestamp')
            if all(times.values()) and times['expires_at'] <= times['created_at']:
                errors.append(f'{prefix}.lifecycle.expires_at must follow created_at')
            action = lifecycle.get('deallocation')
            if not isinstance(action, Mapping):
                errors.append(f'{prefix}.lifecycle.deallocation metadata is required')
            else:
                if action.get('run_id') != run_id or not _text(run_id):
                    errors.append(f'{prefix}.lifecycle.deallocation.run_id must match current run_id')
                if action.get('mode') not in ('stop', 'deallocate'):
                    errors.append(f'{prefix}.lifecycle.deallocation.mode must preserve resources')
                for field in ('preserve_disks', 'preserve_snapshots', 'preserve_evidence',
                              'preview_required'):
                    if action.get(field) is not True:
                        errors.append(f'{prefix}.lifecycle.deallocation.{field} must be true')

        snapshot = agent.get('snapshot')
        if not isinstance(snapshot, Mapping):
            errors.append(f'{prefix}.snapshot metadata is required')
        else:
            for field in ('snapshot_id', 'source_image_id', 'image_digest'):
                if not _text(snapshot.get(field)):
                    errors.append(f'{prefix}.snapshot.{field} is required')
            if _timestamp(snapshot.get('created_at')) is None:
                errors.append(f'{prefix}.snapshot.created_at must be a timezone-aware timestamp')
    return errors
