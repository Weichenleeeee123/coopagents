"""Versioned room contracts with human decisions and append-only history."""
from .errors import Conflict, NotFound, ValidationError
from .messages import _positive
from .tasks import _text, _utc_now


class ContractStore:
    def __init__(self, identity):
        self.db = identity.db
        self.resolve = identity.resolve

    def _contract(self, connection, room_id, contract_id):
        row = connection.execute("SELECT * FROM contracts WHERE id = ? AND room_id = ?",
                                 (contract_id, room_id)).fetchone()
        if row is None:
            raise NotFound("Contract not found")
        return row

    def _enrich(self, connection, row):
        result = dict(row)
        result["versions"] = [dict(version) for version in connection.execute("""SELECT v.*,
                d.decision, d.decided_by_member_id, d.decided_at
            FROM contract_versions v LEFT JOIN contract_decisions d
                ON d.contract_id = v.contract_id AND d.version = v.version
            WHERE v.contract_id = ? ORDER BY v.version""", (row["id"],))]
        result["current_version"] = result["versions"][-1]["version"] if result["versions"] else 0
        result["effective_version"] = next((v["version"] for v in reversed(result["versions"])
                                             if v["decision"] == "approved"), None)
        return result

    def _event(self, connection, principal, contract_id, version, event_type, now):
        connection.execute("""INSERT INTO contract_events
            (contract_id, room_id, version, actor_member_id, event_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (contract_id, principal.room_id, version, principal.member_id, event_type, now))

    def propose(self, agent_token, contract_key, expected_version, title, body,
                source_request_id=None, commit_ref=''):
        contract_key = _text(contract_key, "Contract key", 200)
        title = _text(title, "Title", 200)
        body = _text(body, "Body", 4000)
        if type(expected_version) is not int or expected_version < 0:
            raise ValidationError("Expected version must be a nonnegative integer")
        if not isinstance(commit_ref, str) or len(commit_ref.strip()) > 200:
            raise ValidationError("Commit reference must contain at most 200 characters")
        commit_ref = commit_ref.strip()
        if source_request_id is not None:
            source_request_id = _positive(source_request_id, "Source request id")
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, agent_token, required_kind="agent")
            if source_request_id is not None and not connection.execute(
                    "SELECT id FROM message_requests WHERE id = ? AND room_id = ?",
                    (source_request_id, principal.room_id)).fetchone():
                raise NotFound("Source request not found")
            row = connection.execute("SELECT * FROM contracts WHERE room_id = ? AND contract_key = ?",
                                     (principal.room_id, contract_key)).fetchone()
            current = self._enrich(connection, row)["current_version"] if row else 0
            if expected_version != current:
                raise Conflict("Expected version does not match contract head")
            now = _utc_now()
            if row is None:
                cursor = connection.execute("""INSERT INTO contracts(room_id, contract_key, created_at)
                    VALUES (?, ?, ?)""", (principal.room_id, contract_key, now))
                row = self._contract(connection, principal.room_id, cursor.lastrowid)
            version = current + 1
            connection.execute("""INSERT INTO contract_versions
                (contract_id, room_id, version, proposer_member_id, title, body,
                 source_request_id, commit_ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["id"], principal.room_id, version, principal.member_id,
                 title, body, source_request_id, commit_ref, now))
            self._event(connection, principal, row["id"], version, "proposed", now)
            return self._enrich(connection, row)

    def list_contracts(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            # Snapshot all histories together when concurrent writes append versions.
            connection.execute("BEGIN")
            return [self._enrich(connection, row) for row in connection.execute(
                "SELECT * FROM contracts WHERE room_id = ? ORDER BY id", (principal.room_id,))]

    def decide(self, web_token, contract_id, version, decision):
        contract_id = _positive(contract_id, "Contract id")
        version = _positive(version, "Version")
        if not isinstance(decision, str) or decision not in ("approved", "rejected"):
            raise ValidationError("Decision must be approved or rejected")
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, web_token, required_kind="web")
            row = self._contract(connection, principal.room_id, contract_id)
            contract = self._enrich(connection, row)
            if version != contract["current_version"]:
                raise Conflict("Decision version does not match contract head")
            head = contract["versions"][-1]
            if head["decision"] is not None:
                if (head["decision"], head["decided_by_member_id"]) == (decision, principal.member_id):
                    return contract
                raise Conflict("Contract version already has a decision")
            now = _utc_now()
            connection.execute("""INSERT INTO contract_decisions
                (contract_id, room_id, version, decision, decided_by_member_id, decided_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (contract_id, principal.room_id, version, decision, principal.member_id, now))
            self._event(connection, principal, contract_id, version, decision, now)
            return self._enrich(connection, row)

    def list_events(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return [dict(row) for row in connection.execute(
                "SELECT * FROM contract_events WHERE room_id = ? ORDER BY id", (principal.room_id,))]
