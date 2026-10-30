"""Bounded activity projection from structured project state; never project agent transcripts."""
from datetime import datetime, timezone
from urllib.parse import urlsplit


MAX_ITEMS = 100
MAX_SOURCE_ITEMS = 200
MAX_SUMMARY = 280


def _when(value):
    if not isinstance(value, str) or not value or len(value) > 50:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except ValueError:
        return None


def _text(value, limit=MAX_SUMMARY):
    if not isinstance(value, str):
        return ''
    return value[:limit]


def _release_url(value):
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and url.hostname == 'github.com' and url.username is None
                and url.password is None and url.port is None and not url.query and not url.fragment
                and len(url.path.split('/')) == 6 and url.path.startswith('/')
                and url.path.split('/')[3] == 'releases' and url.path.split('/')[4] == 'tag')
    except ValueError:
        return False


def _item(identifier, kind, occurred_at, source, summary, actor=None, task_id=None, reference=None):
    when = _when(occurred_at)
    if when is None:
        return None
    return {'id': _text(str(identifier), 100), 'type': kind, 'occurred_at': when,
            'actor_member_id': _text(actor, 100) or None,
            'task_id': task_id if type(task_id) is int and task_id > 0 else None,
            'source': source, 'summary': _text(summary), 'reference': reference}


def project_activity(snapshot, limit=MAX_ITEMS):
    """Project only structured collaboration facts into a stable, bounded timeline."""
    if type(limit) is not int or not 1 <= limit <= MAX_ITEMS:
        raise ValueError('Activity limit must be between 1 and 100')
    if not isinstance(snapshot, dict):
        raise ValueError('Activity source must be a snapshot object')
    items = []

    tasks = snapshot.get('tasks', [])
    if isinstance(tasks, list):
        for row in tasks[:MAX_SOURCE_ITEMS]:
            if not isinstance(row, dict):
                continue
            title = _text(row.get('title'), 200)
            task_id = row.get('id')
            if type(task_id) is int and task_id > 0 and title:
                items.append(_item('task:'+str(task_id), 'task_created', row.get('created_at'),
                    'task', 'Task created: '+title, row.get('creator_member_id'), task_id,
                    {'scope': _text(row.get('scope'), 250)}))

    progress = snapshot.get('progress', [])
    if isinstance(progress, list):
        for row in progress[:MAX_SOURCE_ITEMS]:
            if not isinstance(row, dict):
                continue
            summary = _text(row.get('summary'))
            if summary:
                items.append(_item('progress:'+str(row.get('task_id', '')), 'progress_reported',
                    row.get('updated_at'), 'agent_report', summary, row.get('member_id'), row.get('task_id')))

    lifecycle = snapshot.get('lifecycle', {})
    history = lifecycle.get('history', []) if isinstance(lifecycle, dict) else []
    if isinstance(history, list):
        for row in history[:MAX_SOURCE_ITEMS]:
            if not isinstance(row, dict):
                continue
            action = row.get('action')
            if action not in ('claim_task', 'release_task', 'propose_handoff', 'accept_handoff',
                              'reject_handoff', 'force_handoff', 'cancel_task', 'reopen_task'):
                continue
            summary = _text(row.get('summary'))
            if summary:
                items.append(_item('lifecycle:'+str(row.get('id', '')), action, row.get('created_at'),
                    'task_lifecycle', summary, row.get('actor_member_id'), row.get('task_id')))

    sessions = snapshot.get('sessions', [])
    if isinstance(sessions, list):
        for row in sessions[:MAX_SOURCE_ITEMS]:
            if not isinstance(row, dict):
                continue
            tool = row.get('tool')
            if tool not in ('claude-code', 'codex-cli', 'codex-desktop', 'cursor', 'opencode', 'pi', 'kimi-code', 'zcode'):
                continue
            summary = 'Session registered for '+tool
            items.append(_item('session:'+str(row.get('id', '')), 'session_registered',
                row.get('updated_at'), 'session_registry', summary, row.get('member_id'), row.get('task_id'),
                {'tool': tool, 'branch': _text(row.get('branch'), 250)}))

    requests = snapshot.get('requests', [])
    if isinstance(requests, list):
        for row in requests[:MAX_SOURCE_ITEMS]:
            if not isinstance(row, dict):
                continue
            request_id = row.get('id')
            task_id = row.get('task_id')
            reference = {'request_id': request_id if type(request_id) is int and request_id > 0 else None}
            base_summary = 'Collaboration request'
            created = _item('request:'+str(request_id), 'request_sent', row.get('created_at'),
                'collaboration_request', base_summary, row.get('sender_member_id'), task_id, reference)
            if created:
                items.append(created)
            for field, event_type, actor_field, summary in (
                ('read_at', 'request_read', 'receiver_member_id', 'Request read'),
                ('processed_at', 'request_processed', 'receiver_member_id', 'Request acknowledged'),
                ('resolved_at', 'request_resolved', 'receiver_member_id', 'Request resolved'),
            ):
                event = _item('request:'+str(request_id)+':'+field, event_type, row.get(field),
                    'collaboration_request', summary, row.get(actor_field), task_id, reference)
                if event:
                    items.append(event)
            replies = row.get('replies', [])
            if isinstance(replies, list):
                for reply in replies[:MAX_SOURCE_ITEMS]:
                    if isinstance(reply, dict):
                        event = _item('reply:'+str(reply.get('id', '')), 'reply_sent', reply.get('created_at'),
                            'collaboration_reply', 'Reply sent', reply.get('author_member_id'), task_id, reference)
                        if event:
                            items.append(event)

    contracts = snapshot.get('events', [])
    if isinstance(contracts, list):
        for row in contracts[:MAX_SOURCE_ITEMS]:
            if not isinstance(row, dict):
                continue
            event_type = row.get('event_type')
            if event_type not in ('proposed', 'approved', 'rejected'):
                continue
            summary = {'proposed': 'Contract proposed', 'approved': 'Contract approved',
                       'rejected': 'Contract rejected'}[event_type]
            items.append(_item('contract:'+str(row.get('id', '')), 'contract_'+event_type,
                row.get('created_at'), 'contract_event', summary, row.get('actor_member_id'), task_id=None,
                reference={'contract_id': row.get('contract_id') if type(row.get('contract_id')) is int else None,
                           'version': row.get('version') if type(row.get('version')) is int else None}))

    git = snapshot.get('git', {})
    if isinstance(git, dict):
        observations = git.get('events', [])
        if isinstance(observations, list):
            for row in observations[:MAX_SOURCE_ITEMS]:
                if not isinstance(row, dict):
                    continue
                items.append(_item('git-observation:'+str(row.get('id', '')), 'git_observed',
                    row.get('captured_at'), 'local_git',
                    'Local Git checkpoint observed', row.get('member_id'), row.get('task_id'),
                    {'branch': _text(row.get('branch'), 250), 'head': _text(row.get('head'), 64)}))
        deliveries = git.get('deliveries', [])
        if isinstance(deliveries, list):
            for row in deliveries[:MAX_SOURCE_ITEMS]:
                if not isinstance(row, dict) or row.get('source') != 'github_verified':
                    continue
                kind = 'release_verified' if row.get('release_id') is not None else 'github_delivery_verified'
                summary = 'GitHub release '+_text(row.get('tag_name'), 100)+' '+_text(row.get('state'), 40) if kind == 'release_verified' else 'GitHub delivery '+_text(row.get('state'), 40)
                reference = {key: row[key] for key in ('release_id', 'tag_name', 'state', 'pr_number', 'branch', 'commit_sha', 'stale')
                             if key in row}
                if row.get('state') == 'unavailable':
                    reference['unavailable'] = True
                if _release_url(row.get('url')):
                    reference['url'] = row['url']
                items.append(_item('github:'+str(row.get('ref_id', row.get('release_id', ''))), kind,
                    row.get('sync_at'), 'github_verified', summary, None, row.get('task_id'), reference))

    items = [item for item in items if item]
    items.sort(key=lambda item: (item['occurred_at'], item['source'], item['id']), reverse=True)
    return {'items': items[:limit], 'truncated': len(items) > limit, 'limit': limit}
