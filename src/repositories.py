"""Project-scoped immutable local Git observations; never server-verified facts."""
from datetime import datetime, timedelta, timezone
from itertools import combinations
import hashlib
import json
import re

from .errors import AccessDenied, Conflict, NotFound, ValidationError
from .git_workspace import normalize_repository


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


def visible_task(connection, principal, task_id, *, manager=False):
    if type(task_id) is not int or not 0<task_id<2**63:
        raise ValidationError('Task id must be a positive integer')
    task = connection.execute('SELECT * FROM tasks WHERE room_id=? AND id=?', (principal.room_id, task_id)).fetchone()
    if task is None:
        raise NotFound('Task not found')
    if not manager and (task['state'] != 'claimed' or task['owner_member_id'] != principal.member_id):
        raise AccessDenied('Claimed task owner required')
    return task


class RepositoryStore:
    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        with self.db.connect(write=True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS repo_bindings (
                room_id TEXT PRIMARY KEY REFERENCES rooms(id), repository TEXT NOT NULL,
                bound_by TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(bound_by,room_id) REFERENCES members(id,room_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS git_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                member_id TEXT NOT NULL, task_id INTEGER NOT NULL, workspace_id TEXT NOT NULL,
                repository TEXT NOT NULL, branch TEXT NOT NULL, head TEXT NOT NULL,
                paths_json TEXT NOT NULL, captured_at TEXT NOT NULL, received_at TEXT NOT NULL,
                request_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
                UNIQUE(room_id,member_id,request_key),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
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
            c.execute('INSERT INTO repo_bindings VALUES(?,?,?,?)',
                      (principal.room_id, repository, principal.member_id, now().isoformat()))
            return dict(c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone())

    def get_binding(self, token):
        with self.db.connect() as c:
            principal = self.identity.resolve(c, token)
            row = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            return dict(row) if row else None

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
        paths = result['paths']
        if not isinstance(paths, list) or len(paths)>1000:
            raise ValidationError('Expected at most 1000 relative paths')
        for path in paths:
            if (not isinstance(path,str) or not path or len(path)>500 or '\\' in path or ':' in path
                    or '\x00' in path or path.startswith('/') or any(p in ('','..','.git') for p in path.split('/'))):
                raise ValidationError('Expected safe repository-relative paths')
        result['paths'] = sorted(set(paths))
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

    def observe(self, token, task_id, observation):
        data = self.validate_observation(observation)
        payload_hash = hashlib.sha256(json.dumps([task_id,data],sort_keys=True).encode()).hexdigest()
        with self.db.connect(write=True) as c:
            principal = self.identity.resolve(c, token, required_kind='agent')
            visible_task(c, principal, task_id)
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if not binding or binding['repository'] != data['repository']:
                raise Conflict('Local repository does not match the project binding')
            existing = c.execute('''SELECT * FROM git_observations
                WHERE room_id=? AND member_id=? AND request_key=?''',
                (principal.room_id,principal.member_id,data['request_key'])).fetchone()
            if existing:
                if existing['payload_hash'] != payload_hash:
                    raise Conflict('Request key already has another payload')
                return self.observation_row(existing)
            row = c.execute('''INSERT INTO git_observations(room_id,member_id,task_id,workspace_id,
                repository,branch,head,paths_json,captured_at,received_at,request_key,payload_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (principal.room_id,principal.member_id,task_id,data['workspace_id'],data['repository'],
                 data['branch'],data['head'],json.dumps(data['paths']),data['captured_at'],now().isoformat(),
                 data['request_key'],payload_hash))
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
            rows = c.execute('''SELECT g.* FROM git_observations g WHERE g.room_id=? AND NOT EXISTS
                (SELECT 1 FROM git_observations n WHERE n.room_id=g.room_id AND n.member_id=g.member_id
                 AND n.workspace_id=g.workspace_id AND (n.captured_at>g.captured_at OR
                     (n.captured_at=g.captured_at AND n.id>g.id))) ORDER BY g.id DESC LIMIT 51''', (principal.room_id,)).fetchall()
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
            for item in events:
                item['path_count']=len(item.pop('paths'))
            return {'binding':dict(binding) if binding else None,'can_manage':can_manage,'workspaces':workspaces,
                    'overlaps':overlaps,'events':events,'deliveries':[],'workspaces_truncated':truncated}

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
