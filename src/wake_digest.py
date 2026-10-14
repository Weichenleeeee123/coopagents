"""Read-only digest of collaboration items that need this agent's member.

The digest carries kinds and identifiers only, never bodies, so a wake-up
watcher can decide whether to wake a model without exposing teammate text.
Reading it writes no receipts: arrival is not reading.
"""

LIMIT = 50
_LIVE_ROUTE = '''(NOT EXISTS(SELECT 1 FROM dependency_routes x WHERE x.request_id=r.id) OR EXISTS
    (SELECT 1 FROM task_dependencies d WHERE d.current_request_id=r.id AND d.status='active'))'''


class WakeDigest:
    def __init__(self, identity):
        self.db, self.resolve = identity.db, identity.resolve

    def digest(self, agent_token):
        with self.db.connect() as db:
            p = self.resolve(db, agent_token, required_kind='agent')
            # Delivered to me, unresolved, and not yet read through read_inbox.
            requests = [{'kind': 'request', 'id': r['id'], 'request_id': r['id'], 'task_id': r['task_id']}
                for r in db.execute(f'''SELECT r.id,r.task_id FROM message_deliveries m
                    JOIN message_requests r ON r.id=m.request_id
                    WHERE m.room_id=? AND m.receiver_member_id=? AND r.resolved_at IS NULL
                      AND NOT EXISTS(SELECT 1 FROM message_receipts c WHERE c.request_id=r.id)
                      AND {_LIVE_ROUTE}
                    ORDER BY r.id DESC LIMIT ?''', (p.room_id, p.member_id, LIMIT))]
            # Teammates' replies to my unresolved requests. Each reply is a separate item.
            replies = [{'kind': 'reply', 'id': r['id'], 'request_id': r['request_id'], 'task_id': r['task_id']}
                for r in db.execute(f'''SELECT y.id,y.request_id,r.task_id FROM message_replies y
                    JOIN message_requests r ON r.id=y.request_id
                    WHERE r.room_id=? AND r.sender_member_id=? AND y.author_member_id<>? AND r.resolved_at IS NULL
                      AND {_LIVE_ROUTE}
                    ORDER BY y.id DESC LIMIT ?''', (p.room_id, p.member_id, p.member_id, LIMIT))]
            handoffs = [{'kind': 'handoff', 'id': r['id'], 'task_id': r['task_id']}
                for r in db.execute('''SELECT id,task_id FROM task_handoffs
                    WHERE room_id=? AND target_member_id=? AND status='pending'
                    ORDER BY id DESC LIMIT ?''', (p.room_id, p.member_id, LIMIT))]
            return {'room_id': p.room_id, 'member_id': p.member_id,
                    'items': requests + replies + handoffs,
                    'counts': {'request': len(requests), 'reply': len(replies), 'handoff': len(handoffs)},
                    'content_included': False, 'receipts_written': False}
