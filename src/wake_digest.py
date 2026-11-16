"""Read-only digest of collaboration items that need this agent's member.

The digest carries kinds and identifiers only, never bodies, so a wake-up
watcher can decide whether to wake a model without exposing teammate text.
Reading it writes no receipts: arrival is not reading.
"""
from .workflow import live_owner_route_sql
from .identity import _token_hash
from . import session_routing as routing

LIMIT = 50
_LIVE_ROUTE = '''(NOT EXISTS(SELECT 1 FROM dependency_routes x WHERE x.request_id=r.id) OR EXISTS
    (SELECT 1 FROM task_dependencies d WHERE d.current_request_id=r.id AND d.status='active')) AND ''' + live_owner_route_sql()


class WakeDigest:
    def __init__(self, identity):
        self.db, self.resolve = identity.db, identity.resolve
        routing.SessionRoutingStore(identity)

    def digest(self, agent_token, session_key=None):
        if session_key is not None:
            session_key = routing.native_key(session_key)
        with self.db.connect() as db:
            db.execute('BEGIN')
            p = self.resolve(db, agent_token, required_kind='agent')
            now, credential_hash = routing._now(), _token_hash(agent_token)

            def projected(rows, kind, task_field):
                result = []
                # Stream until this viewer has a full page. Applying the native
                # filter after LIMIT could starve a session behind others' work.
                for row in rows:
                    item = {'kind': kind, 'id': row['id'], 'task_id': row['task_id']}
                    if kind in ('request', 'reply'):
                        item['request_id'] = row['id'] if kind == 'request' else row['request_id']
                        item['route_version'] = row['context_version']
                    task_id = row[task_field] if row[task_field] is not None else row['task_id']
                    view = routing.route_item(db, p, item, task_id, session_key, credential_hash, now)
                    if view is not None:
                        result.append(view)
                    if len(result) == LIMIT:
                        break
                return result

            # Delivered to me, unresolved, and not yet read through read_inbox.
            requests = projected(db.execute(f'''SELECT r.id,r.task_id,r.context_version,
                    d.target_task_id AS execution_task_id FROM message_deliveries m
                    JOIN message_requests r ON r.id=m.request_id
                    LEFT JOIN dependency_routes x ON x.request_id=r.id
                    LEFT JOIN task_dependencies d ON d.id=x.dependency_id
                    WHERE m.room_id=? AND m.receiver_member_id=? AND r.resolved_at IS NULL
                      AND NOT EXISTS(SELECT 1 FROM message_receipts c WHERE c.request_id=r.id)
                      AND {_LIVE_ROUTE}
                    ORDER BY r.id DESC''', (p.room_id, p.member_id)), 'request', 'execution_task_id')
            # A teammate may be another session of the same member. Explicit
            # reads remove that exact reply without resolving the question.
            replies = projected(db.execute(f'''SELECT y.id,y.request_id,r.task_id,r.context_version,
                    d.source_task_id AS execution_task_id FROM message_replies y
                    JOIN message_requests r ON r.id=y.request_id
                    LEFT JOIN dependency_routes x ON x.request_id=r.id
                    LEFT JOIN task_dependencies d ON d.id=x.dependency_id
                    WHERE r.room_id=? AND r.sender_member_id=? AND r.resolved_at IS NULL
                      AND NOT EXISTS(SELECT 1 FROM workflow_reply_reads w WHERE w.room_id=r.room_id
                          AND w.member_id=? AND w.reply_id=y.id)
                      AND NOT EXISTS(SELECT 1 FROM dependency_reads w JOIN task_dependencies dd ON dd.id=w.dependency_id
                          JOIN tasks source ON source.id=dd.source_task_id AND source.room_id=dd.room_id
                          WHERE dd.current_request_id=r.id AND w.reply_id=y.id AND w.member_id=?
                              AND w.revision=dd.revision AND w.ownership_epoch=source.ownership_epoch
                              AND (w.actor_kind='web' OR w.session_key=COALESCE(source.execution_session_key,'')))
                      AND {_LIVE_ROUTE}
                    ORDER BY y.id DESC''', (p.room_id, p.member_id, p.member_id, p.member_id)), 'reply', 'execution_task_id')
            handoffs = projected(db.execute('''SELECT id,task_id FROM task_handoffs
                    WHERE room_id=? AND target_member_id=? AND status='pending'
                    ORDER BY id DESC''', (p.room_id, p.member_id)), 'handoff', 'task_id')
            return {'room_id': p.room_id, 'member_id': p.member_id,
                    'items': requests + replies + handoffs,
                    'counts': {'request': len(requests), 'reply': len(replies), 'handoff': len(handoffs)},
                    'content_included': False, 'receipts_written': False}
