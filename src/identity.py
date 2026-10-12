"""Room identities authenticated by opaque, separately scoped credentials."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

from .database import Database
from .errors import AccessDenied, Conflict, NotFound, ValidationError


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


def _utcnow():
    """Server clock, separated for deterministic expiry boundary tests."""
    return datetime.now(timezone.utc)


def _expired(expires_at, now):
    if expires_at is None:
        return False  # Pre-expiry credentials retain their original semantics.
    try:
        expiry = datetime.fromisoformat(expires_at)
        return expiry.tzinfo is None or expiry <= now
    except (TypeError, ValueError):
        return True


class IdentityStore:
    def __init__(self, path):
        self.db = Database(path)

    def create_room(self, name, owner_name, repository=''):
        name, owner_name = _name(name), _name(owner_name)
        if not isinstance(repository, str) or len(repository.strip()) > 500:
            raise ValidationError('Repository must contain at most 500 characters')
        repository = repository.strip()
        room_id = str(uuid4())
        with self.db.connect(write=True) as connection:
            connection.execute("INSERT INTO rooms (id, name, repository) VALUES (?, ?, ?)", (room_id, name, repository))
            return self._create_member(connection, room_id, owner_name, "owner")

    def _create_member(self, connection, room_id, display_name, role):
        member_id = str(uuid4())
        connection.execute(
            "INSERT INTO members (id, room_id, display_name, role) VALUES (?, ?, ?, ?)",
            (member_id, room_id, display_name, role),
        )
        result = {"room_id": room_id, "member_id": member_id}
        now = _utcnow()
        for kind in ("web", "agent"):
            token, expires_at = self._issue_credential(connection, member_id, kind, now)
            result[f"{kind}_token"] = token
            result[f"{kind}_expires_at"] = expires_at
        return result

    def _issue_credential(self, connection, member_id, kind, now):
        token = secrets.token_urlsafe(32)
        expires_at = (now + timedelta(days=30 if kind == 'web' else 90)).isoformat()
        connection.execute(
            'INSERT INTO credentials (token_hash, member_id, kind, expires_at) VALUES (?, ?, ?, ?)',
            (_token_hash(token), member_id, kind, expires_at),
        )
        return token, expires_at

    def room_info(self, token):
        with self.db.connect() as connection:
            principal = self.resolve(connection, token)
            return dict(connection.execute(
                'SELECT id, name, repository FROM rooms WHERE id = ?',
                (principal.room_id,),
            ).fetchone())

    def create_invite(self, web_token):
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, web_token, required_kind='web')
            self._require_unmanaged_room(connection, principal.room_id)
            if principal.role != 'owner':
                raise AccessDenied('Owner credential required')
            token = secrets.token_urlsafe(32)
            expires_at = (_utcnow() + timedelta(hours=1)).isoformat()
            connection.execute('''INSERT INTO invitations
                (token_hash, room_id, created_by_member_id, expires_at) VALUES (?, ?, ?, ?)''',
                (_token_hash(token), principal.room_id, principal.member_id, expires_at))
            return {'invite_token': token, 'expires_at': expires_at, 'room_id': principal.room_id}

    def join_invite(self, invite_token, display_name):
        display_name = _name(display_name)
        try:
            token_hash = _token_hash(invite_token)
        except AccessDenied:
            raise AccessDenied('Invitation not accepted') from None
        # BEGIN IMMEDIATE serializes validation, consumption and credential creation.
        with self.db.connect(write=True) as connection:
            invite = connection.execute('''SELECT room_id, expires_at FROM invitations
                WHERE token_hash = ? AND used_at IS NULL''', (token_hash,)).fetchone()
            now = _utcnow()
            if invite is None or _expired(invite['expires_at'], now):
                raise AccessDenied('Invitation not accepted')
            self._require_unmanaged_room(connection, invite['room_id'])
            result = self._create_member(connection, invite['room_id'], display_name, 'member')
            connection.execute('''UPDATE invitations SET used_at = ?, used_by_member_id = ?
                WHERE token_hash = ?''', (now.isoformat(), result['member_id'], token_hash))
            return result

    def connect_agent(self, web_token):
        """Issue another personal credential without invalidating existing agents."""
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, web_token, required_kind='web')
            now = _utcnow()
            active = connection.execute('''SELECT COUNT(*) FROM credentials
                WHERE member_id=? AND kind='agent' AND revoked_at IS NULL
                AND (expires_at IS NULL OR expires_at>?)''',
                (principal.member_id, now.isoformat())).fetchone()[0]
            if active >= 32:
                raise Conflict('Personal agent credential limit reached; review existing connections')
            token, expires_at = self._issue_credential(connection, principal.member_id, 'agent', now)
            return {'agent_token': token, 'expires_at': expires_at,
                    'room_id': principal.room_id, 'member_id': principal.member_id}

    def rotate_agent(self, web_token):
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, web_token, required_kind='web')
            now = _utcnow()
            connection.execute('''UPDATE credentials SET revoked_at = ?
                WHERE member_id = ? AND kind = 'agent' AND revoked_at IS NULL''',
                (now.isoformat(), principal.member_id))
            token, expires_at = self._issue_credential(connection, principal.member_id, 'agent', now)
            return {'agent_token': token, 'expires_at': expires_at,
                    'room_id': principal.room_id, 'member_id': principal.member_id}

    def add_member(self, owner_web_token, display_name):
        display_name = _name(display_name)
        with self.db.connect(write=True) as connection:
            principal = self.resolve(connection, owner_web_token, required_kind="web")
            self._require_unmanaged_room(connection, principal.room_id)
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
                m.display_name, m.role, c.kind, c.expires_at
            FROM credentials c JOIN members m ON m.id = c.member_id
            WHERE c.token_hash = ? AND c.revoked_at IS NULL""", (token_hash,)).fetchone()
        if (row is None or (required_kind is not None and row["kind"] != required_kind)
                or _expired(row['expires_at'], _utcnow())):
            raise AccessDenied("Credential not accepted")
        fields = dict(row)
        fields.pop('expires_at')
        if self._has_table(connection, 'project_members'):
            mapping = connection.execute('''SELECT p.active,t.active AS team_active
                FROM project_members p JOIN team_projects r ON r.room_id=p.room_id
                JOIN team_members t ON t.team_id=r.team_id AND t.account_id=p.account_id
                WHERE p.member_id=?''', (row['member_id'],)).fetchone()
            if mapping is not None and (not mapping['active'] or not mapping['team_active']):
                raise AccessDenied('Credential not accepted')
            session = connection.execute('''SELECT s.expires_at,s.revoked_at
                FROM session_project_credentials p JOIN account_sessions s ON s.token_hash=p.session_hash
                WHERE p.credential_hash=?''', (token_hash,)).fetchone()
            if session is not None and (session['revoked_at'] is not None or _expired(session['expires_at'], _utcnow())):
                raise AccessDenied('Credential not accepted')
        return Principal(**fields)

    @staticmethod
    def _has_table(connection, name):
        return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _require_unmanaged_room(self, connection, room_id):
        if self._has_table(connection, 'team_projects') and connection.execute(
                'SELECT 1 FROM team_projects WHERE room_id=?', (room_id,)).fetchone():
            raise AccessDenied('Use team project membership management')

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
            if principal.member_id != member_id:
                managed = self._has_table(connection, 'team_projects') and connection.execute(
                    'SELECT team_id FROM team_projects WHERE room_id=?', (principal.room_id,)).fetchone()
                if managed:
                    actor_role = connection.execute('''SELECT t.role FROM project_members p
                        JOIN team_members t ON t.account_id=p.account_id AND t.team_id=?
                        WHERE p.member_id=? AND p.active=1 AND t.active=1''',
                        (managed['team_id'], principal.member_id)).fetchone()
                    target_role = connection.execute('''SELECT t.role FROM project_members p
                        JOIN team_members t ON t.account_id=p.account_id AND t.team_id=?
                        WHERE p.member_id=? AND p.active=1 AND t.active=1''',
                        (managed['team_id'], member_id)).fetchone()
                    if (actor_role is None or actor_role['role'] not in ('owner', 'admin')
                            or (actor_role['role'] == 'admin' and target_role is not None
                                and target_role['role'] != 'member')):
                        raise AccessDenied('Team role does not authorize revocation')
                elif principal.role != 'owner':
                    raise AccessDenied("Member credential does not authorize revocation")
            connection.execute("""UPDATE credentials SET revoked_at = CURRENT_TIMESTAMP
                WHERE member_id = ? AND kind = 'agent' AND revoked_at IS NULL""", (member_id,))
