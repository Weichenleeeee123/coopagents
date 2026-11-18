"""Durable project-scoped GitHub authorization and current remote evidence."""
from datetime import timedelta
import hashlib
import hmac
import json
import math
import re
import secrets
import threading

from .errors import AccessDenied, Conflict, NotFound, ValidationError
from .github_app import GitHubError, positive_id, complete_sha
from .git_workspace import branch_name, parse_task_branch_name  # noqa: F401  (re-exported; delivery and callers import it here)
from .repositories import now, require_manager, timestamp, visible_task


EVENTS = {'push','pull_request','check_run','check_suite','status','release','installation','installation_repositories'}
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
MAX_REFS = 100
MAX_EVIDENCE_BYTES = 450000
MAX_SNAPSHOT_BYTES = 500000


def state_hash(state):
    if not isinstance(state,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',state):
        raise AccessDenied('GitHub authorization state not accepted')
    return hashlib.sha256(state.encode()).hexdigest()


class GitHubSync:
    def __init__(self,identity,repositories,app):
        self.identity,self.repositories,self.app,self.db=identity,repositories,app,identity.db
        self._user_tokens={}
        self._token_lock=threading.RLock()
        self._process_lock=threading.Lock()
        with self.db.connect(write=True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS github_connections (
                room_id TEXT PRIMARY KEY REFERENCES rooms(id), installation_id INTEGER NOT NULL,
                repository_id INTEGER NOT NULL, full_name TEXT NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                sync_at TEXT, bound_by TEXT NOT NULL, authorized_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS github_oauth_states (
                state_hash TEXT PRIMARY KEY, room_id TEXT NOT NULL, member_id TEXT NOT NULL,
                repository TEXT NOT NULL, installation_id INTEGER,
                expires_at TEXT NOT NULL, callback_started INTEGER NOT NULL DEFAULT 0,
                candidate_json TEXT, used_at TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS github_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, branch TEXT NOT NULL, pr_number INTEGER NOT NULL,
                linked_by TEXT NOT NULL, linked_at TEXT NOT NULL,
                UNIQUE(room_id,task_id,branch,pr_number),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            # Separate additive table preserves the old unique branch/PR constraint and its rows.
            c.execute('''CREATE TABLE IF NOT EXISTS github_commit_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, commit_sha TEXT NOT NULL,
                linked_by TEXT NOT NULL, linked_at TEXT NOT NULL,
                UNIQUE(room_id,task_id,commit_sha),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS github_release_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, release_id INTEGER NOT NULL,
                linked_by TEXT NOT NULL, linked_at TEXT NOT NULL,
                UNIQUE(room_id,task_id,release_id),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            for table in ('github_refs', 'github_commit_refs', 'github_release_refs'):
                if 'ownership_epoch' not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN ownership_epoch INTEGER NOT NULL DEFAULT 0')
            c.execute('''CREATE TABLE IF NOT EXISTS github_evidence (
                room_id TEXT PRIMARY KEY REFERENCES rooms(id), revision INTEGER NOT NULL,
                deliveries_json TEXT NOT NULL, pending_json TEXT NOT NULL, sync_at TEXT NOT NULL)''')
            if 'discovery_json' not in {r['name'] for r in c.execute('PRAGMA table_info(github_evidence)')}:
                c.execute("ALTER TABLE github_evidence ADD COLUMN discovery_json TEXT NOT NULL DEFAULT '{}' ")
            if 'releases_json' not in {r['name'] for r in c.execute('PRAGMA table_info(github_evidence)')}:
                c.execute("ALTER TABLE github_evidence ADD COLUMN releases_json TEXT NOT NULL DEFAULT '[]'")
            if 'unattributed_json' not in {r['name'] for r in c.execute('PRAGMA table_info(github_evidence)')}:
                c.execute("ALTER TABLE github_evidence ADD COLUMN unattributed_json TEXT NOT NULL DEFAULT '[]'")
            c.execute('''CREATE TABLE IF NOT EXISTS git_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, ownership_epoch INTEGER NOT NULL,
                request_key TEXT NOT NULL, branch TEXT NOT NULL, head_sha TEXT NOT NULL,
                base_branch TEXT NOT NULL, pr_number INTEGER, pr_url TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL, delivered_by TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(room_id,task_id,request_key),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS git_merge_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, ownership_epoch INTEGER NOT NULL,
                pr_number INTEGER NOT NULL, pr_url TEXT NOT NULL DEFAULT '',
                branch TEXT NOT NULL, head_sha TEXT NOT NULL, base_branch TEXT NOT NULL,
                state TEXT NOT NULL, request_key TEXT NOT NULL, requested_by TEXT NOT NULL,
                merge_sha TEXT NOT NULL DEFAULT '', merged_by TEXT NOT NULL DEFAULT '',
                merged_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(room_id,task_id,ownership_epoch),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id))''')
            if 'write_scope_verified' not in {r['name'] for r in c.execute('PRAGMA table_info(github_connections)')}:
                c.execute('ALTER TABLE github_connections ADD COLUMN write_scope_verified INTEGER NOT NULL DEFAULT 0')
            c.execute('''CREATE TABLE IF NOT EXISTS github_inbox (
                delivery_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, event TEXT NOT NULL,
                installation_id INTEGER NOT NULL, repository_id INTEGER,
                received_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL DEFAULT '',
                last_error TEXT, completed_at TEXT)''')
            c.execute('CREATE INDEX IF NOT EXISTS github_inbox_queue ON github_inbox(status,next_attempt_at)')
            c.execute('''CREATE TABLE IF NOT EXISTS github_rate_limits (
                installation_id INTEGER PRIMARY KEY, retry_at TEXT NOT NULL)''')

    def _enabled(self):
        if not self.app.enabled: raise AccessDenied('GitHub App is not configured')

    def _prune_tokens(self):
        with self._token_lock:
            for key in list(self._user_tokens):
                if self._user_tokens[key][1]<=now(): self._user_tokens.pop(key,None)

    def begin_authorization(self,token,installation_id=None):
        self._enabled()
        if installation_id is not None: positive_id(installation_id)
        state=secrets.token_urlsafe(32)
        with self.db.connect(write=True) as c:
            principal=self.identity.resolve(c,token,required_kind='web')
            require_manager(self.identity,c,principal)
            binding=c.execute('SELECT repository FROM repo_bindings WHERE room_id=?',(principal.room_id,)).fetchone()
            if not binding or not binding['repository'].startswith('github.com/'):
                raise Conflict('Bind a GitHub repository before authorization')
            count=c.execute('SELECT COUNT(*) FROM github_oauth_states WHERE expires_at>? AND used_at IS NULL',(now().isoformat(),)).fetchone()[0]
            if count>=1000: raise Conflict('Too many pending GitHub authorizations')
            c.execute('''INSERT INTO github_oauth_states(state_hash,room_id,member_id,repository,installation_id,expires_at)
                VALUES(?,?,?,?,?,?)''',(state_hash(state),principal.room_id,principal.member_id,binding['repository'],installation_id,(now()+timedelta(minutes=10)).isoformat()))
        return {'state':state,'authorization_url':self.app.authorization_url(state)}

    @staticmethod
    def _valid_state(c,key):
        row=c.execute('SELECT * FROM github_oauth_states WHERE state_hash=?',(key,)).fetchone()
        if not row or row['used_at'] or timestamp(row['expires_at'])<=now():
            raise AccessDenied('GitHub authorization state not accepted')
        return dict(row)

    def complete_authorization(self,state,code):
        self._enabled();key=state_hash(state)
        with self.db.connect(write=True) as c:
            row=self._valid_state(c,key)
            if row['callback_started']: raise AccessDenied('GitHub authorization callback already used')
            c.execute('UPDATE github_oauth_states SET callback_started=1 WHERE state_hash=?',(key,))
        user_token=self.app.exchange_code(code)
        candidate=self.app.verify_user_repository(user_token,row['repository'],row['installation_id'])
        self._prune_tokens()
        with self._token_lock:
            if len(self._user_tokens)>=1000: raise Conflict('Too many pending GitHub authorizations')
            self._user_tokens[key]=(user_token,timestamp(row['expires_at']))
        with self.db.connect(write=True) as c:
            self._valid_state(c,key)
            c.execute('UPDATE github_oauth_states SET candidate_json=? WHERE state_hash=?',(json.dumps(candidate),key))
        return {'ready':True}

    def finish_authorization(self,token,state):
        self._enabled();key=state_hash(state)
        with self.db.connect() as c:
            principal=self.identity.resolve(c,token,required_kind='web')
            require_manager(self.identity,c,principal)
            row=self._valid_state(c,key)
            if row['room_id']!=principal.room_id or row['member_id']!=principal.member_id or not row['candidate_json']:
                raise AccessDenied('GitHub authorization initiator required')
        self._prune_tokens()
        with self._token_lock: ephemeral=self._user_tokens.get(key)
        if not ephemeral: raise AccessDenied('Restart GitHub authorization after server restart')
        candidate=json.loads(row['candidate_json'])
        fresh=self.app.verify_user_repository(ephemeral[0],row['repository'],candidate['installation_id'])
        if fresh!=candidate: raise AccessDenied('GitHub repository authorization changed')
        self.app.verify_repository(candidate['installation_id'],candidate['repository_id'],candidate['full_name'])
        with self.db.connect(write=True) as c:
            principal=self.identity.resolve(c,token,required_kind='web')
            require_manager(self.identity,c,principal)
            current=self._valid_state(c,key)
            if current['candidate_json']!=row['candidate_json'] or current['member_id']!=principal.member_id:
                raise AccessDenied('GitHub authorization state changed')
            binding=c.execute('SELECT repository FROM repo_bindings WHERE room_id=?',(principal.room_id,)).fetchone()
            if not binding or binding['repository']!=row['repository']: raise Conflict('Repository binding changed')
            existing=c.execute('SELECT * FROM github_connections WHERE room_id=?',(principal.room_id,)).fetchone()
            if existing and existing['repository_id']!=candidate['repository_id']:
                raise Conflict('GitHub stable repository identity changed')
            c.execute('''INSERT INTO github_connections(room_id,installation_id,repository_id,full_name,status,bound_by,authorized_at)
                VALUES(?,?,?,?, 'active',?,?) ON CONFLICT(room_id) DO UPDATE SET
                installation_id=excluded.installation_id,status='active',revision=revision+1,
                bound_by=excluded.bound_by,authorized_at=excluded.authorized_at,sync_at=NULL''',
                (principal.room_id,candidate['installation_id'],candidate['repository_id'],candidate['full_name'],principal.member_id,now().isoformat()))
            c.execute('UPDATE github_oauth_states SET used_at=? WHERE state_hash=?',(now().isoformat(),key))
        with self._token_lock: self._user_tokens.pop(key,None)
        return self.snapshot(token)['connection']

    def associate(self,token,task_id,branch='',pr_number=None,commit_sha='',release_id=None,session_key=None,ownership_epoch=None):
        self._enabled()
        if branch: branch_name(branch)
        elif not isinstance(branch,str): raise ValidationError('Expected branch text')
        if pr_number is not None: positive_id(pr_number)
        if not isinstance(commit_sha,str): raise ValidationError('Expected a complete commit SHA')
        if commit_sha: complete_sha(commit_sha)
        if release_id is not None: positive_id(release_id)
        reference_count=sum((bool(branch),pr_number is not None,bool(commit_sha),release_id is not None))
        if reference_count!=1:
            raise ValidationError('Specify exactly one branch, PR, commit or release')
        with self.db.connect(write=True) as c:
            return self._associate_in_transaction(c,token,task_id,branch,pr_number,commit_sha,release_id,session_key,ownership_epoch)

    def _associate_in_transaction(self,c,token,task_id,branch='',pr_number=None,commit_sha='',release_id=None,session_key=None,ownership_epoch=None):
        principal=self.identity.resolve(c,token)
        if principal.kind=='web': require_manager(self.identity,c,principal)
        task = visible_task(c,principal,task_id,manager=principal.kind=='web',session_key=session_key,ownership_epoch=ownership_epoch)
        conn=c.execute("SELECT * FROM github_connections WHERE room_id=? AND status='active'",(principal.room_id,)).fetchone()
        if not conn: raise Conflict('GitHub repository is not authorized')
        if commit_sha:
            existing=c.execute('SELECT * FROM github_commit_refs WHERE room_id=? AND task_id=? AND commit_sha=?',
                (principal.room_id,task_id,commit_sha)).fetchone()
        elif release_id is not None:
            existing=c.execute('SELECT * FROM github_release_refs WHERE room_id=? AND task_id=? AND release_id=?',
                (principal.room_id,task_id,release_id)).fetchone()
        else:
            existing=c.execute('SELECT * FROM github_refs WHERE room_id=? AND task_id=? AND branch=? AND pr_number=?',
                (principal.room_id,task_id,branch,pr_number or 0)).fetchone()
        if existing: return dict(existing)
        count=c.execute('''SELECT (SELECT COUNT(*) FROM github_refs WHERE room_id=?) +
            (SELECT COUNT(*) FROM github_commit_refs WHERE room_id=?) +
            (SELECT COUNT(*) FROM github_release_refs WHERE room_id=?)''',
            (principal.room_id,principal.room_id,principal.room_id)).fetchone()[0]
        if count>=MAX_REFS: raise ValidationError('Project GitHub reference limit is 100')
        if commit_sha:
            c.execute('''INSERT OR IGNORE INTO github_commit_refs(room_id,task_id,commit_sha,linked_by,linked_at,ownership_epoch)
                VALUES(?,?,?,?,?,?)''',(principal.room_id,task_id,commit_sha,principal.member_id,now().isoformat(),task['ownership_epoch']))
            c.execute('UPDATE github_connections SET revision=revision+1 WHERE room_id=?',(principal.room_id,))
            return dict(c.execute('SELECT * FROM github_commit_refs WHERE room_id=? AND task_id=? AND commit_sha=?',
                (principal.room_id,task_id,commit_sha)).fetchone())
        if release_id is not None:
            c.execute('''INSERT OR IGNORE INTO github_release_refs(room_id,task_id,release_id,linked_by,linked_at,ownership_epoch)
                VALUES(?,?,?,?,?,?)''',(principal.room_id,task_id,release_id,principal.member_id,now().isoformat(),task['ownership_epoch']))
            c.execute('UPDATE github_connections SET revision=revision+1 WHERE room_id=?',(principal.room_id,))
            return dict(c.execute('SELECT * FROM github_release_refs WHERE room_id=? AND task_id=? AND release_id=?',
                (principal.room_id,task_id,release_id)).fetchone())
        c.execute('''INSERT OR IGNORE INTO github_refs(room_id,task_id,branch,pr_number,linked_by,linked_at,ownership_epoch)
            VALUES(?,?,?,?,?,?,?)''',(principal.room_id,task_id,branch,pr_number or 0,principal.member_id,now().isoformat(),task['ownership_epoch']))
        c.execute('UPDATE github_connections SET revision=revision+1 WHERE room_id=?',(principal.room_id,))
        return dict(c.execute('SELECT * FROM github_refs WHERE room_id=? AND task_id=? AND branch=? AND pr_number=?',
            (principal.room_id,task_id,branch,pr_number or 0)).fetchone())

    def _write_delivery(self, c, token, task_id, branch, head_sha, base_branch, request_key,
                        session_key, ownership_epoch, state, pr_number, pr_url, mark_write_scope):
        """Persist one delivery attempt: refs, delivery row, pushed branch state."""
        principal = self.identity.resolve(c, token, required_kind='agent')
        task = visible_task(c, principal, task_id, session_key=session_key, ownership_epoch=ownership_epoch)
        self._associate_in_transaction(c, token, task_id, branch=branch,
                                       session_key=session_key, ownership_epoch=ownership_epoch)
        if pr_number is not None:
            self._associate_in_transaction(c, token, task_id, pr_number=pr_number,
                                           session_key=session_key, ownership_epoch=ownership_epoch)
        stamp = now().isoformat()
        c.execute('''INSERT INTO git_deliveries(room_id,task_id,ownership_epoch,request_key,branch,head_sha,
            base_branch,pr_number,pr_url,state,delivered_by,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(room_id,task_id,request_key) DO UPDATE SET head_sha=excluded.head_sha,
            base_branch=excluded.base_branch,pr_number=excluded.pr_number,pr_url=excluded.pr_url,
            state=excluded.state,updated_at=excluded.updated_at''',
            (principal.room_id, task_id, task['ownership_epoch'], request_key, branch, head_sha,
             base_branch, pr_number, pr_url, state, principal.member_id, stamp, stamp))
        c.execute('''UPDATE git_branches SET pushed_sha=?,pushed_at=? WHERE room_id=? AND task_id=?
            AND ownership_epoch=?''', (head_sha, stamp, principal.room_id, task_id, task['ownership_epoch']))
        if mark_write_scope:
            c.execute('UPDATE github_connections SET write_scope_verified=1 WHERE room_id=?', (principal.room_id,))
        return dict(c.execute('''SELECT * FROM git_deliveries WHERE room_id=? AND task_id=?
            AND request_key=?''', (principal.room_id, task_id, request_key)).fetchone())

    def open_pr(self, token, task_id, branch, head_sha, base_branch, title, body='', request_key=None,
                session_key=None, ownership_epoch=None, preview=False):
        """Record a pushed delivery and open its draft PR (W2).

        Lookup-before-create: an existing open PR for the head branch is reused,
        so retries and re-deliveries never open duplicates. A PR creation
        failure after a successful push records state 'pushed' and raises, so a
        retry with the same request_key resumes from lookup. Preview runs every
        local precondition and describes the API call without minting a token,
        calling GitHub, or writing anything.
        """
        branch_name(branch); branch_name(base_branch)
        if branch == base_branch:
            raise ValidationError('PR head and base must differ')
        complete_sha(head_sha)
        if (not isinstance(title, str) or not 1 <= len(title) <= 250 or title != title.strip()
                or any(ord(char) < 32 for char in title)):
            raise ValidationError('PR title is invalid')
        if (not isinstance(body, str) or len(body) > 10000
                or any(ord(char) < 32 and char not in '\n\t' for char in body)):
            raise ValidationError('PR body is invalid')
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200:
            raise ValidationError('Invalid request key')
        if type(preview) is not bool:
            raise ValidationError('Expected a preview flag')
        with self.db.connect() as c:
            principal = self.identity.resolve(c, token, required_kind='agent')
            task = visible_task(c, principal, task_id, session_key=session_key, ownership_epoch=ownership_epoch)
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if not binding:
                raise Conflict('Project repository is not bound')
            if not binding['git_write_enabled']:
                raise Conflict('Git write path is not enabled for this space')
            recorded = c.execute('''SELECT * FROM git_branches WHERE room_id=? AND task_id=?
                AND ownership_epoch=?''', (principal.room_id, task_id, task['ownership_epoch'])).fetchone()
            if not recorded or recorded['branch'] != branch:
                raise Conflict('Task branch is not recorded for the current execution')
            existing = c.execute('''SELECT * FROM git_deliveries WHERE room_id=? AND task_id=?
                AND request_key=?''', (principal.room_id, task_id, request_key)).fetchone()
            if existing and existing['state'] == 'pr_opened':
                result = dict(existing)
                result['created'] = False
                return result
            conn = c.execute("SELECT * FROM github_connections WHERE room_id=? AND status='active'",
                             (principal.room_id,)).fetchone()
            connection = dict(conn) if conn else None
            checked, fresh, conflicts = self.repositories.evaluate_gate(
                c, principal.room_id, principal.member_id, task_id, task['ownership_epoch'])
            display = [{**conflict, 'paths': self.repositories.compact_paths(conflict['paths'], 4000)}
                       for conflict in conflicts]
        if preview:
            return {'preview': True, 'task_id': task_id, 'branch': branch, 'head_sha': head_sha,
                    'base_branch': base_branch, 'title': title,
                    'api_call': {'method': 'POST',
                                 'path': '/repos/' + (connection['full_name'] if connection else '<repository>') + '/pulls',
                                 'head': branch, 'base': base_branch, 'draft': True},
                    'connection': 'active' if connection else 'missing',
                    'existing_state': existing['state'] if existing else None,
                    'paths_checked': checked, 'fresh_checkpoint': fresh,
                    'conflicts': display, 'blocked': bool(conflicts)}
        if not fresh:
            raise Conflict('A fresh checkpoint is required before delivery; call repo_checkpoint first')
        if conflicts:
            with self.db.connect(write=True) as c:
                self.repositories.record_conflict_block(
                    c, principal.room_id, principal.member_id, task_id, task['ownership_epoch'],
                    'delivery', checked, conflicts)
            raise Conflict(self.repositories.conflict_message(conflicts))
        self._enabled()
        if not connection:
            raise Conflict('GitHub repository is not authorized')
        found = self.app.find_open_pr(connection['installation_id'], connection['repository_id'],
                                      connection['full_name'], branch)
        created = False
        if found is not None:
            pr = found
        else:
            try:
                pr = self.app.create_pull_request(connection['installation_id'], connection['repository_id'],
                                                  connection['full_name'], branch, base_branch, title, body)
                created = True
            except GitHubError as failure:
                # The branch is already pushed; a create that raced another
                # delivery surfaces through lookup instead of erroring.
                try:
                    found = self.app.find_open_pr(connection['installation_id'], connection['repository_id'],
                                                  connection['full_name'], branch)
                except GitHubError:
                    found = None
                if found is not None:
                    pr = found
                else:
                    try:
                        with self.db.connect(write=True) as c:
                            self._write_delivery(c, token, task_id, branch, head_sha, base_branch,
                                                 request_key, session_key, ownership_epoch,
                                                 'pushed', None, '', False)
                    except Exception:
                        pass  # Best-effort evidence; the original failure is the report.
                    raise
        if not isinstance(pr, dict):
            raise GitHubError('GitHub PR response is invalid')
        try:
            number = positive_id(pr['number'])
            url = pr['url']
            if not isinstance(url, str) or not url.startswith('https://github.com/') or len(url) > 500:
                raise GitHubError('GitHub PR response is invalid')
        except (KeyError, TypeError, ValidationError):
            raise GitHubError('GitHub PR response is invalid') from None
        with self.db.connect(write=True) as c:
            result = self._write_delivery(c, token, task_id, branch, head_sha, base_branch,
                                          request_key, session_key, ownership_epoch,
                                          'pr_opened', number, url, created)
            self.repositories.clear_conflict_block(c, principal.room_id, task_id,
                                                   task['ownership_epoch'], 'delivery')
        result['created'] = created
        return result

    def request_merge(self, token, task_id, pr_number, request_key, session_key=None,
                      ownership_epoch=None, preview=False):
        """Record a human merge request for the task's opened PR (W4).

        Creates a decision card; performs no merge. Re-requesting refreshes
        the recorded head SHA from the latest delivery, so a head that moved
        after a re-delivery can be merged without a stale request wedging it.
        """
        positive_id(pr_number)
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
            delivery = c.execute('''SELECT * FROM git_deliveries WHERE room_id=? AND task_id=?
                AND ownership_epoch=? AND state='pr_opened' ORDER BY id DESC LIMIT 1''',
                (principal.room_id, task_id, task['ownership_epoch'])).fetchone()
            if not delivery or delivery['pr_number'] != pr_number:
                raise Conflict('No opened delivery matches this merge request')
            existing = c.execute('''SELECT * FROM git_merge_requests WHERE room_id=? AND task_id=?
                AND ownership_epoch=?''', (principal.room_id, task_id, task['ownership_epoch'])).fetchone()
            if existing:
                if existing['pr_number'] != pr_number:
                    raise Conflict('A merge request already exists for a different PR')
                if existing['state'] == 'pending' and (existing['head_sha'] != delivery['head_sha']
                                                       or existing['branch'] != delivery['branch']
                                                       or existing['base_branch'] != delivery['base_branch']):
                    if not preview:
                        c.execute('''UPDATE git_merge_requests SET head_sha=?, branch=?, base_branch=?,
                            updated_at=? WHERE id=?''',
                            (delivery['head_sha'], delivery['branch'], delivery['base_branch'],
                             now().isoformat(), existing['id']))
                        return dict(c.execute('SELECT * FROM git_merge_requests WHERE id=?', (existing['id'],)).fetchone())
                return dict(existing)
            if preview:
                return {'preview': True, 'task_id': task_id, 'pr_number': pr_number,
                        'pr_url': delivery['pr_url'], 'branch': delivery['branch'],
                        'head_sha': delivery['head_sha'], 'base_branch': delivery['base_branch'],
                        'ownership_epoch': task['ownership_epoch']}
            row = c.execute('''INSERT INTO git_merge_requests(room_id,task_id,ownership_epoch,pr_number,
                pr_url,branch,head_sha,base_branch,state,request_key,requested_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (principal.room_id, task_id, task['ownership_epoch'], pr_number, delivery['pr_url'],
                 delivery['branch'], delivery['head_sha'], delivery['base_branch'], 'pending',
                 request_key, principal.member_id, now().isoformat(), now().isoformat()))
            return dict(c.execute('SELECT * FROM git_merge_requests WHERE id=?', (row.lastrowid,)).fetchone())

    @staticmethod
    def _approvals(reviews, author=None):
        """Latest review per reviewer wins; only a standing approval counts.

        The PR author's own approval never counts: GitHub's required-approval
        rules disregard it. When the author is unknown (None), no review is
        excluded and GitHub remains the final enforcer at merge time.
        """
        latest = {}
        for review in reviews:
            latest[review['reviewer']] = review['state']
        return sum(1 for reviewer, state in latest.items()
                   if state == 'APPROVED' and reviewer != author)

    @staticmethod
    def _merge_block_reasons(pr, expected_sha, protection, review_payload):
        """Merge preconditions (W4): head SHA, checks, truncation, protection."""
        reasons = []
        if pr['state'] != 'open':
            return ['PR is not open']
        if pr['head_sha'] != expected_sha:
            reasons.append('PR head moved; re-request the merge for the current head')
        if pr.get('mergeable') is False:
            reasons.append('PR has merge conflicts; resolve them on GitHub')
        if pr.get('checks_truncated') or pr.get('statuses_truncated'):
            reasons.append('check results are truncated; cannot verify all checks')
        failing = sorted({check['name'] for check in pr.get('checks', [])
                          if check.get('conclusion') in ('failure', 'cancelled', 'timed_out', 'action_required')})
        failing += sorted({status['context'] for status in pr.get('statuses', [])
                           if status.get('state') in ('failure', 'error')})
        if failing:
            reasons.append('failing checks: ' + ', '.join(failing[:10]))
        if protection:
            restrictions = protection.get('restrictions') or {}
            if any(restrictions.get(key) for key in ('users', 'teams', 'apps')):
                reasons.append('branch restrictions may exclude the App; merge on GitHub')
            required = ((protection.get('required_status_checks') or {}).get('contexts') or [])
            passing = {check['name'] for check in pr.get('checks', []) if check.get('conclusion') == 'success'}
            passing |= {status['context'] for status in pr.get('statuses', []) if status.get('state') == 'success'}
            missing = [context for context in required if context not in passing]
            if missing:
                reasons.append('required checks not passing: ' + ', '.join(missing[:10]))
            count = ((protection.get('required_pull_request_reviews') or {})
                     .get('required_approving_review_count') or 0)
            if count:
                if review_payload.get('truncated'):
                    reasons.append('review list is truncated; cannot verify approvals')
                elif pr.get('author') is None:
                    reasons.append('cannot verify the PR author; merge on GitHub')
                else:
                    approvals = GitHubSync._approvals(review_payload.get('reviews', []), pr.get('author'))
                    if approvals < count:
                        reasons.append('requires %d approving review(s); %d recorded' % (count, approvals))
        return reasons

    def _mark_merged(self, connection, request, merge_sha, merged_by):
        stamp = now().isoformat()
        connection.execute('''UPDATE git_merge_requests SET state='merged', merge_sha=?, merged_by=?,
            merged_at=?, updated_at=? WHERE id=? AND state='pending' ''',
            (merge_sha, merged_by, stamp, stamp, request['id']))
        connection.execute('''UPDATE git_deliveries SET state='merged', updated_at=? WHERE room_id=?
            AND task_id=? AND ownership_epoch=? AND pr_number=? AND state='pr_opened' ''',
            (stamp, request['room_id'], request['task_id'], request['ownership_epoch'], request['pr_number']))
        return dict(connection.execute('SELECT * FROM git_merge_requests WHERE id=?', (request['id'],)).fetchone())

    def merge_pr(self, token, merge_request_id, preview=False):
        """Execute a human-approved merge (W4, D1: web-only, manager-only).

        Verifies preconditions against live GitHub state, then merges with a
        merge commit guarded by the expected head SHA. A merged PR never
        accepts the task (D6); acceptance stays a separate human act. Preview
        runs the live precondition reads and describes the PUT without merging,
        and never writes — including when the PR is already merged.
        """
        positive_id(merge_request_id)
        if type(preview) is not bool:
            raise ValidationError('Expected a preview flag')
        with self.db.connect() as c:
            principal = self.identity.resolve(c, token, required_kind='web')
            require_manager(self.identity, c, principal)
            request = c.execute('''SELECT * FROM git_merge_requests WHERE id=? AND room_id=?''',
                                (merge_request_id, principal.room_id)).fetchone()
            if not request:
                raise NotFound('Merge request not found')
            request = dict(request)
            binding = c.execute('SELECT * FROM repo_bindings WHERE room_id=?', (principal.room_id,)).fetchone()
            if not binding or not binding['git_write_enabled']:
                raise Conflict('Git write path is not enabled for this space')
            conn = c.execute("SELECT * FROM github_connections WHERE room_id=? AND status='active'",
                             (principal.room_id,)).fetchone()
            if not conn:
                raise Conflict('GitHub repository is not authorized')
            connection = dict(conn)
        if request['state'] == 'merged':
            return request
        self._enabled()
        state = self.app.repository_state(connection['installation_id'], connection['repository_id'],
                                          connection['full_name'], pr_numbers=(request['pr_number'],))
        prs = state.get('pull_requests') if isinstance(state, dict) else None
        pr = next((item for item in prs if isinstance(item, dict) and item.get('number') == request['pr_number']),
                  None) if isinstance(prs, list) else None
        if pr is None:
            raise Conflict('PR is no longer visible to the App; re-check it on GitHub')
        if pr.get('merged'):
            if preview:
                return {'preview': True, 'merge_request_id': request['id'], 'task_id': request['task_id'],
                        'pr_number': request['pr_number'], 'pr_url': request['pr_url'],
                        'head_sha': request['head_sha'], 'base_branch': pr.get('base_branch') or request['base_branch'],
                        'already_merged': True, 'merge_commit_sha': pr.get('merge_commit_sha') or '',
                        'api_call': None, 'checks': pr.get('checks', []), 'statuses': pr.get('statuses', []),
                        'protection': None, 'blocked': False, 'reasons': []}
            with self.db.connect(write=True) as c:
                return self._mark_merged(c, request, pr.get('merge_commit_sha') or '', principal.member_id)
        base = pr.get('base_branch') or request['base_branch']
        protection = self.app.read_branch_protection(connection['installation_id'], connection['repository_id'],
                                                     connection['full_name'], base)
        count = ((protection or {}).get('required_pull_request_reviews') or {}).get('required_approving_review_count') or 0
        review_payload = self.app.read_pull_reviews(connection['installation_id'], connection['repository_id'],
                                                    connection['full_name'], request['pr_number']) if count else {'reviews': [], 'truncated': False}
        reasons = self._merge_block_reasons(pr, request['head_sha'], protection, review_payload)
        if preview:
            return {'preview': True, 'merge_request_id': request['id'], 'task_id': request['task_id'],
                    'pr_number': request['pr_number'], 'pr_url': request['pr_url'],
                    'head_sha': request['head_sha'], 'base_branch': base,
                    'api_call': {'method': 'PUT',
                                 'path': '/repos/' + connection['full_name'] + '/pulls/%d/merge' % request['pr_number'],
                                 'sha': request['head_sha'], 'merge_method': 'merge'},
                    'checks': pr.get('checks', []), 'statuses': pr.get('statuses', []),
                    'protection': protection, 'blocked': bool(reasons), 'reasons': reasons}
        if reasons:
            raise Conflict('Merge blocked: ' + '; '.join(reasons))
        try:
            result = self.app.merge_pull_request(connection['installation_id'], connection['repository_id'],
                                                 connection['full_name'], request['pr_number'], request['head_sha'])
        except GitHubError:
            # A concurrent merge may have completed between the read and the PUT.
            state = self.app.repository_state(connection['installation_id'], connection['repository_id'],
                                              connection['full_name'], pr_numbers=(request['pr_number'],))
            prs = state.get('pull_requests') if isinstance(state, dict) else None
            pr = next((item for item in prs if isinstance(item, dict) and item.get('number') == request['pr_number']),
                      None) if isinstance(prs, list) else None
            if pr is not None and pr.get('merged'):
                with self.db.connect(write=True) as c:
                    return self._mark_merged(c, request, pr.get('merge_commit_sha') or '', principal.member_id)
            raise Conflict('GitHub refused the merge; the PR may conflict or branch protection may block it') from None
        with self.db.connect(write=True) as c:
            merged = self._mark_merged(c, request, result['sha'], principal.member_id)
        try:
            self._reconcile(principal.room_id, token)
        except Exception:
            pass  # Best-effort evidence refresh; the merge record above stands.
        return merged

    def refresh(self,token):
        self._enabled()
        with self.db.connect() as c: principal=self.identity.resolve(c,token)
        self._reconcile(principal.room_id,token)
        return self.snapshot(token)

    def _revoke(self,room_id,revision):
        with self.db.connect(write=True) as c:
            c.execute("UPDATE github_connections SET status='revoked',revision=revision+1 WHERE room_id=? AND revision=?",(room_id,revision))

    @staticmethod
    def _checks_at(sha,item):
        if not isinstance(item,dict) or not isinstance(item.get('checks',[]),list) or not isinstance(item.get('statuses',[]),list):
            raise GitHubError('GitHub commit checks are invalid')
        if len(item.get('checks',[]))>100 or len(item.get('statuses',[]))>100:
            raise GitHubError('GitHub commit checks exceed limit')
        checks=[]
        for check in item.get('checks',[]):
            if isinstance(check,dict) and check.get('head_sha')==sha:
                checks.append({'head_sha':sha,'name':str(check.get('name',''))[:200],
                    'status':str(check.get('status',''))[:40],'conclusion':str(check.get('conclusion') or '')[:40]})
        statuses=[];contexts=set()
        for status in item.get('statuses',[]):
            if isinstance(status,dict) and status.get('head_sha')==sha:
                context=str(status.get('context',''))[:200]
                if context not in contexts:
                    contexts.add(context);statuses.append({'head_sha':sha,'context':context,'state':str(status.get('state',''))[:40]})
        return checks,statuses

    @staticmethod
    def _evidence(state,refs,conn,sync_at):
        if not isinstance(state,dict) or state.get('repository_id')!=conn['repository_id'] or state.get('full_name','').casefold()!=conn['full_name'].casefold():
            raise AccessDenied('GitHub repository identity changed')
        branches=state.get('branches');pulls=state.get('pull_requests')
        commits=state.get('commits',{})
        if (not isinstance(branches,dict) or len(branches)>100 or not isinstance(pulls,list) or len(pulls)>150):
            raise GitHubError('GitHub state is invalid')
        if not isinstance(commits,dict) or len(commits)>150: raise GitHubError('GitHub commit state is invalid')
        releases=state.get('releases',[])
        unavailable_releases=state.get('unavailable_release_ids',[])
        if not isinstance(releases,list) or len(releases)>120 or not isinstance(unavailable_releases,list) or len(unavailable_releases)>100:
            raise GitHubError('GitHub release state is invalid')
        normalized_releases={}
        from urllib.parse import quote
        for release in releases:
            if not isinstance(release,dict): raise GitHubError('GitHub release is invalid')
            try:
                release_id=positive_id(release['release_id'])
                tag=release['tag_name'];name=release['name'];state_name=release['state']
                draft=release['draft'];prerelease=release['prerelease'];assets=release['assets']
                assets_truncated=release['assets_truncated']
                if (release_id in normalized_releases or not isinstance(tag,str) or not tag or len(tag)>250
                        or any(ord(char)<32 for char in tag) or not isinstance(name,str) or len(name)>250
                        or state_name not in ('draft','prerelease','published') or type(draft) is not bool
                        or type(prerelease) is not bool or type(assets_truncated) is not bool
                        or not isinstance(assets,list) or len(assets)>20):
                    raise GitHubError('GitHub release is invalid')
                if state_name!=('draft' if draft else 'prerelease' if prerelease else 'published'):
                    raise GitHubError('GitHub release state is invalid')
                safe_assets=[]
                for asset in assets:
                    if (not isinstance(asset,dict) or set(asset)!={'name','size','digest'}
                            or not isinstance(asset['name'],str) or not asset['name'] or len(asset['name'])>250
                            or type(asset['size']) is not int or not 0<=asset['size']<2**63
                            or (asset['digest'] is not None and (not isinstance(asset['digest'],str) or len(asset['digest'])>100))):
                        raise GitHubError('GitHub release asset metadata is invalid')
                    safe_assets.append(dict(asset))
                published_at=release['published_at'];created_at=release['created_at'];target=release['target_commitish']
                for value in (published_at,created_at):
                    if value is not None and (not isinstance(value,str) or len(value)>50):
                        raise GitHubError('GitHub release timestamp is invalid')
                if not isinstance(target,str) or len(target)>250: raise GitHubError('GitHub release target is invalid')
                normalized_releases[release_id]={'release_id':release_id,'tag_name':tag,'name':name,'state':state_name,
                    'draft':draft,'prerelease':prerelease,'created_at':created_at,'published_at':published_at,
                    'target_commitish':target,'assets':safe_assets,'assets_truncated':assets_truncated,
                    'url':f"https://github.com/{conn['full_name']}/releases/tag/{quote(tag,safe='')}",
                    'repository_id':conn['repository_id'],'source':'github_verified','sync_at':sync_at,'stale':False}
            except (KeyError,TypeError,ValidationError): raise GitHubError('GitHub release is invalid') from None
        unavailable_releases=[positive_id(release_id) for release_id in unavailable_releases]
        normalized=[]
        for pr in pulls:
            if not isinstance(pr,dict): raise GitHubError('GitHub PR is invalid')
            try:
                positive_id(pr['number']);sha=pr['head_sha']
                if not isinstance(sha,str) or not SHA.fullmatch(sha) or pr['state'] not in ('open','closed') or type(pr['merged']) is not bool:
                    raise GitHubError('GitHub PR is invalid')
                checks,statuses=GitHubSync._checks_at(sha,pr)
                normalized.append({'number':pr['number'],'head_sha':sha,'head_repository_id':pr.get('head_repository_id'),
                    'branch':str(pr.get('head_branch',''))[:250],
                    'state':'merged' if pr['merged'] else ('open' if pr['state']=='open' else 'closed_unmerged'),
                    'checks':checks,'statuses':statuses,
                    'checks_truncated':bool(pr.get('checks_truncated')),'statuses_truncated':bool(pr.get('statuses_truncated')),
                    'checks_verified':bool(pr.get('checks_verified',True)),
                    'url':f"https://github.com/{conn['full_name']}/pull/{pr['number']}",
                    'repository_id':conn['repository_id'],'source':'github_verified','sync_at':sync_at,'stale':False})
            except (KeyError,TypeError,ValidationError): raise GitHubError('GitHub PR is invalid') from None
        deliveries=[];associated=set()
        def unavailable(ref):
            return {'task_id':ref['task_id'],'ref_id':ref['id'],'release_id':ref.get('release_id'),
                'branch':ref['branch'],
                'pr_number':ref['pr_number'] or None,'commit_sha':ref.get('commit_sha',''),
                'head_sha':'','repository_id':conn['repository_id'],'state':'unavailable','checks':[],'statuses':[],
                'source':'github_verified','sync_at':sync_at,'stale':False,'url':''}
        for ref in refs:
            if ref.get('release_id') is not None:
                release_id=ref['release_id']
                if release_id in unavailable_releases or release_id not in normalized_releases:
                    deliveries.append(unavailable(ref));continue
                deliveries.append(dict(normalized_releases[release_id],task_id=ref['task_id'],
                    ref_id=ref['id'],ownership_epoch=ref.get('ownership_epoch',0)))
            elif ref.get('commit_sha'):
                sha=ref['commit_sha']
                if sha not in commits or sha in state.get('unavailable_commit_shas',[]):
                    deliveries.append(unavailable(ref));continue
                checks,statuses=GitHubSync._checks_at(sha,commits[sha])
                deliveries.append({'task_id':ref['task_id'],'ref_id':ref['id'],'branch':'','commit_sha':sha,
                    'head_sha':sha,'repository_id':conn['repository_id'],'state':'pushed','checks':checks,'statuses':statuses,
                    'checks_truncated':bool(commits[sha].get('checks_truncated')),'statuses_truncated':bool(commits[sha].get('statuses_truncated')),
                    'source':'github_verified','sync_at':sync_at,'stale':False,'url':f"https://github.com/{conn['full_name']}/commit/{sha}"})
            elif ref['pr_number']:
                found=False
                for pr in normalized:
                    if pr['number']==ref['pr_number']:
                        found=True
                        deliveries.append(dict(pr,task_id=ref['task_id'],pr_number=pr['number'],ref_id=ref['id']))
                        associated.add(pr['number'])
                if not found: deliveries.append(unavailable(ref))
            elif ref['branch'] in branches:
                sha=branches[ref['branch']]
                if not isinstance(sha,str) or not SHA.fullmatch(sha): raise GitHubError('GitHub branch SHA is invalid')
                matching=[p for p in normalized if p['head_repository_id']==conn['repository_id'] and p['branch']==ref['branch'] and p['head_sha']==sha]
                if matching:
                    for pr in matching:
                        deliveries.append(dict(pr,task_id=ref['task_id'],pr_number=pr['number'],ref_id=ref['id']))
                        associated.add(pr['number'])
                else:
                    checks,statuses=GitHubSync._checks_at(sha,commits.get(sha,{}))
                    deliveries.append({'task_id':ref['task_id'],'ref_id':ref['id'],'branch':ref['branch'],
                        'head_sha':sha,'repository_id':conn['repository_id'],'state':'pushed','checks':checks,'statuses':statuses,
                        'checks_truncated':bool(commits.get(sha,{}).get('checks_truncated')),'statuses_truncated':bool(commits.get(sha,{}).get('statuses_truncated')),
                        'source':'github_verified','sync_at':sync_at,'stale':False,'url':''})
            else: deliveries.append(unavailable(ref))
        by_ref = {ref['id']: ref for ref in refs}
        for delivery in deliveries:
            delivery['ownership_epoch'] = by_ref[delivery['ref_id']].get('ownership_epoch', 0)
        discovery=state.get('release_discovery',{'limit':20,'truncated':False})
        if (not isinstance(discovery,dict) or set(discovery)-{'limit','truncated'}
                or ('limit' in discovery and (type(discovery['limit']) is not int or not 1<=discovery['limit']<=20))
                or ('truncated' in discovery and type(discovery['truncated']) is not bool)):
            raise GitHubError('GitHub release discovery bounds are invalid')
        unattributed=GitHubSync._classify_discovered(state,refs,branches,commits,normalized,sync_at)
        return deliveries,[p for p in normalized if p['number'] not in associated],list(normalized_releases.values()),discovery,unattributed

    @staticmethod
    def _classify_discovered(state,refs,branches,commits,normalized,sync_at):
        """Classify discovered branches: governed, task-named direct, or unattributed.

        Presentation only: nothing here creates refs, associates tasks, or
        blocks. A branch matching a task branch name is attributed to that
        task with source 'direct'; snapshot() later drops entries whose task
        is cancelled or whose epoch no longer matches. The default branch is
        reported only through its own entry, never duplicated below.
        """
        discovered=state.get('discovered_branches',[])
        if not isinstance(discovered,list) or len(discovered)>50:
            raise GitHubError('GitHub branch discovery is invalid')
        default_branch=state.get('default_branch')
        if default_branch is not None and not isinstance(default_branch,str):
            raise GitHubError('GitHub default branch is invalid')
        governed={ref['branch'] for ref in refs if ref.get('branch')}
        known={sha for sha in branches.values() if isinstance(sha,str) and SHA.fullmatch(sha)}
        known.update(sha for sha in commits if isinstance(sha,str) and SHA.fullmatch(sha))
        for pr in normalized:
            known.add(pr['head_sha'])
        for pr in state.get('pull_requests',[]):
            merge_sha=pr.get('merge_commit_sha') if isinstance(pr,dict) else None
            if isinstance(merge_sha,str) and SHA.fullmatch(merge_sha):
                known.add(merge_sha)
        unattributed=[]
        for item in discovered:
            if not isinstance(item,dict):
                raise GitHubError('GitHub branch discovery is invalid')
            name,sha=item.get('branch'),item.get('head_sha')
            try: branch_name(name)
            except ValidationError: raise GitHubError('GitHub branch discovery is invalid') from None
            if not isinstance(sha,str) or not SHA.fullmatch(sha):
                raise GitHubError('GitHub branch discovery is invalid')
            if name in governed or name==default_branch:
                continue
            parsed=parse_task_branch_name(name)
            if parsed:
                unattributed.append({'kind':'direct_branch','task_id':parsed['task_id'],
                    'ownership_epoch':parsed['ownership_epoch'],'branch':name,'head_sha':sha,
                    'source':'direct','sync_at':sync_at,'stale':False})
            else:
                unattributed.append({'kind':'unattributed_branch','branch':name,'head_sha':sha,
                    'source':'direct','sync_at':sync_at,'stale':False})
        default_head=state.get('default_branch_head_sha')
        if default_branch and default_head:
            if not isinstance(default_head,str) or not SHA.fullmatch(default_head):
                raise GitHubError('GitHub default branch head is invalid')
            if default_head not in known:
                unattributed.append({'kind':'default_branch_direct_push','branch':default_branch,
                    'head_sha':default_head,'source':'direct','sync_at':sync_at,'stale':False})
        return unattributed

    def _reconcile(self,room_id,token=None):
        with self.db.connect(write=True) as c:
            if token: self.identity.resolve(c,token)
            conn=c.execute("SELECT * FROM github_connections WHERE room_id=? AND status='active'",(room_id,)).fetchone()
            if not conn: return False
            limit=c.execute('SELECT retry_at FROM github_rate_limits WHERE installation_id=?',(conn['installation_id'],)).fetchone()
            if limit and timestamp(limit['retry_at'])>now():
                remaining=math.ceil((timestamp(limit['retry_at'])-now()).total_seconds())
                raise GitHubError('GitHub rate limited',retryable=True,retry_after=remaining,rate_limited=True)
            c.execute('UPDATE github_connections SET revision=revision+1 WHERE room_id=?',(room_id,))
            conn=dict(conn);conn['revision']+=1
            refs=[dict(r) for r in c.execute('SELECT * FROM github_refs WHERE room_id=?',(room_id,))]
            refs.extend(dict(dict(r),id='commit:'+str(r['id']),branch='',pr_number=0)
                for r in c.execute('SELECT * FROM github_commit_refs WHERE room_id=?',(room_id,)))
            refs.extend(dict(dict(r),id='release:'+str(r['id']),branch='',pr_number=0,commit_sha='')
                for r in c.execute('SELECT * FROM github_release_refs WHERE room_id=?',(room_id,)))
            if len(refs)>MAX_REFS: raise GitHubError('Project GitHub references exceed limit')
            previous=c.execute('SELECT * FROM github_evidence WHERE room_id=?',(room_id,)).fetchone()
            # Previously matched PRs remain candidates after they close; each is fetched again.
            candidates=set()
            if previous and conn['sync_at'] and conn['sync_at']==previous['sync_at']:
                candidates={r['pr_number'] for r in json.loads(previous['deliveries_json']) if r.get('pr_number')}
            explicit={r['pr_number'] for r in refs if r['pr_number']}
            prior_candidates=sorted(candidates-explicit)[:max(0,MAX_REFS-len(refs))]
            explicit_releases=sorted({r['release_id'] for r in refs if r.get('release_id') is not None})
        try:
            state=self.app.repository_state(conn['installation_id'],conn['repository_id'],conn['full_name'],
                branches=sorted({r['branch'] for r in refs if r['branch']}),pr_numbers=sorted(explicit.union(prior_candidates)),
                commit_shas=sorted({r['commit_sha'] for r in refs if r.get('commit_sha')}),release_ids=explicit_releases)
            sync_at=now().isoformat();deliveries,pending,releases,release_discovery,unattributed=self._evidence(state,refs,conn,sync_at)
            discovery=state.get('discovery',{})
            if (not isinstance(discovery,dict) or set(discovery)-{'limit','truncated','state'}
                    or ('limit' in discovery and (type(discovery['limit']) is not int or not 1<=discovery['limit']<=50))):
                raise GitHubError('GitHub discovery bounds are invalid')
            branch_discovery=state.get('branch_discovery',{'limit':50,'truncated':False})
            if (not isinstance(branch_discovery,dict) or set(branch_discovery)-{'limit','truncated'}
                    or ('limit' in branch_discovery and (type(branch_discovery['limit']) is not int or not 1<=branch_discovery['limit']<=50))
                    or ('truncated' in branch_discovery and type(branch_discovery['truncated']) is not bool)):
                raise GitHubError('GitHub branch discovery bounds are invalid')
            discovery['releases']=release_discovery
            discovery['branches']=branch_discovery
            deliveries_json=json.dumps(deliveries);pending_json=json.dumps(pending);discovery_json=json.dumps(discovery);releases_json=json.dumps(releases);unattributed_json=json.dumps(unattributed)
            if len((deliveries_json+pending_json+discovery_json+releases_json+unattributed_json).encode())>MAX_EVIDENCE_BYTES:
                raise GitHubError('GitHub evidence exceeds output budget')
        except AccessDenied:
            self._revoke(room_id,conn['revision'])
            raise
        except GitHubError as failure:
            if failure.rate_limited:
                retry_at=(now()+timedelta(seconds=max(60,failure.retry_after))).isoformat()
                with self.db.connect(write=True) as c:
                    c.execute('''INSERT INTO github_rate_limits VALUES(?,?) ON CONFLICT(installation_id)
                        DO UPDATE SET retry_at=MAX(retry_at,excluded.retry_at)''',(conn['installation_id'],retry_at))
            raise
        with self.db.connect(write=True) as c:
            if token: self.identity.resolve(c,token)
            current=c.execute('SELECT revision,status FROM github_connections WHERE room_id=?',(room_id,)).fetchone()
            if not current or current['revision']!=conn['revision'] or current['status']!='active': return False
            c.execute('''INSERT INTO github_evidence(room_id,revision,deliveries_json,pending_json,sync_at,discovery_json,releases_json,unattributed_json)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(room_id) DO UPDATE SET
                revision=excluded.revision,deliveries_json=excluded.deliveries_json,
                pending_json=excluded.pending_json,sync_at=excluded.sync_at,discovery_json=excluded.discovery_json,
                releases_json=excluded.releases_json,unattributed_json=excluded.unattributed_json''',
                (room_id,conn['revision'],deliveries_json,pending_json,sync_at,discovery_json,releases_json,unattributed_json))
            c.execute('UPDATE github_connections SET sync_at=? WHERE room_id=?',(sync_at,room_id))
        return True

    def snapshot(self,token):
        with self.db.connect() as c:
            principal=self.identity.resolve(c,token)
            conn=c.execute('SELECT * FROM github_connections WHERE room_id=?',(principal.room_id,)).fetchone()
            evidence=c.execute('SELECT * FROM github_evidence WHERE room_id=?',(principal.room_id,)).fetchone()
            deliveries=[];pending=[];events=[];discovery={};releases=[];unattributed=[]
            if conn:
                events=[dict(r) for r in c.execute('''SELECT delivery_id,event,status,received_at,completed_at,attempts
                    FROM github_inbox WHERE installation_id=? AND (repository_id=? OR repository_id IS NULL)
                    ORDER BY received_at DESC LIMIT 100''',(conn['installation_id'],conn['repository_id']))]
                if conn['status']=='active' and evidence and conn['sync_at'] and conn['sync_at']==evidence['sync_at']:
                    deliveries=json.loads(evidence['deliveries_json']);pending=json.loads(evidence['pending_json'])
                    discovery=json.loads(evidence['discovery_json'])
                    releases=json.loads(evidence['releases_json'])
                    unattributed=json.loads(evidence['unattributed_json'])
                    for row in deliveries+pending+releases+unattributed:
                        row['stale']=timestamp(evidence['sync_at'])<now()-timedelta(minutes=15)
            active_refs = {r['id']:(r['task_id'],r['ownership_epoch'],r['linked_at']) for r in c.execute('SELECT * FROM github_refs WHERE room_id=?',(principal.room_id,))}
            active_refs.update({'commit:'+str(r['id']):(r['task_id'],r['ownership_epoch'],r['linked_at']) for r in c.execute('SELECT * FROM github_commit_refs WHERE room_id=?',(principal.room_id,))})
            active_refs.update({'release:'+str(r['id']):(r['task_id'],r['ownership_epoch'],r['linked_at']) for r in c.execute('SELECT * FROM github_release_refs WHERE room_id=?',(principal.room_id,))})
            tasks = {r['id']:dict(r) for r in c.execute('SELECT * FROM tasks WHERE room_id=?',(principal.room_id,))}
            deliveries = [r for r in deliveries if r.get('ref_id') in active_refs
                and r['task_id'] in tasks and not tasks[r['task_id']]['cancelled_at']
                and r.get('ownership_epoch',0)==tasks[r['task_id']]['ownership_epoch']==active_refs[r['ref_id']][1]
                and r['sync_at'] >= active_refs[r['ref_id']][2]]
            unattributed = [r for r in unattributed if r.get('task_id') is None
                or (r['task_id'] in tasks and not tasks[r['task_id']]['cancelled_at']
                    and r.get('ownership_epoch',0)==tasks[r['task_id']]['ownership_epoch'])]
            snapshot={'connection':dict(conn) if conn else None,'deliveries':deliveries,'releases':releases,'github_events':events,
                      'github_pending':pending,'github_discovery':discovery,'github_unattributed':unattributed}
            if len(json.dumps(snapshot).encode())>MAX_SNAPSHOT_BYTES: raise GitHubError('GitHub snapshot exceeds output budget')
            return snapshot

    def receive_webhook(self,delivery,event,signature,body):
        self._enabled()
        if not isinstance(body,bytes) or len(body)>65536: raise ValidationError('Webhook body exceeds limit')
        if not isinstance(signature,str) or not re.fullmatch(r'sha256=[0-9a-f]{64}',signature):
            raise AccessDenied('GitHub webhook signature not accepted')
        expected='sha256='+hmac.new(self.app.webhook_secret.encode(),body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature): raise AccessDenied('GitHub webhook signature not accepted')
        if not isinstance(delivery,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',delivery):
            raise ValidationError('GitHub delivery identifier is invalid')
        if not isinstance(event,str) or not re.fullmatch(r'[a-z_]{1,40}',event): raise ValidationError('GitHub event is invalid')
        digest=hashlib.sha256(event.encode()+b'\x00'+body).hexdigest()
        with self.db.connect(write=True) as c:
            previous=c.execute('SELECT payload_hash FROM github_inbox WHERE delivery_id=?',(delivery,)).fetchone()
            if previous:
                if previous['payload_hash']!=digest: raise Conflict('GitHub delivery payload changed')
                return {'accepted':True,'duplicate':True}
            if event not in EVENTS: return {'accepted':True,'ignored':True,'duplicate':False}
            try:
                payload=json.loads(body)
                if not isinstance(payload,dict) or not isinstance(payload.get('installation'),dict): raise ValueError()
                if 'repository' in payload and not isinstance(payload['repository'],dict): raise ValueError()
                installation=positive_id(payload['installation']['id'])
                repository=(payload.get('repository') or {}).get('id')
                if repository is not None: positive_id(repository)
                if repository is None and event not in ('installation','installation_repositories'):
                    raise ValueError()
            except (ValueError,TypeError,KeyError,UnicodeError): raise ValidationError('GitHub webhook payload is invalid') from None
            c.execute('''INSERT INTO github_inbox(delivery_id,payload_hash,event,installation_id,repository_id,received_at)
                VALUES(?,?,?,?,?,?)''',(delivery,digest,event,installation,repository,now().isoformat()))
        return {'accepted':True,'duplicate':False}

    def process_pending(self,limit=20,should_stop=None):
        if not self.app.enabled: return 0
        if type(limit) is not int or not 1<=limit<=100: raise ValidationError('Invalid inbox processing limit')
        if should_stop is not None and not callable(should_stop): raise ValidationError('Expected a stop callback')
        if should_stop and should_stop(): return 0
        self._prune_tokens()
        if not self._process_lock.acquire(blocking=False): return 0
        processed=0
        try:
            with self.db.connect() as c:
                rows=[dict(r) for r in c.execute('''SELECT * FROM github_inbox WHERE status IN ('queued','retry')
                    AND next_attempt_at<=? ORDER BY received_at LIMIT ?''',(now().isoformat(),limit))]
            for row in rows:
                if should_stop and should_stop(): break
                with self.db.connect() as c:
                    rooms=[r['room_id'] for r in c.execute('''SELECT room_id FROM github_connections
                        WHERE installation_id=? AND status='active' AND (? IS NULL OR repository_id=?)''',
                        (row['installation_id'],row['repository_id'],row['repository_id']))]
                error=None;retryable=False;provider_delay=0;rate_limited=False;interrupted=False
                try:
                    for room_id in rooms:
                        if should_stop and should_stop():
                            interrupted=True
                            break
                        try: self._reconcile(room_id)
                        except AccessDenied: continue  # Revocation is a successfully reconciled terminal state.
                except GitHubError as failure:
                    error=str(failure);retryable=failure.retryable
                    provider_delay=failure.retry_after;rate_limited=failure.rate_limited
                except Exception:
                    error='GitHub synchronization failed';retryable=True
                if interrupted: break  # Keep the durable event queued until every mapped room has reconciled.
                attempts=row['attempts']+1
                delay=max(provider_delay,min(3600,60*2**min(attempts-1,6)) if rate_limited else min(3600,2**min(attempts,11)))
                with self.db.connect(write=True) as c:
                    c.execute('''UPDATE github_inbox SET status=?,attempts=?,next_attempt_at=?,last_error=?,completed_at=?
                        WHERE delivery_id=?''',('retry' if retryable else ('failed' if error else 'completed'),attempts,
                        (now()+timedelta(seconds=min(86400,delay))).isoformat() if retryable else '',
                        error,None if retryable else now().isoformat(),row['delivery_id']))
                processed+=1
        finally: self._process_lock.release()
        return processed

    def reconcile_all(self,should_stop=None):
        if not self.app.enabled: return 0
        if should_stop is not None and not callable(should_stop): raise ValidationError('Expected a stop callback')
        with self.db.connect() as c:
            rooms=[r['room_id'] for r in c.execute("SELECT room_id FROM github_connections WHERE status='active'")]
        completed=0
        for room in rooms:
            if should_stop and should_stop(): break
            try: completed+=bool(self._reconcile(room))
            except (AccessDenied,GitHubError): continue
        return completed
