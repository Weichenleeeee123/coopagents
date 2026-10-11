"""Transactional team roles and explicit account-to-project authorization."""
import secrets
from datetime import timedelta
from uuid import uuid4

from .errors import AccessDenied, ValidationError
from .identity import _name, _token_hash, _utcnow, _expired


class WorkspaceStore:
    def __init__(self, accounts):
        self.accounts, self.identity, self.db = accounts, accounts.identity, accounts.db
        self.capacity_check = lambda connection, team_id, resource: None
        with self.db.connect(write=True) as c:
            for sql in (
                '''CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,name TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS team_members(team_id TEXT REFERENCES teams(id),
                    account_id TEXT REFERENCES accounts(id),role TEXT NOT NULL CHECK(role IN ('owner','admin','member')),
                    active INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(team_id,account_id))''',
                '''CREATE TABLE IF NOT EXISTS team_projects(room_id TEXT PRIMARY KEY REFERENCES rooms(id),team_id TEXT NOT NULL REFERENCES teams(id))''',
                '''CREATE TABLE IF NOT EXISTS project_members(room_id TEXT REFERENCES rooms(id),account_id TEXT REFERENCES accounts(id),
                    member_id TEXT NOT NULL UNIQUE REFERENCES members(id),active INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(room_id,account_id))''',
                '''CREATE TABLE IF NOT EXISTS team_invitations(token_hash TEXT PRIMARY KEY,team_id TEXT REFERENCES teams(id),
                    issued_by TEXT REFERENCES accounts(id),role TEXT NOT NULL CHECK(role IN ('owner','admin','member')),
                    expires_at TEXT NOT NULL,used_at TEXT,revoked_at TEXT)''',
                '''CREATE TABLE IF NOT EXISTS team_invite_projects(token_hash TEXT REFERENCES team_invitations(token_hash),
                    room_id TEXT REFERENCES team_projects(room_id),PRIMARY KEY(token_hash,room_id))''',
                '''CREATE TABLE IF NOT EXISTS session_project_credentials(session_hash TEXT REFERENCES account_sessions(token_hash),
                    credential_hash TEXT PRIMARY KEY REFERENCES credentials(token_hash))''',
            ):
                c.execute(sql)

    def _role(self, c, team_id, account_id):
        row = c.execute('SELECT role FROM team_members WHERE team_id=? AND account_id=? AND active=1', (team_id, account_id)).fetchone()
        if row is None:
            raise AccessDenied('Team membership required')
        return row['role']

    def _manager(self, c, session, team_id):
        account = self.accounts.resolve(c, session)
        role = self._role(c, team_id, account['id'])
        if role not in ('owner', 'admin'):
            raise AccessDenied('Team manager required')
        return account, role

    def _project_team(self, c, room_id):
        row = c.execute('SELECT team_id FROM team_projects WHERE room_id=?', (room_id,)).fetchone()
        if row is None:
            raise AccessDenied('Project not accepted')
        return row['team_id']

    def create_team(self, session_token, name):
        with self.db.connect(write=True) as c:
            account = self.accounts.resolve(c, session_token)
            team_id = str(uuid4())
            c.execute('INSERT INTO teams VALUES(?,?)', (team_id, _name(name)))
            c.execute('INSERT INTO team_members VALUES(?,?,?,1)', (team_id, account['id'], 'owner'))
            return {'team_id': team_id, 'name': name.strip(), 'role': 'owner'}

    def list_teams(self, session_token):
        with self.db.connect() as c:
            account = self.accounts.resolve(c, session_token)
            return [dict(r) for r in c.execute('SELECT t.id AS team_id,t.name,m.role FROM teams t JOIN team_members m ON m.team_id=t.id WHERE m.account_id=? AND m.active=1 ORDER BY t.name,t.id', (account['id'],))]

    def list_members(self, session_token, team_id):
        with self.db.connect() as c:
            self._role(c, team_id, self.accounts.resolve(c, session_token)['id'])
            return [dict(r) for r in c.execute('SELECT a.id AS account_id,a.username,a.display_name,m.role FROM team_members m JOIN accounts a ON a.id=m.account_id WHERE m.team_id=? AND m.active=1 ORDER BY a.display_name,a.id', (team_id,))]

    def _protect_target(self, c, team_id, actor, actor_role, target, new_role=None):
        target_role = self._role(c, team_id, target)
        if actor['id'] != target and (actor_role == 'member' or (actor_role == 'admin' and target_role != 'member')):
            raise AccessDenied('Cannot manage this team member')
        if target_role == 'owner' and new_role != 'owner':
            count = c.execute("SELECT count(*) FROM team_members WHERE team_id=? AND role='owner' AND active=1", (team_id,)).fetchone()[0]
            if count <= 1:
                raise AccessDenied('Last owner must remain')
        return target_role

    def _invalidate_invites(self, c, team_id, account_id):
        c.execute('UPDATE team_invitations SET revoked_at=? WHERE team_id=? AND issued_by=? AND used_at IS NULL', (_utcnow().isoformat(), team_id, account_id))

    def change_role(self, session_token, team_id, account_id, role):
        if role not in ('owner', 'admin', 'member'):
            raise ValidationError('Invalid team role')
        with self.db.connect(write=True) as c:
            actor, actor_role = self._manager(c, session_token, team_id)
            if actor_role != 'owner':
                raise AccessDenied('Owner required to change roles')
            old = self._protect_target(c, team_id, actor, actor_role, account_id, role)
            c.execute('UPDATE team_members SET role=? WHERE team_id=? AND account_id=?', (role, team_id, account_id))
            if old != role:
                self._invalidate_invites(c, team_id, account_id)

    def _revoke_mapping(self, c, room_id, account_id):
        now = _utcnow().isoformat()
        c.execute('UPDATE credentials SET revoked_at=? WHERE member_id IN (SELECT member_id FROM project_members WHERE room_id=? AND account_id=?) AND revoked_at IS NULL', (now, room_id, account_id))
        c.execute('UPDATE project_members SET active=0 WHERE room_id=? AND account_id=?', (room_id, account_id))

    def remove_member(self, session_token, team_id, account_id):
        with self.db.connect(write=True) as c:
            actor = self.accounts.resolve(c, session_token)
            role = self._role(c, team_id, actor['id'])
            self._protect_target(c, team_id, actor, role, account_id)
            for r in c.execute('SELECT room_id FROM team_projects WHERE team_id=?', (team_id,)).fetchall():
                self._revoke_mapping(c, r['room_id'], account_id)
            c.execute('UPDATE team_members SET active=0 WHERE team_id=? AND account_id=?', (team_id, account_id))
            self._invalidate_invites(c, team_id, account_id)

    def _grant(self, c, room_id, account_id, member_id=None):
        self._role(c, self._project_team(c, room_id), account_id)
        existing = c.execute('SELECT member_id FROM project_members WHERE room_id=? AND account_id=?', (room_id, account_id)).fetchone()
        if existing:
            c.execute('UPDATE project_members SET active=1 WHERE room_id=? AND account_id=?', (room_id, account_id))
            return existing['member_id']
        if member_id is None:
            member_id = str(uuid4())
            account = self.accounts._get(c, account_id)
            c.execute("INSERT INTO members(id,room_id,display_name,role) VALUES(?,?,?,'member')", (member_id, room_id, account['display_name']))
        c.execute('INSERT INTO project_members VALUES(?,?,?,1)', (room_id, account_id, member_id))
        return member_id

    def create_project(self, session_token, team_id, name, repository=''):
        if not isinstance(repository, str) or len(repository.strip()) > 500:
            raise ValidationError('Repository must contain at most 500 characters')
        with self.db.connect(write=True) as c:
            actor, _ = self._manager(c, session_token, team_id)
            self.capacity_check(c, team_id, 'projects')
            room_id, member_id = str(uuid4()), str(uuid4())
            c.execute('INSERT INTO rooms(id,name,repository) VALUES(?,?,?)', (room_id, _name(name), repository.strip()))
            c.execute("INSERT INTO members(id,room_id,display_name,role) VALUES(?,?,?,'owner')", (member_id, room_id, actor['display_name']))
            c.execute('INSERT INTO team_projects VALUES(?,?)', (room_id, team_id))
            self._grant(c, room_id, actor['id'], member_id)
            return {'room_id': room_id, 'team_id': team_id, 'name': name.strip(), 'repository': repository.strip()}

    def list_projects(self, session_token, team_id):
        with self.db.connect() as c:
            actor = self.accounts.resolve(c, session_token)
            self._role(c, team_id, actor['id'])
            return [dict(r) for r in c.execute('SELECT r.id AS room_id,r.name,r.repository,p.team_id FROM rooms r JOIN team_projects p ON p.room_id=r.id JOIN project_members m ON m.room_id=r.id WHERE p.team_id=? AND m.account_id=? AND m.active=1 ORDER BY r.name,r.id', (team_id, actor['id']))]

    def grant_project(self, session_token, room_id, account_id):
        with self.db.connect(write=True) as c:
            team_id = self._project_team(c, room_id)
            actor, role = self._manager(c, session_token, team_id)
            target_role = self._role(c, team_id, account_id)
            if role == 'admin' and target_role != 'member' and actor['id'] != account_id:
                raise AccessDenied('Cannot manage this project member')
            return {'room_id': room_id, 'member_id': self._grant(c, room_id, account_id), 'account_id': account_id}

    def list_managed_projects(self, session_token, team_id):
        """Manager metadata only; project context still requires explicit membership."""
        with self.db.connect() as c:
            actor, _ = self._manager(c, session_token, team_id)
            rows = c.execute('''SELECT r.id AS room_id,r.name,r.repository,p.team_id,
                EXISTS(SELECT 1 FROM project_members m WHERE m.room_id=r.id
                    AND m.account_id=? AND m.active=1) AS has_access
                FROM rooms r JOIN team_projects p ON p.room_id=r.id
                WHERE p.team_id=? ORDER BY r.name,r.id''', (actor['id'], team_id))
            return [dict(r, has_access=bool(r['has_access'])) for r in rows]

    def remove_project_member(self, session_token, room_id, account_id):
        with self.db.connect(write=True) as c:
            team_id = self._project_team(c, room_id)
            actor, role = self._manager(c, session_token, team_id)
            target_role = self._role(c, team_id, account_id)
            if role == 'admin' and target_role != 'member' and actor['id'] != account_id:
                raise AccessDenied('Cannot manage this project member')
            self._revoke_mapping(c, room_id, account_id)

    def project_credential(self, session_token, room_id):
        with self.db.connect(write=True) as c:
            actor = self.accounts.resolve(c, session_token)
            self._role(c, self._project_team(c, room_id), actor['id'])
            mapping = c.execute('SELECT member_id FROM project_members WHERE room_id=? AND account_id=? AND active=1', (room_id, actor['id'])).fetchone()
            if mapping is None:
                raise AccessDenied('Project membership required')
            token, expiry = self.identity._issue_credential(c, mapping['member_id'], 'web', _utcnow())
            session_hash = _token_hash(session_token)
            expiry = min(expiry, c.execute('SELECT expires_at FROM account_sessions WHERE token_hash=?', (session_hash,)).fetchone()['expires_at'])
            c.execute('UPDATE credentials SET expires_at=? WHERE token_hash=?', (expiry, _token_hash(token)))
            c.execute('INSERT INTO session_project_credentials VALUES(?,?)', (session_hash, _token_hash(token)))
            return {'room_id': room_id, 'member_id': mapping['member_id'], 'web_token': token, 'expires_at': expiry}

    def create_invite(self, session_token, team_id, role='member', project_ids=()):
        if role not in ('owner', 'admin', 'member') or not isinstance(project_ids, (list, tuple)):
            raise ValidationError('Invalid invitation role or project scopes')
        with self.db.connect(write=True) as c:
            actor, actor_role = self._manager(c, session_token, team_id)
            if role != 'member' and actor_role != 'owner':
                raise AccessDenied('Owner required to invite privileged member')
            projects = list(dict.fromkeys(project_ids))
            for project in projects:
                if self._project_team(c, project) != team_id:
                    raise AccessDenied('Invitation project outside team')
            token, expiry = secrets.token_urlsafe(32), (_utcnow() + timedelta(hours=24)).isoformat()
            c.execute('INSERT INTO team_invitations VALUES(?,?,?,?,?,NULL,NULL)', (_token_hash(token), team_id, actor['id'], role, expiry))
            for project in projects:
                c.execute('INSERT INTO team_invite_projects VALUES(?,?)', (_token_hash(token), project))
            return {'invite_token': token, 'expires_at': expiry, 'team_id': team_id, 'role': role, 'project_ids': projects}

    def _invitation(self, c, invite_token):
        token_hash = _token_hash(invite_token)
        invite = c.execute('SELECT * FROM team_invitations WHERE token_hash=? AND used_at IS NULL AND revoked_at IS NULL', (token_hash,)).fetchone()
        if invite is None or _expired(invite['expires_at'], _utcnow()):
            raise AccessDenied('Invitation expired, used, revoked or unavailable')
        issuer_role = self._role(c, invite['team_id'], invite['issued_by'])
        if issuer_role not in ('owner', 'admin') or (invite['role'] != 'member' and issuer_role != 'owner'):
            raise AccessDenied('Invitation issuer no longer authorized')
        projects = [dict(row) for row in c.execute('''SELECT r.id AS room_id,r.name FROM team_invite_projects i
            JOIN team_projects p ON p.room_id=i.room_id JOIN rooms r ON r.id=i.room_id
            WHERE i.token_hash=? AND p.team_id=? ORDER BY r.name,r.id''', (token_hash, invite['team_id']))]
        return token_hash, invite, issuer_role, projects

    def preview_invite(self, invite_token):
        """Possession permits metadata preview, never redemption or account creation."""
        with self.db.connect() as c:
            _, invite, _, projects = self._invitation(c, invite_token)
            return {'team_id': invite['team_id'], 'team_name': c.execute('SELECT name FROM teams WHERE id=?', (invite['team_id'],)).fetchone()['name'],
                    'role': invite['role'], 'projects': projects, 'expires_at': invite['expires_at']}

    def accept_invite(self, invite_token, session_token=None, username=None, password=None, display_name=None):
        with self.db.connect(write=True) as c:
            token_hash, invite, issuer_role, projects = self._invitation(c, invite_token)
            account = self.accounts.resolve(c, session_token) if session_token else self.accounts._create_local(c, username, password, display_name)
            existing = c.execute('SELECT active,role FROM team_members WHERE team_id=? AND account_id=?', (invite['team_id'], account['id'])).fetchone()
            role = invite['role']
            if existing and existing['active']:
                role = existing['role']
                if issuer_role == 'admin' and role != 'member' and account['id'] != invite['issued_by']:
                    raise AccessDenied('Cannot manage this project member')
            else:
                self.capacity_check(c, invite['team_id'], 'members')
                c.execute('INSERT INTO team_members VALUES(?,?,?,1) ON CONFLICT(team_id,account_id) DO UPDATE SET role=excluded.role,active=1', (invite['team_id'], account['id'], role))
            for project in projects:
                self._grant(c, project['room_id'], account['id'])
            c.execute('UPDATE team_invitations SET used_at=? WHERE token_hash=?', (_utcnow().isoformat(), token_hash))
            return {'account': account, 'team_id': invite['team_id'], 'role': role, 'project_ids': [p['room_id'] for p in projects]}

    def claim_legacy_project(self, session_token, team_id, owner_web_token):
        with self.db.connect(write=True) as c:
            actor, _ = self._manager(c, session_token, team_id)
            owner = self.identity.resolve(c, owner_web_token, 'web')
            if owner.role != 'owner' or c.execute('SELECT 1 FROM team_projects WHERE room_id=?', (owner.room_id,)).fetchone():
                raise AccessDenied('Unbound project owner credential required')
            self.capacity_check(c, team_id, 'projects')
            c.execute('INSERT INTO team_projects VALUES(?,?)', (owner.room_id, team_id))
            self._grant(c, owner.room_id, actor['id'], owner.member_id)
            return {'team_id': team_id, 'room_id': owner.room_id}

    def reset_password(self, session_token, team_id, account_id, new_password):
        with self.db.connect(write=True) as c:
            actor, role = self._manager(c, session_token, team_id)
            target = self._role(c, team_id, account_id)
            if actor['id'] == account_id or target == 'owner' or (role == 'admin' and target != 'member'):
                raise AccessDenied('Password reset not authorized')
            if c.execute('SELECT count(*) FROM team_members WHERE account_id=? AND active=1', (account_id,)).fetchone()[0] != 1:
                raise AccessDenied('Cannot reset account belonging to other teams')
            self.accounts._reset_password(c, account_id, new_password)
