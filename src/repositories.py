"""Project-scoped immutable local Git observations; never server-verified facts."""
from datetime import datetime, timedelta, timezone
from itertools import combinations
import hashlib
import json
import re

from .errors import AccessDenied, Conflict, NotFound, ValidationError
from .git_workspace import normalize_repository, task_branch_name, validate_relative_paths


def now():
    return datetime.now(timezone.utc)


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ValidationError('Expected an ISO timestamp with timezone') from None


def require_manager(identity, connection, principal):
    if principal.kind != 'web':
        raise AccessDenied('Project manager web credential required')
    if identity._has_table(connection, 'team_projects'):
        managed = connection.execute('SELECT team_id FROM team_projects WHERE room_id=?', (principal.room_id,)).fetchone()
        if managed:
            row = connection.execute('''SELECT t.role FROM project_members p JOIN team_members t
                ON t.account_id=p.account_id AND t.team_id=?
                WHERE p.room_id=? AND p.member_id=? AND p.active=1 AND t.active=1''',
                (managed['team_id'], principal.room_id, principal.member_id)).fetchone()
            if row and row['role'] in ('owner', 'admin'):
                return
            raise AccessDenied('Project manager required')
    if principal.role != 'owner':
        raise AccessDenied('Project manager required')


def visible_task(connection, principal, task_id, *, manager=False, session_key=None, ownership_epoch=None):
    from .task_lifecycle import task_row, execution_task
    if not manager:
        return execution_task(connection, principal, task_id, session_key, ownership_epoch)
    task = task_row(connection, principal, task_id)
    if task['cancelled_at']:
        raise Conflict('Task is cancelled; reopen it first')
    return task



class RepositoryStore:
    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        with self.db.connect(write=True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS repo_bindings (
                room_id TEXT PRIMARY KEY REFERENCES rooms(id), repository TEXT NOT NULL,
                bound_by TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(bound_by,room_id) REFERENCES members(id,room_id))''')
            if 'git_write_enabled' not in {r['name'] for r in c.execute('PRAGMA table_info(repo_bindings)')}:
                c.execute('ALTER TABLE repo_bindings ADD COLUMN git_write_enabled INTEGER NOT NULL DEFAULT 0')
            c.execute('''CREATE TABLE IF NOT EXISTS git_branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, branch TEXT NOT NULL, base_sha TEXT NOT NULL,
                ownership_epoch INTEGER NOT NULL, created_by TEXT NOT NULL,
                request_key TEXT NOT NULL, pushed_sha TEXT NOT NULL DEFAULT '',
                pushed_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                UNIQUE(room_id,task_id,ownership_epoch),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS git_write_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                member_id TEXT NOT NULL, action TEXT NOT NULL, scope_json TEXT NOT NULL,
                created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS git_conflict_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, ownership_epoch INTEGER NOT NULL,
                gate TEXT NOT NULL, paths_json TEXT NOT NULL, conflicts_json TEXT NOT NULL,
                blocked_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(room_id,task_id,ownership_epoch,gate),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS git_overlap_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, ownership_epoch INTEGER NOT NULL,
                paths_json TEXT NOT NULL, reason TEXT NOT NULL, overridden_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS git_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                member_id TEXT NOT NULL, task_id INTEGER NOT NULL, workspace_id TEXT NOT NULL,
                repository TEXT NOT NULL, branch TEXT NOT NULL, head TEXT NOT NULL,
                paths_json TEXT NOT NULL, captured_at TEXT NOT NULL, received_at TEXT NOT NULL,
                request_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
                UNIQUE(room_id,member_id,request_key),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            if 'ownership_epoch' not in {r['name'] for r in c.execute('PRAGMA table_info(git_observations)')}:
                c.execute('ALTER TABLE git_observations ADD COLUMN ownership_epoch INTEGER NOT NULL DEFAULT 0')
            c.execute('CREATE INDEX IF NOT EXISTS git_observation_room ON git_observations(room_id,id)')

    def bind_repository(self, token, repository):
        repository = normalize_repository(repository)
        with self.db.connect(write=True) as c:
            principal = self.identity.resolve(c, token, required_kind='web')
            require_manager(self.identity, c, principal)
            existing = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if existing:
                if existing['repository'] == repository:
                    return dict(existing)
                raise Conflict('Project repository is already bound; create a separate project for another repository')
            c.execute('''INSERT INTO repo_bindings(room_id,repository,bound_by,updated_at) VALUES(?,?,?,?)''',
                      (principal.room_id, repository, principal.member_id, now().isoformat()))
            return dict(c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone())

    def get_binding(self, token):
        with self.db.connect() as c:
            principal = self.identity.resolve(c, token)
            row = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            return dict(row) if row else None

    def git_write_enabled_for_room(self, room_id):
        """Unauthenticated room lookup for callers holding an authenticated principal."""
        with self.db.connect() as c:
            row = c.execute('SELECT git_write_enabled FROM repo_bindings WHERE room_id=?', (room_id,)).fetchone()
            return bool(row and row['git_write_enabled'])

    def set_git_write_enabled(self, token, enabled):
        if type(enabled) is not bool:
            raise ValidationError('Expected a git write flag value')
        with self.db.connect(write=True) as c:
            principal = self.identity.resolve(c, token, required_kind='web')
            require_manager(self.identity, c, principal)
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if not binding:
                raise Conflict('Bind a repository before changing the git write path')
            c.execute('UPDATE repo_bindings SET git_write_enabled=? WHERE room_id=?',
                      (1 if enabled else 0, principal.room_id))
            c.execute('INSERT INTO git_write_audit(room_id,member_id,action,scope_json,created_at) VALUES(?,?,?,?,?)',
                      (principal.room_id, principal.member_id,
                       'flag_enabled' if enabled else 'flag_disabled',
                       json.dumps({'git_write_enabled': enabled}), now().isoformat()))
            return {'repository': binding['repository'], 'git_write_enabled': enabled}

    def record_branch(self, token, task_id, branch, base_sha, request_key, session_key=None, ownership_epoch=None, preview=False):
        """Record a locally created task branch; the service never runs git (W1)."""
        from .git_workspace import branch_name
        branch_name(branch)
        if not isinstance(base_sha, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', base_sha):
            raise ValidationError('Expected a complete commit SHA')
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200:
            raise ValidationError('Invalid request key')
        if type(preview) is not bool:
            raise ValidationError('Expected a preview flag')
        with self.db.connect(write=True) as c:
            principal = self.identity.resolve(c, token, required_kind='agent')
            task = visible_task(c, principal, task_id, session_key=session_key, ownership_epoch=ownership_epoch)
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if not binding:
                raise Conflict('Project repository is not bound')
            if not binding['git_write_enabled']:
                raise Conflict('Git write path is not enabled for this space')
            expected = task_branch_name(task_id, task['ownership_epoch'], task['title'])
            if branch != expected:
                raise ValidationError('Branch name does not match the task branch')
            existing = c.execute('''SELECT * FROM git_branches WHERE room_id=? AND task_id=?
                AND ownership_epoch=?''', (principal.room_id, task_id, task['ownership_epoch'])).fetchone()
            if existing:
                if existing['branch'] != branch or existing['base_sha'] != base_sha:
                    raise Conflict('Task branch already recorded from a different base')
                return dict(existing)
            checked, _, conflicts = self.evaluate_gate(
                c, principal.room_id, principal.member_id, task_id, task['ownership_epoch'])
            display = [{**conflict, 'paths': self.compact_paths(conflict['paths'], 4000)}
                       for conflict in conflicts]
            if preview:
                return {'task_id': task_id, 'branch': branch, 'base_sha': base_sha,
                        'ownership_epoch': task['ownership_epoch'], 'preview': True,
                        'paths_checked': checked, 'conflicts': display, 'blocked': bool(conflicts)}
            if conflicts:
                blocked = (principal, task, checked, conflicts)
            else:
                row = c.execute('''INSERT INTO git_branches(room_id,task_id,branch,base_sha,ownership_epoch,
                    created_by,request_key,created_at) VALUES(?,?,?,?,?,?,?,?)''',
                    (principal.room_id, task_id, branch, base_sha, task['ownership_epoch'],
                     principal.member_id, request_key, now().isoformat()))
                self.clear_conflict_block(c, principal.room_id, task_id, task['ownership_epoch'], 'claim')
                return dict(c.execute('SELECT * FROM git_branches WHERE id=?', (row.lastrowid,)).fetchone())
        # Record the block in its own transaction: raising inside the write
        # block above would roll the insert back with it.
        principal, task, checked, conflicts = blocked
        with self.db.connect(write=True) as c:
            self.record_conflict_block(c, principal.room_id, principal.member_id, task_id,
                                       task['ownership_epoch'], 'claim', checked, conflicts)
        raise Conflict(self.conflict_message(conflicts))

    def get_branch(self, token, task_id, session_key=None, ownership_epoch=None):
        with self.db.connect() as c:
            principal = self.identity.resolve(c, token)
            task = visible_task(c, principal, task_id, session_key=session_key,
                                ownership_epoch=ownership_epoch, manager=principal.kind == 'web')
            row = c.execute('''SELECT * FROM git_branches WHERE room_id=? AND task_id=?
                AND ownership_epoch=?''', (principal.room_id, task_id, task['ownership_epoch'])).fetchone()
            return dict(row) if row else None

    def overlap_conflicts(self, connection, room_id, task_id, paths, compact=True):
        """Fresh cross-task path overlaps; stale observations never block (W3 read).

        With compact=False the full hit lists are returned for gate decisions
        (override subtraction needs exact paths); display callers keep the
        compacted form.
        """
        wanted = set(validate_relative_paths(paths))
        if not wanted:
            return []
        rows = connection.execute('''SELECT g.* FROM git_observations g JOIN tasks t ON t.id=g.task_id
            WHERE g.room_id=? AND t.cancelled_at IS NULL AND t.owner_member_id IS NOT NULL
            AND g.ownership_epoch=t.ownership_epoch AND g.task_id!=? AND NOT EXISTS
            (SELECT 1 FROM git_observations n WHERE n.room_id=g.room_id AND n.member_id=g.member_id
             AND n.workspace_id=g.workspace_id AND n.task_id=g.task_id AND n.ownership_epoch=g.ownership_epoch
             AND (n.captured_at>g.captured_at OR (n.captured_at=g.captured_at AND n.id>g.id)))
            ORDER BY g.id DESC LIMIT 50''',
            (room_id, task_id)).fetchall()
        conflicts = []
        for row in rows:
            if timestamp(row['captured_at']) < now() - timedelta(minutes=5):
                continue
            hit = sorted(wanted.intersection(json.loads(row['paths_json'])))
            if hit:
                conflicts.append({'task_id': row['task_id'], 'member_id': row['member_id'],
                                  'paths': self.compact_paths(hit, 4000) if compact else hit,
                                  'path_count': len(hit),
                                  'captured_at': row['captured_at']})
        return conflicts

    def _fresh_caller_paths(self, connection, room_id, member_id, task_id, ownership_epoch):
        """Union of fresh latest-per-workspace observation paths for one execution."""
        rows = connection.execute('''SELECT g.paths_json,g.captured_at FROM git_observations g
            WHERE g.room_id=? AND g.member_id=? AND g.task_id=? AND g.ownership_epoch=? AND NOT EXISTS
            (SELECT 1 FROM git_observations n WHERE n.room_id=g.room_id AND n.member_id=g.member_id
             AND n.workspace_id=g.workspace_id AND n.task_id=g.task_id AND n.ownership_epoch=g.ownership_epoch
             AND (n.captured_at>g.captured_at OR (n.captured_at=g.captured_at AND n.id>g.id)))''',
            (room_id, member_id, task_id, ownership_epoch)).fetchall()
        paths = set()
        fresh = False
        for row in rows:
            if timestamp(row['captured_at']) >= now() - timedelta(minutes=5):
                fresh = True
                paths.update(json.loads(row['paths_json']))
        return sorted(paths), fresh

    def _overridden_paths(self, connection, room_id, task_id, ownership_epoch):
        rows = connection.execute('''SELECT paths_json FROM git_overlap_overrides
            WHERE room_id=? AND task_id=? AND ownership_epoch=?''',
            (room_id, task_id, ownership_epoch)).fetchall()
        paths = set()
        for row in rows:
            paths.update(json.loads(row['paths_json']))
        return paths

    @staticmethod
    def _apply_overrides(conflicts, overridden):
        kept = []
        for conflict in conflicts:
            remaining = [path for path in conflict['paths'] if path not in overridden]
            if remaining:
                kept.append({**conflict, 'paths': remaining, 'path_count': len(remaining)})
        return kept

    def evaluate_gate(self, connection, room_id, member_id, task_id, ownership_epoch, paths=None):
        """Fresh caller paths + override-adjusted conflicts for a write gate.

        With explicit paths those are checked; otherwise the caller's fresh
        observation paths are used. Returns (paths_checked, fresh, conflicts).
        """
        if paths is None:
            paths, fresh = self._fresh_caller_paths(connection, room_id, member_id, task_id, ownership_epoch)
        else:
            paths = validate_relative_paths(paths)
            _, fresh = self._fresh_caller_paths(connection, room_id, member_id, task_id, ownership_epoch)
        conflicts = self._apply_overrides(
            self.overlap_conflicts(connection, room_id, task_id, paths, compact=False),
            self._overridden_paths(connection, room_id, task_id, ownership_epoch))
        return paths, fresh, conflicts

    @staticmethod
    def conflict_message(conflicts):
        parts = []
        for conflict in conflicts[:5]:
            parts.append('task %d (member %s) also touches %s' % (
                conflict['task_id'], conflict['member_id'], ', '.join(conflict['paths'][:5])))
        return ('Overlap conflict: ' + '; '.join(parts)
                + '. Wait for the owning task or ask a project manager to override.')

    def record_conflict_block(self, connection, room_id, member_id, task_id, ownership_epoch,
                              gate, paths, conflicts):
        stamp = now().isoformat()
        connection.execute('''INSERT INTO git_conflict_blocks(room_id,task_id,ownership_epoch,gate,
            paths_json,conflicts_json,blocked_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(room_id,task_id,ownership_epoch,gate) DO UPDATE SET paths_json=excluded.paths_json,
            conflicts_json=excluded.conflicts_json,blocked_by=excluded.blocked_by,updated_at=excluded.updated_at''',
            (room_id, task_id, ownership_epoch, gate, json.dumps(paths), json.dumps(conflicts),
             member_id, stamp, stamp))

    def clear_conflict_block(self, connection, room_id, task_id, ownership_epoch, gate):
        connection.execute('''DELETE FROM git_conflict_blocks WHERE room_id=? AND task_id=?
            AND ownership_epoch=? AND gate=?''', (room_id, task_id, ownership_epoch, gate))

    def check_overlap(self, token, task_id, paths=None, session_key=None, ownership_epoch=None, gate=None):
        """Overlap read for a task execution; with a gate, a block is recorded.

        Without paths, the caller's fresh observation paths are checked. The
        read itself never blocks; callers enforcing a gate raise on `blocked`.
        """
        if gate is not None and gate not in ('claim', 'delivery'):
            raise ValidationError('Expected an overlap gate')
        if paths is not None:
            paths = validate_relative_paths(paths)
        with self.db.connect(write=True) as c:
            principal = self.identity.resolve(c, token, required_kind='agent')
            task = visible_task(c, principal, task_id, session_key=session_key, ownership_epoch=ownership_epoch)
            checked, fresh, conflicts = self.evaluate_gate(
                c, principal.room_id, principal.member_id, task_id, task['ownership_epoch'], paths)
            blocked = bool(conflicts)
            if blocked and gate is not None:
                self.record_conflict_block(c, principal.room_id, principal.member_id, task_id,
                                           task['ownership_epoch'], gate, checked, conflicts)
            display = [{**conflict, 'paths': self.compact_paths(conflict['paths'], 4000)}
                       for conflict in conflicts]
            return {'task_id': task_id, 'ownership_epoch': task['ownership_epoch'],
                    'paths_checked': checked, 'fresh_checkpoint': fresh, 'conflicts': display,
                    'blocked': blocked}

    def override_overlap(self, token, block_id, reason):
        """Record a project-manager overlap override (W4, D9) and clear the block.

        The override covers exactly the paths the blocked gate checked, for the
        blocked execution epoch only; a new epoch needs a new override. The
        manager, reason, and scope are written to the write audit trail.
        """
        if type(block_id) is not int or block_id < 1:
            raise ValidationError('Expected a positive block id')
        if (not isinstance(reason, str) or not 1 <= len(reason) <= 500 or reason != reason.strip()
                or any(ord(char) < 32 for char in reason)):
            raise ValidationError('Override reason is invalid')
        with self.db.connect(write=True) as c:
            principal = self.identity.resolve(c, token, required_kind='web')
            require_manager(self.identity, c, principal)
            block = c.execute('''SELECT * FROM git_conflict_blocks WHERE id=? AND room_id=?''',
                              (block_id, principal.room_id)).fetchone()
            if not block:
                raise NotFound('Conflict block not found')
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if not binding or not binding['git_write_enabled']:
                raise Conflict('Git write path is not enabled for this space')
            stamp = now().isoformat()
            row = c.execute('''INSERT INTO git_overlap_overrides(room_id,task_id,ownership_epoch,
                paths_json,reason,overridden_by,created_at) VALUES(?,?,?,?,?,?,?)''',
                (principal.room_id, block['task_id'], block['ownership_epoch'], block['paths_json'],
                 reason, principal.member_id, stamp))
            c.execute('DELETE FROM git_conflict_blocks WHERE id=?', (block_id,))
            c.execute('''INSERT INTO git_write_audit(room_id,member_id,action,scope_json,created_at)
                VALUES(?,?,?,?,?)''',
                (principal.room_id, principal.member_id, 'overlap_override',
                 json.dumps({'task_id': block['task_id'], 'ownership_epoch': block['ownership_epoch'],
                             'gate': block['gate'], 'paths': json.loads(block['paths_json']),
                             'reason': reason}), stamp))
            return dict(c.execute('SELECT * FROM git_overlap_overrides WHERE id=?', (row.lastrowid,)).fetchone())

    @staticmethod
    def validate_observation(observation):
        keys = {'request_key','workspace_id','repository','branch','head','paths','captured_at'}
        if not isinstance(observation, dict) or set(observation) != keys:
            raise ValidationError('Unsupported observation fields')
        result = dict(observation)
        try:
            for value in result.values():
                if isinstance(value,str): value.encode('utf-8')
            for path in result.get('paths',[]) if isinstance(result.get('paths'),list) else []:
                if isinstance(path,str): path.encode('utf-8')
        except UnicodeEncodeError:
            raise ValidationError('Observation must contain valid Unicode') from None
        for key, maximum in [('request_key',200),('workspace_id',128),('branch',250),('head',64)]:
            value = result[key]
            if not isinstance(value, str) or len(value) > maximum or any(ord(ch)<32 for ch in value):
                raise ValidationError('Invalid observation text')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,128}', result['workspace_id']) or not result['request_key']:
            raise ValidationError('Invalid workspace or request identifier')
        if result['head'] and not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', result['head']):
            raise ValidationError('Expected a complete commit SHA')
        result['repository'] = normalize_repository(result['repository'])
        result['paths'] = validate_relative_paths(result['paths'])
        captured = timestamp(result['captured_at'])
        if captured > now()+timedelta(seconds=60):
            raise ValidationError('Capture timestamp is in the future')
        result['captured_at'] = captured.isoformat()
        if len(json.dumps(result).encode())>60_000:
            raise ValidationError('Git observation exceeds the request size limit')
        return result

    @staticmethod
    def observation_row(row):
        value = dict(row)
        value['paths'] = json.loads(value.pop('paths_json'))
        value.pop('payload_hash')
        value['source'] = 'local_git'
        return value

    def observe(self, token, task_id, observation, session_key=None, ownership_epoch=None):
        data = self.validate_observation(observation)
        payload = [task_id,data] if session_key is None and ownership_epoch is None else [task_id,data,session_key,ownership_epoch]
        payload_hash = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        with self.db.connect(write=True) as c:
            principal = self.identity.resolve(c, token, required_kind='agent')
            task = visible_task(c, principal, task_id, session_key=session_key, ownership_epoch=ownership_epoch)
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if not binding or binding['repository'] != data['repository']:
                raise Conflict('Local repository does not match the project binding')
            existing = c.execute('''SELECT * FROM git_observations
                WHERE room_id=? AND member_id=? AND request_key=?''',
                (principal.room_id,principal.member_id,data['request_key'])).fetchone()
            if existing:
                if existing['payload_hash'] != payload_hash or existing['ownership_epoch'] != task['ownership_epoch']:
                    raise Conflict('Request key already has another payload')
                return self.observation_row(existing)
            row = c.execute('''INSERT INTO git_observations(room_id,member_id,task_id,workspace_id,
                repository,branch,head,paths_json,captured_at,received_at,request_key,payload_hash,ownership_epoch)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (principal.room_id,principal.member_id,task_id,data['workspace_id'],data['repository'],
                 data['branch'],data['head'],json.dumps(data['paths']),data['captured_at'],now().isoformat(),
                 data['request_key'],payload_hash,task['ownership_epoch']))
            return self.observation_row(c.execute('SELECT * FROM git_observations WHERE id=?', (row.lastrowid,)).fetchone())

    def snapshot(self, token):
        with self.db.connect() as c:
            principal = self.identity.resolve(c, token)
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            try:
                require_manager(self.identity,c,principal)
                can_manage=True
            except AccessDenied:
                can_manage=False
            rows = c.execute('''SELECT g.* FROM git_observations g JOIN tasks t ON t.id=g.task_id
                WHERE g.room_id=? AND t.cancelled_at IS NULL AND t.owner_member_id IS NOT NULL
                AND g.ownership_epoch=t.ownership_epoch AND NOT EXISTS
                (SELECT 1 FROM git_observations n WHERE n.room_id=g.room_id AND n.member_id=g.member_id
                 AND n.workspace_id=g.workspace_id AND n.task_id=g.task_id AND n.ownership_epoch=g.ownership_epoch
                 AND (n.captured_at>g.captured_at OR (n.captured_at=g.captured_at AND n.id>g.id))) ORDER BY g.id DESC LIMIT 51''', (principal.room_id,)).fetchall()
            truncated=len(rows)>50
            workspaces = [self.observation_row(r) for r in reversed(rows[:50])]
            for item in workspaces:
                item['stale'] = timestamp(item['captured_at']) < now()-timedelta(minutes=5)
            overlaps = []
            for left, right in combinations(workspaces,2):
                paths = sorted(set(left['paths']).intersection(right['paths']))
                if paths and len(overlaps)<50 and left['task_id'] != right['task_id'] and not left['stale'] and not right['stale']:
                    overlaps.append({'task_ids':[left['task_id'],right['task_id']],
                                     'member_ids':[left['member_id'],right['member_id']],
                                     'paths':self.compact_paths(paths,4000),'path_count':len(paths),
                                     'source':'local_git','captured_at':[left['captured_at'],right['captured_at']]})
            for item in workspaces:
                item['path_count']=len(item['paths'])
                item['paths']=self.compact_paths(item['paths'])
                item['paths_truncated']=len(item['paths'])<item['path_count']
            events = [self.observation_row(r) for r in c.execute(
                'SELECT * FROM git_observations WHERE room_id=? ORDER BY id DESC LIMIT 50', (principal.room_id,))]
            epochs = {r['id']:r['ownership_epoch'] for r in c.execute('SELECT id,ownership_epoch FROM tasks WHERE room_id=?',(principal.room_id,))}
            for item in events:
                item['historical'] = item['ownership_epoch'] != epochs.get(item['task_id'])
                item['path_count']=len(item.pop('paths'))
            branches = [dict(r) for r in c.execute(
                'SELECT * FROM git_branches WHERE room_id=? ORDER BY id DESC LIMIT 50', (principal.room_id,))]
            blocks = []
            for r in c.execute('''SELECT b.* FROM git_conflict_blocks b JOIN tasks t
                ON t.id=b.task_id AND t.room_id=b.room_id WHERE b.room_id=? AND t.cancelled_at IS NULL
                AND b.ownership_epoch=t.ownership_epoch ORDER BY b.id DESC LIMIT 50''', (principal.room_id,)):
                row = dict(r)
                try:
                    conflicts = json.loads(row.pop('conflicts_json'))
                except (TypeError, ValueError):
                    conflicts = []
                row['conflicts'] = [{**conflict, 'paths': self.compact_paths(conflict.get('paths', []), 4000)}
                                    for conflict in conflicts[:5] if isinstance(conflict, dict)]
                try:
                    row['paths'] = self.compact_paths(json.loads(row.pop('paths_json')), 4000)
                except (TypeError, ValueError):
                    row['paths'] = []
                blocks.append(row)
            merges = []
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='git_merge_requests'").fetchone():
                merges = [dict(r) for r in c.execute('''SELECT m.* FROM git_merge_requests m JOIN tasks t
                    ON t.id=m.task_id AND t.room_id=m.room_id WHERE m.room_id=? AND m.state='pending'
                    AND t.cancelled_at IS NULL AND m.ownership_epoch=t.ownership_epoch ORDER BY m.id DESC LIMIT 50''',
                    (principal.room_id,))]
            return {'binding':dict(binding) if binding else None,'can_manage':can_manage,'workspaces':workspaces,
                    'overlaps':overlaps,'events':events,'deliveries':[],'workspaces_truncated':truncated,
                    'git_write_enabled':bool(binding and binding['git_write_enabled']),'branches':branches,
                    'conflict_blocks':blocks,'merge_requests':merges}

    def read_observation(self,token,observation_id):
        if type(observation_id) is not int or not 0<observation_id<2**63:
            raise ValidationError('Expected a positive observation identifier')
        with self.db.connect() as c:
            principal=self.identity.resolve(c,token)
            row=c.execute('SELECT * FROM git_observations WHERE room_id=? AND id=?',(principal.room_id,observation_id)).fetchone()
            if row is None:raise NotFound('Observation not found')
            return self.observation_row(row)

    @staticmethod
    def compact_paths(paths,limit=8000):
        result=[];size=0
        for path in paths:
            size+=len(json.dumps(path).encode())+2
            if size>limit or len(result)>=100:break
            result.append(path)
        return result
