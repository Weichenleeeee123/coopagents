"""Bounded factual diagnostics. Reading never connects, starts hosts or grants trust."""
from contextlib import closing
from datetime import datetime, timezone
import base64
import json
import math
import os
from pathlib import Path
import re
import sqlite3

from .bridge_event_cache import EVENT_CACHE_FILENAME
from .identity import _expired
from .session_routing import _binding_active, _credential_active, _lease
from .spaces import read_profile

ACTIONS = {
    'refresh_current_responsibility': 'Refresh the current task owner and route before using an answer.',
    'wait_for_owner_assignment': 'Ask the user to clarify responsibility; do not assign or claim it automatically.',
    'review_cancelled_target': 'Review the cancelled target with its owner; do not reopen it automatically.',
    'refresh_current_task': 'Refresh the current task and obtain its current authorized execution.',
    'register_current_execution': 'Register the validated current task execution in the intended native session.',
    'reconnect_personal_credential': 'Reconnect your personal agent credential through the permitted setup flow.',
    'open_correct_native_session': 'Open the intended native session and inspect its actual tools and pending work.',
    'resume_authorized_watcher': 'Review and resume the optional watcher in the correct open native session.',
    'check_local_host_and_connection': 'Inspect the existing host and connection before reconnecting when authorized.',
    'ask_owner_to_check_execution': 'Ask the responsible teammate to inspect its current execution and watcher.',
    'read_reply_explicitly': 'Read the actual latest reply in the intended requester session.',
    'confirm_outcome_when_authorized': 'Review the answer before any separately authorized resolution.',
    'check_current_reply': 'Inspect the current route for a factual reply; keep independent work authorized.',
    'retain_history': 'Keep this historical fact; it does not authorize new work.',
    'verify_native_tools': 'Inspect the actual tool list in the intended native session; configuration is not proof.',
    'review_native_hook_trust': 'Review hook configuration and trust in the native host; do not grant trust here.',
    'verify_current_identity': 'Verify the intended project identity in the actual native session.',
    'select_correct_personal_profile': 'Select the correct existing personal profile before reconnecting.',
    'ask_user_before_starting_host': 'The owner explicitly stopped this host; ask before starting it.',
    'review_owner_host_recovery': 'Ask the owner to inspect blocked host recovery before an explicit retry.',
    'inspect_existing_host': 'Inspect the existing owner host; this policy alone does not prove it is running.',
    'refresh_after_cache_reset': 'Read current authorized project state after the cached cursor reset.',
    'review_cached_changes': 'Cached invalidations are not current authorization or explicit message reads.',
    'review_optional_wake_setup': 'Inspect the optional wake configuration without installing or starting it.',
    'retry_existing_outbox_when_authorized': 'Review queued local operations and retry only through the existing authorized flow.',
}


def _now():
    return datetime.now(timezone.utc)


def _card(component, status, evidence, action, **target):
    return {'component': component, 'status': status, 'evidence': evidence,
            'next_action': {'action': action, 'instruction': ACTIONS[action], **target}}


def _unknowns():
    return [_card(component, 'unknown', {'observed': False}, action) for component, action in (
        ('network', 'check_local_host_and_connection'), ('native_mcp', 'verify_native_tools'),
        ('hook_trust', 'review_native_hook_trust'))]


def _pack(specific, base=(), *, limit=8, budget=2500):
    shown = list(base)
    for item in specific:
        candidate = shown[:-len(base)] + [item] + list(base) if base else shown + [item]
        if len(candidate) <= limit and len(json.dumps(candidate, sort_keys=True).encode()) <= budget:
            shown = candidate
    return {'diagnostics': shown, 'diagnostics_total': len(specific) + len(base),
            'diagnostics_truncated': len(shown) < len(specific) + len(base),
            'read_only': True, 'model_consumption_proven': False}


def _execution(db, p, task, now):
    evidence = {'task_id': task['id'], 'ownership_epoch': task['ownership_epoch'],
                'availability_proven': False}
    previous = db.execute('''SELECT * FROM task_session_routes WHERE room_id=? AND task_id=? AND member_id=?
        ORDER BY updated_at DESC LIMIT 1''', (p.room_id, task['id'], p.member_id)).fetchone()
    if previous and (previous['ownership_epoch'] != task['ownership_epoch']
                     or previous['logical_session_key'] != task['execution_session_key']
                     or previous['member_id'] != task['owner_member_id']):
        return _card('execution', 'execution_retired', evidence, 'refresh_current_task', task_id=task['id'])
    if task['cancelled_at']:
        return _card('execution', 'task_cancelled', evidence, 'review_cancelled_target', task_id=task['id'])
    if not task['owner_member_id']:
        return _card('execution', 'owner_unassigned', evidence, 'wait_for_owner_assignment', task_id=task['id'])
    own = task['owner_member_id'] == p.member_id
    binding = db.execute('''SELECT * FROM task_session_routes WHERE room_id=? AND task_id=?
        AND member_id=? AND ownership_epoch=? AND logical_session_key=?''',
        (p.room_id, task['id'], task['owner_member_id'], task['ownership_epoch'], task['execution_session_key'])).fetchone()
    action = 'register_current_execution' if own else 'ask_owner_to_check_execution'
    if not task['execution_session_key']:
        return _card('execution', 'execution_unbound', evidence, 'refresh_current_task' if own else action, task_id=task['id'])
    if not binding:
        return _card('execution', 'native_alias_missing', evidence, action, task_id=task['id'])
    evidence['alias_reported'] = True
    if not _credential_active(db, binding['credential_hash'], binding['member_id'], p.room_id, now):
        return _card('execution', 'credential_unavailable', evidence, 'reconnect_personal_credential' if own else action, task_id=task['id'])
    presence = _lease(db, binding)
    if not presence:
        return _card('execution', 'watcher_unobserved', evidence, 'open_correct_native_session' if own else action, task_id=task['id'])
    evidence.update(state=presence['state'], updated_at=presence['updated_at'], expires_at=presence['expires_at'])
    if presence['state'] == 'stopped':
        return _card('execution', 'watcher_stopped', evidence, 'resume_authorized_watcher' if own else action, task_id=task['id'])
    if _expired(presence['expires_at'], now):
        return _card('execution', 'watcher_stale', evidence, 'check_local_host_and_connection' if own else action, task_id=task['id'])
    if not _binding_active(db, binding, now):
        return _card('execution', 'watcher_mismatch', evidence, action, task_id=task['id'])
    return _card('execution', 'watcher_lease_active', evidence, 'open_correct_native_session' if own else action, task_id=task['id'])


def server_diagnostics(db, p, *, requests=(), owner_questions=(), tasks=(), task_id=None):
    """Project stable business facts from the caller's existing SQLite snapshot."""
    now = _now()
    specific = []
    task = next((t for t in tasks if t['id'] == task_id), None) if task_id is not None else next(
        (t for t in tasks if t['owner_member_id'] == p.member_id and not t['cancelled_at']), None)
    if task:
        specific.append(_execution(db, p, task, now))
    for queue in owner_questions:
        cancelled = queue['wait_reason'] == 'target_cancelled'
        specific.append(_card('owner_question', 'target_cancelled' if cancelled else 'owner_unassigned',
            {'target_task_id': queue['target_task_id'], 'route_version': queue['route_version'],
             'delivered': False, 'created_at': queue['created_at']},
            'review_cancelled_target' if cancelled else 'wait_for_owner_assignment', task_id=queue['target_task_id']))
    for request in requests:
        state = request['route_state']
        status, action = (
            ('historical_route', 'refresh_current_responsibility') if state == 'historical' else
            ('resolved', 'retain_history') if request['resolved'] or state == 'closed' else
            ('queued', 'wait_for_owner_assignment') if not request['delivered'] else
            ('reply_unread', 'read_reply_explicitly') if request['replied'] and not request['sender_reply_read'] else
            ('reply_read_waiting_confirmation', 'confirm_outcome_when_authorized') if request['replied'] else
            ('processing_reported', 'check_current_reply') if request['processing'] else
            ('recipient_read_no_reply', 'check_current_reply') if request['recipient_read'] else
            ('delivered_unread', 'open_correct_native_session'))
        evidence = {k: request[k] for k in ('delivered', 'recipient_read', 'processing', 'replied',
            'sender_reply_read', 'resolved', 'route_state', 'latest_reply_id')}
        evidence['request_id'] = request['id']
        for key in ('recipient_read_at', 'processed_at', 'resolved_at'):
            if request.get(key):
                evidence[key] = request[key]
        specific.append(_card('message', status, evidence, action, request_id=request['id']))
    base = [_card('identity', 'authenticated', {'principal_kind': p.kind}, 'verify_current_identity'), *_unknowns()]
    return _pack(specific, base)


def _json_file(path):
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError()
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError()
    return value


def _readonly(path, reader):
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        return reader(db)


def _cache_card(path, profile):
    try:
        def inspect(db):
            row = db.execute('SELECT room,member,cursor,floor,reset FROM state LIMIT 1').fetchone()
            if not row or not profile or (row['room'], row['member']) != (profile['room_id'], profile['member_id']):
                return _card('event_cache', 'identity_mismatch', {'identity_matches': False}, 'select_correct_personal_profile')
            evidence = {'identity_matches': True, 'cached_events': db.execute('SELECT COUNT(*) FROM events').fetchone()[0]}
            for field in ('cursor', 'floor'):
                if type(row[field]) is int and 0 <= row[field] < 2**63:
                    evidence[field] = row[field]
            reset = row['reset'] in ('future_cursor', 'expired_cursor', 'local_cache_expired')
            evidence['reset_required'] = reset
            return _card('event_cache', 'reset_required' if reset else 'cached_only', evidence,
                         'refresh_after_cache_reset' if reset else 'review_cached_changes')
        return _readonly(path, inspect) or _card('event_cache', 'unknown', {'state_file_exists': False}, 'review_cached_changes')
    except (OSError, ValueError, sqlite3.Error):
        return _card('event_cache', 'unknown', {'state_readable': False}, 'review_cached_changes')


def _watcher_card(path):
    try:
        def inspect(db):
            rows = db.execute('SELECT tool,status,seen FROM watchers ORDER BY seen DESC LIMIT 6').fetchall()
            evidence = {'reported_watchers': db.execute('SELECT COUNT(*) FROM watchers').fetchone()[0],
                        'availability_proven': False}
            if not rows:
                return _card('watcher', 'unknown', evidence, 'review_optional_wake_setup')
            row = rows[0]
            status = 'unknown'
            seen = row['seen']
            if type(seen) in (int, float) and math.isfinite(seen) and 0 <= seen < 2**38:
                when = datetime.fromtimestamp(seen, timezone.utc)
                evidence['last_observed_at'] = when.isoformat()
                if row['status'] in ('stopped', 'owner_exited', 'gone'):
                    status = 'stopped'
                elif when <= _now() and (_now() - when).total_seconds() >= 90:
                    status = 'stale'
                elif when <= _now() and row['status'] == 'watching':
                    status = 'watching_reported'
            return _card('watcher', status, evidence,
                         'resume_authorized_watcher' if status == 'stopped' else 'check_local_host_and_connection')
        return _readonly(path, inspect) or _card('watcher', 'unknown', {'state_file_exists': False}, 'review_optional_wake_setup')
    except (OSError, ValueError, OverflowError, sqlite3.Error):
        return _card('watcher', 'unknown', {'state_readable': False}, 'review_optional_wake_setup')


def _managed_hook(value, depth=0):
    if depth > 12:
        return False
    if isinstance(value, dict):
        return any(_managed_hook(v, depth + 1) for v in list(value.values())[:100])
    if isinstance(value, list):
        return any(_managed_hook(v, depth + 1) for v in value[:100])
    if isinstance(value, str) and len(value) <= 32768:
        if any(marker in value for marker in ('coopagents.space_wake', 'coopagents.checkpoint_hook')):
            return True
        encoded = re.search(r'-EncodedCommand\s+([A-Za-z0-9+/=]+)', value, re.I)
        if encoded:
            try:
                return _managed_hook(base64.b64decode(encoded[1], validate=True).decode('utf-16-le'), depth + 1)
            except (ValueError, UnicodeError):
                pass
    return False


def local_diagnostics(profile_path, transport_status=None, *, observed_at=None, outbox=None,
                      event_cache_path=None, wake_state_path=None, native_host_policy_path=None,
                      tool=None, project_dir=None, hook_paths=None):
    """Read existing local files only. Never ensure a host, connect or initialize state."""
    path = Path(profile_path).expanduser().absolute()
    profile = None
    try:
        profile = read_profile(path)
    except (OSError, ValueError, TypeError):
        pass
    known_transport = ('online', 'connecting', 'reconnecting', 'disconnected', 'offline', 'degraded', 'denied', 'auth_denied', 'stopped')
    transport = transport_status if isinstance(transport_status, str) and transport_status in known_transport else 'unknown'
    denied = transport in ('denied', 'auth_denied')
    cards = [_card('identity', 'rejected' if denied else 'local_profile_present' if profile else 'unknown',
                   {'profile_present': profile is not None, 'remote_identity_verified': False},
                   'reconnect_personal_credential' if denied else 'verify_current_identity')]
    transport_evidence = {'transport_status': transport, 'model_consumption_proven': False}
    if isinstance(observed_at, str):
        try:
            parsed = datetime.fromisoformat(observed_at)
            if parsed.tzinfo is not None:
                transport_evidence['observed_at'] = parsed.isoformat()
        except ValueError:
            pass
    elif type(observed_at) in (int, float) and math.isfinite(observed_at) and 0 <= observed_at < 2**38:
        try:
            transport_evidence['observed_at'] = datetime.fromtimestamp(observed_at, timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    cards.append(_card('transport', transport, transport_evidence,
                       'reconnect_personal_credential' if denied else 'check_local_host_and_connection'))
    try:
        host = _json_file(Path(native_host_policy_path) if native_host_policy_path else path.with_name('native-host.json'))
        if (not profile or not profile.get('control_token') or host.get('schema_version') != 1
                or (host.get('room_id'), host.get('member_id')) != (profile['room_id'], profile['member_id'])
                or type(host.get('desired_running')) is not bool or type(host.get('blocked')) is not bool):
            raise ValueError()
        status, action = ('stopped_by_user', 'ask_user_before_starting_host') if not host['desired_running'] else (
            ('recovery_blocked', 'review_owner_host_recovery') if host['blocked'] else ('policy_present', 'inspect_existing_host'))
        cards.append(_card('host_policy', status, {k: host[k] for k in ('desired_running', 'blocked')}, action))
    except (OSError, ValueError, TypeError):
        cards.append(_card('host_policy', 'unknown', {'policy_observed': False}, 'inspect_existing_host'))
    cards.append(_cache_card(Path(event_cache_path) if event_cache_path else path.with_name(EVENT_CACHE_FILENAME), profile))
    cards.append(_watcher_card(Path(wake_state_path) if wake_state_path else path.with_name('wake-state.sqlite3')))
    if hook_paths is None:
        hook_paths = []
        if tool:
            from .wake_hook_settings import TOOLS, normalize_tool, settings_path
            try:
                normalized = normalize_tool({'codex-cli': 'codex', 'claude-code': 'claude'}.get(tool, tool))
                for scope in ('project', 'user') if normalized in TOOLS else ():
                    if scope == 'project' and not project_dir:
                        continue
                    if scope == 'project' and normalized == 'zcode':
                        continue
                    try:
                        override = os.environ.get('CODEX_HOME' if normalized == 'codex' else 'CLAUDE_CONFIG_DIR') if scope == 'user' and normalized in ('codex', 'claude') else None
                        hook_paths.append(Path(override) / ('hooks.json' if normalized == 'codex' else 'settings.json')
                                          if override else settings_path(normalized, scope, project_dir))
                    except ValueError:
                        pass
            except (ValueError, TypeError):
                pass
    inspected, configured = 0, False
    for hook in list(hook_paths)[:4]:
        try:
            document = _json_file(Path(hook))
            inspected += 1
            configured = configured or _managed_hook(document.get('hooks', {}))
        except (OSError, ValueError, TypeError):
            pass
    cards.append(_card('hooks_configuration', 'configuration_present' if configured else 'unknown',
                       {'files_inspected': inspected, 'managed_configuration_present': configured,
                        'execution_verified': False}, 'review_native_hook_trust'))
    cards.extend([_card('hook_trust', 'unknown', {'trust_observed': False}, 'review_native_hook_trust'),
                  _card('native_mcp', 'unknown', {'loaded_in_session': None}, 'verify_native_tools')])
    if isinstance(outbox, dict):
        source = outbox.get('counts', {})
        counts = {k: source[k] for k in ('queued_locally', 'blocked', 'synced_to_service')
                  if isinstance(source, dict) and type(source.get(k)) is int and 0 <= source[k] < 2**31}
        cards.append(_card('outbox', 'blocked' if counts.get('blocked') else 'queued_locally' if counts.get('queued_locally') else 'counts_observed',
                           counts, 'retry_existing_outbox_when_authorized'))
    return _pack(cards, limit=12, budget=5000)
