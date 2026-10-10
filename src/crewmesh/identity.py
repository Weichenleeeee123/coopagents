"""Room identities authenticated by opaque, separately scoped credentials."""
from dataclasses import dataclass
import hashlib
import secrets
from uuid import uuid4

from .database import Database
from .errors import AccessDenied, NotFound, ValidationError


@dataclass(frozen=True)
class Principal:
    room_id: str
    member_id: str
    display_name: str
    role: str
    kind: str


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
        raise ValidationError("Names must contain 1 to 120 characters")
    return value.strip()


def _token_hash(token):
    if not isinstance(token, str) or not token:
        raise AccessDenied("Credential not accepted")
    try:
        encoded = token.encode("utf-8")
    except UnicodeEncodeError:
        raise AccessDenied("Credential not accepted") from None
    return hashlib.sha256(encoded).hexdigest()


class IdentityStore:
    def __init__(self, path):
        self.db = Database(path)

    def create_room(self, name, owner_name):
        name, owner_name = _name(name), _name(owner_name)
        room_id = str(uuid4())
        with self.db.connect(write=True) as connection:
            connection.execute("INSERT INTO rooms (id, name) VALUES (?, ?)", (room_id, name))
            return self._create_member(connection, room_id, owner_name, "owner")

    def _create_member(self, connection, room_id, display_name, role):
        member_id = str(uuid4())
        connection.execute(
            "INSERT INTO members (id, room_id, display_name, role) VALUES (?, ?, ?, ?)",
            (member_id, room_id, display_name, role),
        )
        result = {"room_id": room_id, "member_id": member_id}
        for kind in ("web", "agent"):
            token = secrets.token_urlsafe(32)
            connection.execute(
                "INSERT INTO credentials (token_hash, member_id, kind) VALUES (?, ?, ?)",
                (_token_hash(token), member_id, kind),
            )
            result[f"{kind}_token"] = token
        return result

    def add_member(self, owner_web_token, display_name):
        display_name = _name(display_name)
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, owner_web_token, required_kind="web")
            if principal.role != "owner":
                raise AccessDenied("Owner credential required")
            return self._create_member(connection, principal.room_id, display_name, "member")

    def authenticate(self, token, required_kind=None):
        with self.db.connect() as connection:
            return self.resolve(connection, token, required_kind)

    def resolve(self, connection, token, required_kind=None):
        if required_kind is not None and required_kind not in ("web", "agent"):
            raise ValidationError("Credential kind must be web or agent")
        token_hash = _token_hash(token)
        row = connection.execute("""SELECT m.room_id, m.id AS member_id,
                m.display_name, m.role, c.kind
            FROM credentials c JOIN members m ON m.id = c.member_id
            WHERE c.token_hash = ? AND c.revoked_at IS NULL""", (token_hash,)).fetchone()
        if row is None or (required_kind is not None and row["kind"] != required_kind):
            raise AccessDenied("Credential not accepted")
        return Principal(**dict(row))

    def list_members(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return [dict(row) for row in connection.execute("""SELECT room_id,
                id AS member_id, display_name, role FROM members
                WHERE room_id = ? ORDER BY display_name, id""", (principal.room_id,))]

    def revoke_agent(self, web_token, member_id):
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, web_token, required_kind="web")
            target = connection.execute(
                "SELECT id FROM members WHERE id = ? AND room_id = ?",
                (member_id, principal.room_id),
            ).fetchone()
            if target is None:
                raise NotFound("Member not found")
            if principal.role != "owner" and principal.member_id != member_id:
                raise AccessDenied("Member credential does not authorize revocation")
            connection.execute("""UPDATE credentials SET revoked_at = CURRENT_TIMESTAMP
                WHERE member_id = ? AND kind = 'agent' AND revoked_at IS NULL""", (member_id,))
