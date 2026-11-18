"""Business-read-only collaboration recovery with private frozen delta caches."""
from dataclasses import asdict
import hashlib
import json

from .errors import ValidationError
from .task_lifecycle import execution_task, manager, project_task, task_row
from .workflow import queued_owner_questions, request_route_info
from .brief_deltas import BriefDeltaStore, item_key
from .workflow_diagnostics import server_diagnostics

MAX_BYTES = 16000
KINDS = {'task': 'tasks', 'dependency': 'dependencies', 'request': 'requests',
         'owner_question': 'owner_questions',
         'agreement': 'agreements', 'agreement_change': 'agreement_changes',
         'decision': 'decisions', 'member_activity': 'member_activity'}


def schemas():
    return {
        'read_workflow': {'task_id': (int, False, None)},
        'work_brief': {'task_id': (int, False, None), 'session_key': (str, False, None),
                       'ownership_epoch': (int, False, None), 'after_cursor': (str, False, None),
                       'limit': (int, False, 20)},
    }


def _json(value):
    # ASCII escaping is a conservative size bound for both HTTP and MCP JSON.
    return json.dumps(value, sort_keys=True)


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _clip(value, maximum=160):
    if isinstance(value, str):
        return value[:maximum]
    if isinstance(value, list):
        return [_clip(v, maximum) for v in value]
    if isinstance(value, dict):
        exact = {'session_key', 'execution_session_key', 'member_id', 'room_id',
                 'owner_member_id', 'sender_member_id', 'receiver_member_id',
                  'target_member_id', 'source_owner_member_id', 'target_owner_member_id',
                  'question_key', 'requester_member_id'}
        result = {k: v if k in exact else _clip(v, maximum) for k, v in value.items()}
        if any(isinstance(v, str) and len(v) > maximum for v in value.values()):
            result['excerpted'] = True
        return result
    return value


class TeamWorkflowStore:
    def __init__(self, service):
        self.service, self.identity, self.db = service, service.identity, service.identity.db
        self.delta_cache = BriefDeltaStore(self.db)

    def read_workflow(self, token, task_id=None):
        with self.db.connect() as db:
            db.execute('BEGIN')
            p = self.identity.resolve(db, token)
            if task_id is not None:
                task_row(db, p, task_id)
            records, meta, _ = self._collect(db, p, task_id, personal=False)
            result = {**meta, **{name: [] for name in KINDS.values()}, 'truncated': False,
                      'has_more': False, 'limit': 50,
                      'detail_actions': ['read_team', 'read_dependency', 'read_replies']}
            # This overview has no page cursor: sample every nonempty category
            # before filling remaining space so a large task list cannot hide work.
            priority = ('request', 'owner_question', 'agreement_change', 'decision', 'dependency',
                        'agreement', 'task', 'member_activity')
            groups = {category: [r for kind, r in records if kind == category] for category in priority}
            groups['request'].sort(key=lambda r: bool(r['resolved'] or r['route_state'] == 'historical'))
            groups['agreement_change'].sort(key=lambda r: not r['review_required'])
            ordered = [(category, groups[category][index])
                       for index in range(max((len(g) for g in groups.values()), default=0))
                       for category in priority if index < len(groups[category])]
            represented = sum(bool(group) for group in groups.values())
            for maximum in (160, 80, 40, 32):
                for name in KINDS.values():
                    result[name] = []
                for category, record in ordered[:represented]:
                    result[KINDS[category]].append(_clip(record, maximum))
                result['truncated'] = result['has_more'] = represented < len(records)
                if len(_json(result).encode()) <= MAX_BYTES:
                    break
            for category, record in ordered[represented:]:
                shown = sum(len(result[name]) for name in KINDS.values())
                if shown == result['limit']:
                    break
                collection = result[KINDS[category]]
                collection.append(_clip(record))
                result['truncated'] = result['has_more'] = shown + 1 < len(records)
                if len(_json(result).encode()) > MAX_BYTES:
                    collection.pop()
                    result['truncated'] = result['has_more'] = True
            return result

    def work_brief(self, token, task_id=None, session_key=None, ownership_epoch=None,
                   after_cursor=None, limit=20):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValidationError('Limit must be an integer from 1 to 50')
        if task_id is None and (session_key is not None or ownership_epoch is not None):
            raise ValidationError('Execution fields require task_id')
        with self.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, required_kind='agent')
            # Validate before inspecting a cursor, including the unchanged path.
            task = execution_task(db, p, task_id, session_key, ownership_epoch) if task_id is not None else None
            target = ({'task_id': task_id, 'session_key': task['execution_session_key'],
                       'ownership_epoch': task['ownership_epoch']} if task else None)
            binding = _hash([p.room_id, p.member_id, task_id, session_key, ownership_epoch, limit])
            return self.delta_cache.read(db, binding, after_cursor, limit,
                lambda: self._delta_state(db, p, task_id, target))

    def _delta_state(self, db, p, task_id, target):
        records, meta, semantic = self._collect(db, p, task_id, personal=True)
        item_budget = MAX_BYTES - len(_json({**meta, 'execution_target': target}).encode()) - 1200
        state = {}
        for kind, record in records:
            key = item_key(kind, record)
            raw = {'record': record}
            if kind == 'request':
                replies = [r for r in semantic['replies'] if r['request_id'] == record['id']]
                reply_ids = {r['id'] for r in replies}
                raw.update(source=next(r for r in semantic['requests'] if r['id'] == record['id']), replies=replies,
                    reads=[r for r in semantic['reads'] if r['reply_id'] in reply_ids],
                    dependency_reads=[r for r in semantic['dependency_reads'] if r['dependency_id'] == record['dependency_id']])
            elif kind == 'agreement_change':
                version = db.execute('''SELECT * FROM contract_versions WHERE room_id=? AND contract_id=? AND version=?''',
                    (p.room_id, record['contract_id'], record['effective_version'])).fetchone()
                raw['source_version'] = dict(version) if version else None
            for maximum in (160, 80, 40, 32):
                clipped = _clip(record, maximum)
                item = ({'kind': kind, 'decision': clipped} if kind == 'decision' else {**clipped, 'kind': kind})
                item['item_key'] = key
                if clipped != record or record.get('excerpted') or record.get('replies_truncated'):
                    item.update(excerpted=True, source_read={'operation': 'read_team', 'item_key': key,
                        'note': 'Excerpt only; inspect the original source record before acting.'})
                if len(_json(item).encode()) <= item_budget:
                    break
            state[key] = {'hash': _hash(raw), 'item': item}
        return state, {**meta, 'execution_target': target}

    @staticmethod
    def _member_fallback(db, p, request, tasks, related_ids, route_map):
        if request['resolved_at'] or request['id'] in route_map:
            return False
        owner = request_route_info(db, request['id'])
        if owner and not owner['current']:
            return False
        if owner and request['sender_member_id'] == p.member_id:
            return True  # An owner-only question has no source execution task.
        known = tasks.get(request['task_id'])
        if known and known['owner_member_id'] == p.member_id and known['id'] not in related_ids:
            return False
        if request['receiver_member_id'] == p.member_id:
            return not db.execute('SELECT 1 FROM message_receipts WHERE request_id=?', (request['id'],)).fetchone()
        if request['sender_member_id'] == p.member_id:
            return bool(db.execute('''SELECT 1 FROM message_replies y WHERE y.request_id=?
                AND NOT EXISTS(SELECT 1 FROM workflow_reply_reads rr WHERE rr.reply_id=y.id AND rr.member_id=?)''',
                (request['id'], p.member_id)).fetchone())
        return False

    def _collect(self, db, p, task_id, *, personal):
        """All identities, authority and source facts are read through this db."""
        def rows(sql, values=()):
            return [dict(r) for r in db.execute(sql, values)]

        all_tasks = rows('SELECT * FROM tasks WHERE room_id=? ORDER BY id', (p.room_id,))
        task_map = {t['id']: t for t in all_tasks}
        all_deps = rows('SELECT * FROM task_dependencies WHERE room_id=? ORDER BY id', (p.room_id,))
        focus_ids = ({task_id} if task_id is not None else
                     {t['id'] for t in all_tasks if t['owner_member_id'] == p.member_id} if personal else None)
        deps = [d for d in all_deps if focus_ids is None or d['source_task_id'] in focus_ids or d['target_task_id'] in focus_ids]
        related_ids = None if focus_ids is None else focus_ids | {d[k] for d in deps for k in ('source_task_id', 'target_task_id')}
        tasks = [t for t in all_tasks if related_ids is None or t['id'] in related_ids]
        routes = rows('''SELECT x.* FROM dependency_routes x JOIN task_dependencies d ON d.id=x.dependency_id
                         WHERE d.room_id=? ORDER BY x.request_id''', (p.room_id,))
        route_map = {r['request_id']: r for r in routes}
        dep_map = {d['id']: d for d in deps}
        requests = rows('SELECT * FROM message_requests WHERE room_id=? ORDER BY id DESC', (p.room_id,))
        owner_questions = queued_owner_questions(db, p)
        if task_id is not None and not personal:
            owner_questions = [q for q in owner_questions if q['target_task_id'] == task_id]
        owner_questions = [{**q, 'status': 'queued' if q['wait_reason'] == 'awaiting_owner' else 'blocked'}
                           for q in owner_questions]
        fallback_ids = {r['id'] for r in requests if personal and task_id is not None
                        and self._member_fallback(db, p, r, task_map, related_ids, route_map)}
        if focus_ids is not None:
            requests = [r for r in requests if r['task_id'] in focus_ids
                        or route_map.get(r['id'], {}).get('dependency_id') in dep_map
                        or r['id'] in fallback_ids
                        or task_id is None and p.member_id in (r['sender_member_id'], r['receiver_member_id'])]
        request_ids = {r['id'] for r in requests}
        replies = rows('SELECT * FROM message_replies WHERE room_id=? ORDER BY id', (p.room_id,))
        replies = [r for r in replies if r['request_id'] in request_ids]
        reads = rows('SELECT * FROM workflow_reply_reads WHERE room_id=? ORDER BY reply_id', (p.room_id,))
        reply_reads = {(r['member_id'], r['reply_id']): r['read_at'] for r in reads}
        receipts = rows('SELECT * FROM message_receipts WHERE room_id=? ORDER BY request_id', (p.room_id,))
        receipt_map = {r['request_id']: r for r in receipts}
        deliveries = rows('SELECT * FROM message_deliveries WHERE room_id=? ORDER BY id', (p.room_id,))
        delivered = {r['request_id'] for r in deliveries}
        dependency_reads = rows('''SELECT r.* FROM dependency_reads r JOIN task_dependencies d ON d.id=r.dependency_id
                                   WHERE d.room_id=? ORDER BY r.dependency_id,r.member_id''', (p.room_id,))
        by_request = {}
        for reply in replies:
            by_request.setdefault(reply['request_id'], []).append(reply)
        request_items = [self._request(r, by_request.get(r['id'], []), receipt_map.get(r['id']),
                         r['id'] in delivered, route_map.get(r['id']), dep_map, reply_reads,
                         dependency_reads, p, task_map, request_route_info(db, r['id'])) for r in requests]
        for item in request_items:
            if item['id'] in fallback_ids and item['task_id'] not in focus_ids:
                item['brief_scope'] = 'member_pending'
        for question in owner_questions:
            if personal and task_id is not None and question['target_task_id'] not in related_ids:
                question['brief_scope'] = 'member_pending'
        dependency_items = []
        request_states = {r['id']: r['route_state'] for r in request_items}
        for dep in deps:
            source, target = task_map[dep['source_task_id']], task_map[dep['target_task_id']]
            dependency_items.append({**dep, 'source_title': source['title'], 'target_title': target['title'],
                'source_owner_member_id': source['owner_member_id'], 'target_owner_member_id': target['owner_member_id'],
                'route_state': request_states.get(dep['current_request_id'], 'historical'),
                'next_actions': [{'operation': 'read_dependency', 'arguments': {'dependency_id': dep['id']}}]})
        uses = self.service.agreement_usage.project(db, p, task_id)
        if personal and task_id is None:
            uses = [u for u in uses if u['task_id'] in focus_ids]
        agreements, decisions = self._decisions(db, p, task_id, focus_ids, task_map, request_ids, uses)
        members = rows('SELECT id AS member_id,display_name,role FROM members WHERE room_id=? ORDER BY id', (p.room_id,))
        relevant_members = {p.member_id} | {t['owner_member_id'] for t in tasks} | {
            r[k] for r in requests for k in ('sender_member_id', 'receiver_member_id')}
        if focus_ids is not None:
            members = [m for m in members if m['member_id'] in relevant_members]
        observations = rows('''SELECT member_id,MAX(updated_at) AS last_checkpoint_at
                               FROM collaboration_checkpoints WHERE room_id=? GROUP BY member_id''', (p.room_id,))
        checkpoints = {r['member_id']: r['last_checkpoint_at'] for r in observations}
        activity = []
        for member in members:
            session_at = db.execute('''SELECT MAX(updated_at) FROM
                (SELECT updated_at FROM sessions WHERE room_id=? AND member_id=?
                 UNION ALL SELECT updated_at FROM harness_sessions WHERE room_id=? AND member_id=?)''',
                (p.room_id, member['member_id'], p.room_id, member['member_id'])).fetchone()[0]
            activity.append({**member, 'last_checkpoint_at': checkpoints.get(member['member_id']),
                'last_session_at': session_at, 'model_responsiveness': 'unknown', 'availability_proven': False})
        records = [('task', {**project_task(t), 'execution_target': {
                      'task_id': t['id'], 'session_key': t['execution_session_key'], 'ownership_epoch': t['ownership_epoch']}
                      if t['owner_member_id'] == p.member_id and t['state'] == 'claimed' and not t['cancelled_at'] else None})
                   for t in sorted(tasks, key=lambda t: (t['id'] != task_id, t['id']))]
        records += [('dependency', d) for d in dependency_items]
        records += [('request', r) for r in request_items]
        records += [('owner_question', q) for q in owner_questions]
        records += [('agreement_change', u) for u in uses]
        records += [('agreement', a) for a in agreements]
        records += [('decision', d) for d in decisions]
        records += [('member_activity', a) for a in activity]
        totals = {kind: sum(category == kind for category, _ in records) for kind in KINDS}
        onboarding = self._onboarding(p, request_items)
        meta = {'source': 'team_workflow', 'focus': {'task_id': task_id}, 'read_only': True,
                'model_consumption_proven': False, 'totals': totals, 'onboarding': onboarding,
                'recovery': [{'action': 'continue_authorized_independent_work'},
                             {'action': 'refresh_current_responsibility_before_rerouting'},
                             {'action': 'surface_pending_human_decisions_without_approving'}]}
        diagnostics = server_diagnostics(db, p, requests=request_items, owner_questions=owner_questions,
                                         tasks=tasks, task_id=task_id)
        meta.update(diagnostics)
        recovery = []
        for card in diagnostics['diagnostics']:
            action = card['next_action']
            if action not in recovery:
                recovery.append(action)
        meta['recovery'] = recovery[:6]
        # Full reply/receipt facts affect the digest, including excerpted bodies.
        semantic = {'principal': asdict(p), 'records': records, 'replies': replies, 'requests': requests,
                    'dependency_reads': dependency_reads,
                    'receipts': [r for r in receipts if r['request_id'] in request_ids],
                    'reads': [r for r in reads if any(y['id'] == r['reply_id'] for y in replies)],
                    'meta': meta}
        return records, meta, semantic

    @staticmethod
    def _request(row, replies, receipt, delivered, route, dep_map, reply_reads, dep_reads, p, tasks, owner_route=None):
        dep = dep_map.get(route['dependency_id']) if route else None
        retired = False
        if dep and route:
            source, target = tasks[dep['source_task_id']], tasks[dep['target_task_id']]
            retired = (bool(source['cancelled_at'] or target['cancelled_at']) or dep['status'] == 'cancelled'
                       or route['source_member_id'] != source['owner_member_id']
                       or route['target_member_id'] != target['owner_member_id']
                       or route['created_at'] < max(source['epoch_started_at'] or '', target['epoch_started_at'] or ''))
        state = ('historical' if not dep or retired or dep['current_request_id'] != row['id']
                 else 'closed' if dep['status'] != 'active' else 'current') if route else 'ordinary'
        if owner_route:
            state = owner_route['state']
        result = {k: row[k] for k in ('id', 'task_id', 'sender_member_id', 'receiver_member_id',
                  'context_version', 'body', 'created_at', 'resolved_at')}
        enriched = []
        latest = replies[-1] if replies else None

        def current_read(read):
            return bool(dep and state == 'current' and dep['status'] == 'active' and latest
                and read['reply_id'] == latest['id'] and read['revision'] == dep['revision']
                and read['ownership_epoch'] == tasks[dep['source_task_id']]['ownership_epoch']
                and (read['actor_kind'] == 'web' or read['session_key'] ==
                     (tasks[dep['source_task_id']]['execution_session_key'] or '')))

        for reply in replies[-2:]:
            recorded = [r for r in dep_reads if dep and r['dependency_id'] == dep['id']
                        and r['member_id'] == row['sender_member_id'] and r['reply_id'] == reply['id']]
            confirm = max(recorded, key=lambda r: (current_read(r), r['read_at'], r['revision'],
                          r['session_key'], r['actor_kind']), default=None)
            fact = ({**{k: confirm[k] for k in ('revision', 'ownership_epoch', 'session_key', 'actor_kind', 'read_at')},
                     'currently_valid': current_read(confirm)} if confirm else None)
            enriched.append({**reply, 'sender_read_at': reply_reads.get((row['sender_member_id'], reply['id'])),
                             'dependency_confirmation_read_at': confirm['read_at'] if confirm else None,
                             'dependency_confirmation_read': fact})
        sender_read = bool(latest and reply_reads.get((row['sender_member_id'], latest['id'])))
        recipient_read = True if receipt and receipt['read_at'] else None
        processing = bool(receipt and receipt['processed_at'])
        wait = ('historical_route' if state == 'historical' else 'resolved' if row['resolved_at'] or state == 'closed'
                else 'awaiting_assignment' if not delivered else 'reply_waiting_for_sender_read' if latest and not sender_read
                else 'awaiting_requester_resolution' if latest else 'processing' if processing
                else 'read' if recipient_read else 'awaiting_recipient_read')
        actions = []
        if state == 'historical' and dep:
            actions.append({'operation': 'read_dependency', 'arguments': {'dependency_id': dep['id']}})
        elif state not in ('historical', 'closed') and p.kind == 'agent' and not row['resolved_at']:
            if row['sender_member_id'] == p.member_id and latest and not sender_read:
                actions.append({'operation': 'read_replies', 'arguments': {'after_id': 0, 'task_id': row['task_id']}})
            elif row['receiver_member_id'] == p.member_id and not latest:
                actions.append({'operation': 'read_inbox', 'arguments': {'after_id': 0}})
        result.update(delivered=delivered, recipient_read=recipient_read,
                      recipient_read_at=receipt['read_at'] if receipt else None, processing=processing,
                      processed_at=receipt['processed_at'] if receipt else None, replied=bool(latest),
                      sender_reply_read=sender_read, latest_reply_id=latest['id'] if latest else None,
                      resolved=bool(row['resolved_at']) or state == 'closed', route_state=state,
                      dependency_status=dep['status'] if dep else None,
                      dependency_satisfied=bool(dep and dep['status'] == 'satisfied'),
                      dependency_id=route['dependency_id'] if route else None,
                      route_version=route['route_version'] if route else None, wait_reason=wait,
                      replies=enriched, reply_total=len(replies), replies_truncated=len(replies) > 2,
                      next_actions=actions, model_comprehension_proven=False)
        if owner_route:
            result.update(owner_route_state=state, owner_target_task_id=owner_route['target_task_id'],
                          current_request_id=owner_route['current_request_id'],
                          route_version=owner_route['route_version'])
        return result

    @staticmethod
    def _onboarding(p, requests):
        exchanges = [r for r in requests if r['delivered'] and r['receiver_member_id']
                     and r['sender_member_id'] != r['receiver_member_id']
                     and p.member_id in (r['sender_member_id'], r['receiver_member_id'])
                     and r['route_state'] != 'historical']
        selected = max(exchanges, key=lambda r: (int(r['replied']) + int(r['sender_reply_read']), r['id']), default=None)
        exchange = {k: selected[k] for k in ('sender_member_id', 'receiver_member_id', 'delivered',
                    'replied', 'sender_reply_read', 'latest_reply_id')} if selected else None
        if exchange:
            exchange['request_id'] = selected['id']
            exchange['requester_reply_read'] = exchange.pop('sender_reply_read')
        return {'identity_verified': True, 'addressed_exchange': exchange,
                'two_member_exchange_complete': bool(selected and selected['replied'] and selected['sender_reply_read']),
                'model_comprehension_proven': False}

    def _decisions(self, db, p, task_id, focus_ids, tasks, request_ids, uses):
        agreements, cards = [], []
        heads = db.execute('''SELECT v.*,d.decision FROM contract_versions v LEFT JOIN contract_decisions d
            ON d.contract_id=v.contract_id AND d.version=v.version AND d.room_id=v.room_id
            WHERE v.room_id=? ORDER BY v.contract_id,v.version''', (p.room_id,)).fetchall()
        used_ids = {u['contract_id'] for u in uses}
        latest, approved = {}, {}
        for raw in heads:
            row = dict(raw)
            latest[row['contract_id']] = row
            if row['decision'] == 'approved':
                approved[row['contract_id']] = row
        def relevant(row):
            return (task_id is None or not row['source_request_id'] or row['source_request_id'] in request_ids
                    or row['contract_id'] in used_ids)
        agreements = [{k: row[k] for k in ('contract_id', 'version', 'title', 'body')}
                      for row in approved.values() if relevant(row)]
        for row in latest.values():
            if row['decision'] is None and relevant(row):
                cards.append({'kind': 'contract', 'id': row['contract_id'], 'title': row['title'],
                    'summary': row['body'], 'operation': 'decision', 'choices': ['approved', 'rejected'],
                    'payload': {'contract_id': row['contract_id'], 'version': row['version']},
                    'eligible': p.kind == 'web', 'requires_human': True, 'authority': 'current_web_user'})
        handoffs = db.execute('''SELECT h.*,t.revision,t.cancelled_at FROM task_handoffs h
            JOIN tasks t ON t.id=h.task_id AND t.room_id=h.room_id
            WHERE h.room_id=? AND h.status='pending' ORDER BY h.id''', (p.room_id,)).fetchall()
        for h in handoffs:
            if h['cancelled_at'] or (task_id is not None and h['task_id'] != task_id) or (task_id is None and h['target_member_id'] != p.member_id):
                continue
            cards.append({'kind': 'handoff', 'id': h['id'], 'summary': h['summary'],
                'operations': ['accept_handoff', 'reject_handoff'], 'target_member_id': h['target_member_id'],
                'payload': {'task_id': h['task_id'], 'expected_revision': h['revision']},
                'required_input': ['request_key', 'summary'], 'eligible': p.kind == 'web' and h['target_member_id'] == p.member_id,
                'requires_human': True, 'authority': 'proposed_recipient_web_user'})
        for task in tasks.values():
            if task['owner_member_id'] is None and not task['cancelled_at'] and (task_id is None or task['id'] == task_id):
                cards.append({'kind': 'unassigned_task', 'id': task['id'], 'title': task['title'],
                    'operation': 'claim_task', 'payload': {'task_id': task['id']}, 'required_input': ['session_key'],
                    'eligible': p.kind == 'agent', 'requires_human': False, 'authority': 'personal_agent'})
        can_manage = manager(self.identity, db, p)
        suggestions = db.execute('''SELECT s.* FROM delivery_suggestions s JOIN tasks t
            ON t.id=s.task_id AND t.room_id=s.room_id WHERE s.room_id=? AND s.status='pending'
            AND t.cancelled_at IS NULL AND s.ownership_epoch=t.ownership_epoch
            AND s.member_id=t.owner_member_id ORDER BY s.id''', (p.room_id,)).fetchall()
        for s in suggestions:
            if task_id is not None and s['task_id'] != task_id:
                continue
            cards.append({'kind': 'delivery', 'id': s['id'], 'task_id': s['task_id'],
                'summary': s['evidence'], 'object_key': s['object_key'], 'ownership_epoch': s['ownership_epoch'],
                'operation': 'decide_delivery', 'payload': {'suggestion_id': s['id']},
                'choices': ['confirmed', 'rejected'], 'eligible': can_manage,
                'requires_human': True, 'authority': 'project_manager_web_user'})
        for use in uses:
            if use['review_required']:
                cards.append({'kind': 'agreement_review', 'id': use['contract_id'], 'task_id': use['task_id'],
                    'title': use['title'], 'operation': 'record_agreement_use',
                    'payload': {'task_id': use['task_id'], 'contract_id': use['contract_id'],
                        'version': use['effective_version'], 'session_key': use['execution_session_key'],
                        'ownership_epoch': use['ownership_epoch']},
                    'eligible': p.kind == 'agent' and use['owner_member_id'] == p.member_id,
                    'requires_human': False, 'authority': 'current_execution_owner'})
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='git_conflict_blocks'").fetchone():
            blocks = db.execute('''SELECT b.* FROM git_conflict_blocks b JOIN tasks t
                ON t.id=b.task_id AND t.room_id=b.room_id WHERE b.room_id=? AND t.cancelled_at IS NULL
                AND b.ownership_epoch=t.ownership_epoch ORDER BY b.id''', (p.room_id,)).fetchall()
            for block in blocks:
                if task_id is not None and block['task_id'] != task_id:
                    continue
                try:
                    conflicts = json.loads(block['conflicts_json'])
                except (TypeError, ValueError):
                    conflicts = []
                first = conflicts[0] if isinstance(conflicts, list) and conflicts else {}
                paths = first.get('paths') if isinstance(first, dict) else None
                summary = ('Task %d is blocked at the %s gate: task %s also touches %s. '
                           'Wait for the owning task or override with a reason.'
                           % (block['task_id'], block['gate'], first.get('task_id'),
                              ', '.join(paths[:3]) if isinstance(paths, list) and paths else 'the same paths'))
                cards.append({'kind': 'git_conflict', 'id': block['id'], 'task_id': block['task_id'],
                    'title': 'Overlap block at the %s gate' % block['gate'], 'summary': summary,
                    'blocking_task_id': first.get('task_id') if isinstance(first, dict) else None,
                    'blocking_member_id': first.get('member_id') if isinstance(first, dict) else None,
                    'ownership_epoch': block['ownership_epoch'], 'operation': 'override_overlap',
                    'payload': {'block_id': block['id']}, 'required_input': ['reason'],
                    'eligible': can_manage, 'requires_human': True,
                    'authority': 'project_manager_web_user'})
        return agreements, cards
