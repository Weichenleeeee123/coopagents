"""Durable technical requests with separate read, processed and resolved states.

Every operation returns enriched request dictionaries (or a list/page of them).
Original receiver payload is stored privately for retries after assignment.
"""
from .errors import AccessDenied, Conflict, NotFound, ValidationError
from .tasks import _text, _utc_now


def _positive(value, field):
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{field} must be a positive integer")
    return value


class MessageStore:
    def __init__(self, identity_store):
        self.db = identity_store.db
        self.resolve = identity_store.resolve

    def _request(self, connection, principal, request_id):
        row = connection.execute("SELECT * FROM message_requests WHERE id = ? AND room_id = ?",
                                 (request_id, principal.room_id)).fetchone()
        if row is None:
            raise NotFound("Request not found")
        return row

    def _member(self, connection, principal, member_id):
        if not isinstance(member_id, str) or not connection.execute(
                "SELECT id FROM members WHERE id = ? AND room_id = ?",
                (member_id, principal.room_id)).fetchone():
            raise NotFound("Member not found")

    def _enrich(self, connection, row):
        result = dict(row)
        result.pop("initial_receiver_member_id")
        delivery = connection.execute("SELECT id FROM message_deliveries WHERE request_id = ?",
                                      (row["id"],)).fetchone()
        result["delivery_id"] = delivery["id"] if delivery else None
        receipt = connection.execute("SELECT read_at, processed_at FROM message_receipts WHERE request_id = ?",
                                     (row["id"],)).fetchone()
        result.update(dict(receipt) if receipt else {"read_at": None, "processed_at": None})
        from .dependencies import linked_request
        linked = linked_request(connection, row['id'])
        if linked:
            result['dependency_id'] = linked['dependency_id']
            dep = connection.execute('SELECT status,current_request_id FROM task_dependencies WHERE id=?', (linked['dependency_id'],)).fetchone()
            result['dependency_route_state'] = ('historical' if dep['current_request_id']!=row['id']
                else 'closed' if dep['status']!='active' else 'current')
        result["replies"] = [dict(reply) for reply in connection.execute(
            "SELECT * FROM message_replies WHERE request_id = ? ORDER BY id", (row["id"],))]
        return result

    def _recipient(self, principal, row):
        if row["receiver_member_id"] != principal.member_id:
            raise AccessDenied("Assigned recipient required")

    def _version(self, row, version):
        if row["context_version"] != version:
            raise Conflict("Context version does not match request")

    def send_request(self, agent_token, request_key, receiver_member_id, task_id, context_version, body):
        request_key = _text(request_key, "Request key", 200)
        body = _text(body, "Body", 4000)
        context_version = _positive(context_version, "Context version")
        if task_id is not None:
            task_id = _positive(task_id, "Task id")
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            if receiver_member_id is not None:
                self._member(connection, principal, receiver_member_id)
            if task_id is not None and not connection.execute(
                    "SELECT id FROM tasks WHERE id = ? AND room_id = ?", (task_id, principal.room_id)).fetchone():
                raise NotFound("Task not found")
            row = connection.execute("""SELECT * FROM message_requests
                WHERE room_id = ? AND sender_member_id = ? AND request_key = ?""",
                (principal.room_id, principal.member_id, request_key)).fetchone()
            if row is not None:
                if (row["initial_receiver_member_id"], row["task_id"], row["context_version"], row["body"]) != (receiver_member_id, task_id, context_version, body):
                    raise Conflict("Request key already has a different payload")
            else:
                cursor = connection.execute("""INSERT INTO message_requests
                    (room_id, sender_member_id, receiver_member_id, initial_receiver_member_id,
                     task_id, context_version, body, request_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (principal.room_id, principal.member_id, receiver_member_id, receiver_member_id,
                     task_id, context_version, body, request_key, _utc_now()))
                row = self._request(connection, principal, cursor.lastrowid)
                if receiver_member_id is not None:
                    self._deliver(connection, row["id"], principal.room_id, receiver_member_id)
            return self._enrich(connection, row)

    def _deliver(self, connection, request_id, room_id, receiver_member_id):
        connection.execute("""INSERT INTO message_deliveries
            (request_id, room_id, receiver_member_id) VALUES (?, ?, ?)
            ON CONFLICT(request_id) DO NOTHING""", (request_id, room_id, receiver_member_id))

    def list_requests(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return [self._enrich(connection, row) for row in connection.execute(
                "SELECT * FROM message_requests WHERE room_id = ? ORDER BY id", (principal.room_id,))]

    def read_inbox(self, agent_token, after_id=0, limit=50):
        """Read a delivery page; after_id is an exclusive delivery_id cursor."""
        if type(after_id) is not int or after_id < 0:
            raise ValidationError("Cursor must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValidationError("Limit must be an integer from 1 to 50")
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            rows = connection.execute("""SELECT r.*, d.id AS delivery_id
                FROM message_deliveries d JOIN message_requests r ON r.id = d.request_id
                WHERE d.room_id = ? AND d.receiver_member_id = ? AND d.id > ? ORDER BY d.id LIMIT ?""",
                (principal.room_id, principal.member_id, after_id, limit)).fetchall()
            now = _utc_now()
            for row in rows:
                connection.execute("""INSERT INTO message_receipts (request_id, room_id, member_id, read_at)
                    VALUES (?, ?, ?, ?) ON CONFLICT(request_id) DO NOTHING""",
                    (row["id"], principal.room_id, principal.member_id, now))
            return {"requests": [self._enrich(connection, row) for row in rows],
                    "next_cursor": rows[-1]["delivery_id"] if rows else after_id}

    def acknowledge(self, agent_token, request_id):
        request_id = _positive(request_id, "Request id")
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            row = self._request(connection, principal, request_id)
            self._recipient(principal, row)
            if not connection.execute("SELECT request_id FROM message_receipts WHERE request_id = ?",
                                      (request_id,)).fetchone():
                raise Conflict("Request must be read before acknowledgement")
            connection.execute("""UPDATE message_receipts SET processed_at = ?
                WHERE request_id = ? AND processed_at IS NULL""", (_utc_now(), request_id))
            return self._enrich(connection, row)

    def reply(self, agent_token, request_id, request_key, context_version, body, evidence=""):
        request_id = _positive(request_id, "Request id")
        context_version = _positive(context_version, "Context version")
        request_key = _text(request_key, "Request key", 200)
        body = _text(body, "Body", 4000)
        if not isinstance(evidence, str) or len(evidence.strip()) > 1000:
            raise ValidationError("Evidence must contain at most 1000 characters")
        evidence = evidence.strip()
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            row = self._request(connection, principal, request_id)
            self._recipient(principal, row)
            from .dependencies import linked_request
            if linked_request(connection, request_id):
                raise Conflict('Use the dedicated dependency operation for linked requests')
            self._version(row, context_version)
            existing = connection.execute("""SELECT * FROM message_replies
                WHERE room_id = ? AND author_member_id = ? AND request_key = ?""",
                (principal.room_id, principal.member_id, request_key)).fetchone()
            if existing is not None:
                if (existing["request_id"], existing["context_version"], existing["body"], existing["evidence"]) != (request_id, context_version, body, evidence):
                    raise Conflict("Reply key already has a different payload")
            else:
                connection.execute("""INSERT INTO message_replies
                    (request_id, room_id, author_member_id, request_key, context_version, body, evidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (request_id, principal.room_id, principal.member_id, request_key,
                     context_version, body, evidence, _utc_now()))
            return self._enrich(connection, row)

    def resolve_request(self, token, request_id, context_version):
        request_id = _positive(request_id, "Request id")
        context_version = _positive(context_version, "Context version")
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, token)
            row = self._request(connection, principal, request_id)
            from .dependencies import linked_request
            if linked_request(connection, request_id):
                raise Conflict('Use the dedicated dependency operation for linked requests')
            if row["sender_member_id"] != principal.member_id:
                raise AccessDenied("Request sender required")
            self._version(row, context_version)
            if not connection.execute("""SELECT id FROM message_replies WHERE request_id = ?
                AND author_member_id = ? AND context_version = ?""",
                (request_id, row["receiver_member_id"], context_version)).fetchone():
                raise Conflict("Current recipient reply required before resolution")
            connection.execute("UPDATE message_requests SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL",
                               (_utc_now(), request_id))
            return self._enrich(connection, self._request(connection, principal, request_id))

    def assign_receiver(self, web_token, request_id, receiver_member_id):
        request_id = _positive(request_id, "Request id")
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, web_token, required_kind="web")
            row = self._request(connection, principal, request_id)
            from .dependencies import linked_request
            if linked_request(connection, request_id):
                raise Conflict('Use the dedicated dependency operation for linked requests')
            self._member(connection, principal, receiver_member_id)
            if row["receiver_member_id"] is not None and row["receiver_member_id"] != receiver_member_id:
                raise Conflict("Request already has an assigned recipient")
            connection.execute("""UPDATE message_requests SET receiver_member_id = ?,
                assigned_by_member_id = ?, assigned_at = ? WHERE id = ? AND receiver_member_id IS NULL""",
                (receiver_member_id, principal.member_id, _utc_now(), request_id))
            if row["receiver_member_id"] is None:
                self._deliver(connection, request_id, principal.room_id, receiver_member_id)
            return self._enrich(connection, self._request(connection, principal, request_id))
