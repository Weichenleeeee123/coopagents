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
from .repositories import now, require_manager, timestamp, visible_task


EVENTS = {'push','pull_request','check_run','check_suite','status','installation','installation_repositories'}
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
MAX_REFS = 100
MAX_EVIDENCE_BYTES = 450000
MAX_SNAPSHOT_BYTES = 500000


def state_hash(state):
    if not isinstance(state,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',state):
        raise AccessDenied('GitHub authorization state not accepted')
    return hashlib.sha256(state.encode()).hexdigest()


def branch_name(branch):
    if (not isinstance(branch,str) or len(branch)>250 or any(ord(x)<33 for x in branch)
            or any(x in branch for x in ('..','@{','\\','~','^',':','?','*','['))
            or branch.startswith(('/','-')) or branch.endswith(('/','.','.lock'))
            or any(not x or x.startswith('.') for x in branch.split('/'))):
        raise ValidationError('Expected a safe Git branch name')
    return branch


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
            for table in ('github_refs', 'github_commit_refs'):
                if 'ownership_epoch' not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN ownership_epoch INTEGER NOT NULL DEFAULT 0')
            c.execute('''CREATE TABLE IF NOT EXISTS github_evidence (
                room_id TEXT PRIMARY KEY REFERENCES rooms(id), revision INTEGER NOT NULL,
                deliveries_json TEXT NOT NULL, pending_json TEXT NOT NULL, sync_at TEXT NOT NULL)''')
            if 'discovery_json' not in {r['name'] for r in c.execute('PRAGMA table_info(github_evidence)')}:
                c.execute("ALTER TABLE github_evidence ADD COLUMN discovery_json TEXT NOT NULL DEFAULT '{}' ")
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

    def associate(self,token,task_id,branch='',pr_number=None,commit_sha='',session_key=None,ownership_epoch=None):
        self._enabled()
        if branch: branch_name(branch)
        elif not isinstance(branch,str): raise ValidationError('Expected branch text')
        if pr_number is not None: positive_id(pr_number)
        if not isinstance(commit_sha,str): raise ValidationError('Expected a complete commit SHA')
        if commit_sha:
            complete_sha(commit_sha)
            if branch or pr_number is not None: raise ValidationError('Associate a commit separately from a branch or PR')
        if not branch and pr_number is None and not commit_sha: raise ValidationError('Specify a branch, PR or commit')
        with self.db.connect(write=True) as c:
            principal=self.identity.resolve(c,token)
            if principal.kind=='web': require_manager(self.identity,c,principal)
            task = visible_task(c,principal,task_id,manager=principal.kind=='web',session_key=session_key,ownership_epoch=ownership_epoch)
            conn=c.execute("SELECT * FROM github_connections WHERE room_id=? AND status='active'",(principal.room_id,)).fetchone()
            if not conn: raise Conflict('GitHub repository is not authorized')
            existing=(c.execute('SELECT * FROM github_commit_refs WHERE room_id=? AND task_id=? AND commit_sha=?',
                (principal.room_id,task_id,commit_sha)).fetchone() if commit_sha else c.execute(
                'SELECT * FROM github_refs WHERE room_id=? AND task_id=? AND branch=? AND pr_number=?',
                (principal.room_id,task_id,branch,pr_number or 0)).fetchone())
            if existing: return dict(existing)
            count=c.execute('''SELECT (SELECT COUNT(*) FROM github_refs WHERE room_id=?) +
                (SELECT COUNT(*) FROM github_commit_refs WHERE room_id=?)''',(principal.room_id,principal.room_id)).fetchone()[0]
            if count>=MAX_REFS: raise ValidationError('Project GitHub reference limit is 100')
            if commit_sha:
                c.execute('''INSERT OR IGNORE INTO github_commit_refs(room_id,task_id,commit_sha,linked_by,linked_at,ownership_epoch)
                    VALUES(?,?,?,?,?,?)''',(principal.room_id,task_id,commit_sha,principal.member_id,now().isoformat(),task['ownership_epoch']))
                c.execute('UPDATE github_connections SET revision=revision+1 WHERE room_id=?',(principal.room_id,))
                return dict(c.execute('SELECT * FROM github_commit_refs WHERE room_id=? AND task_id=? AND commit_sha=?',
                    (principal.room_id,task_id,commit_sha)).fetchone())
            c.execute('''INSERT OR IGNORE INTO github_refs(room_id,task_id,branch,pr_number,linked_by,linked_at,ownership_epoch)
                VALUES(?,?,?,?,?,?,?)''',(principal.room_id,task_id,branch,pr_number or 0,principal.member_id,now().isoformat(),task['ownership_epoch']))
            c.execute('UPDATE github_connections SET revision=revision+1 WHERE room_id=?',(principal.room_id,))
            return dict(c.execute('SELECT * FROM github_refs WHERE room_id=? AND task_id=? AND branch=? AND pr_number=?',
                (principal.room_id,task_id,branch,pr_number or 0)).fetchone())

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
            return {'task_id':ref['task_id'],'ref_id':ref['id'],'branch':ref['branch'],
                'pr_number':ref['pr_number'] or None,'commit_sha':ref.get('commit_sha',''),
                'head_sha':'','repository_id':conn['repository_id'],'state':'unavailable','checks':[],'statuses':[],
                'source':'github_verified','sync_at':sync_at,'stale':False,'url':''}
        for ref in refs:
            if ref.get('commit_sha'):
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
        return deliveries,[p for p in normalized if p['number'] not in associated]

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
            if len(refs)>MAX_REFS: raise GitHubError('Project GitHub references exceed limit')
            previous=c.execute('SELECT * FROM github_evidence WHERE room_id=?',(room_id,)).fetchone()
            # Previously matched PRs remain candidates after they close; each is fetched again.
            candidates=set()
            if previous and conn['sync_at'] and conn['sync_at']==previous['sync_at']:
                candidates={r['pr_number'] for r in json.loads(previous['deliveries_json']) if r.get('pr_number')}
            explicit={r['pr_number'] for r in refs if r['pr_number']}
            prior_candidates=sorted(candidates-explicit)[:max(0,MAX_REFS-len(refs))]
        try:
            state=self.app.repository_state(conn['installation_id'],conn['repository_id'],conn['full_name'],
                branches=sorted({r['branch'] for r in refs if r['branch']}),pr_numbers=sorted(explicit.union(prior_candidates)),
                commit_shas=sorted({r['commit_sha'] for r in refs if r.get('commit_sha')}))
            sync_at=now().isoformat();deliveries,pending=self._evidence(state,refs,conn,sync_at)
            discovery=state.get('discovery',{})
            if (not isinstance(discovery,dict) or set(discovery)-{'limit','truncated','state'}
                    or ('limit' in discovery and (type(discovery['limit']) is not int or not 1<=discovery['limit']<=50))):
                raise GitHubError('GitHub discovery bounds are invalid')
            deliveries_json=json.dumps(deliveries);pending_json=json.dumps(pending);discovery_json=json.dumps(discovery)
            if len((deliveries_json+pending_json+discovery_json).encode())>MAX_EVIDENCE_BYTES:
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
            c.execute('''INSERT INTO github_evidence(room_id,revision,deliveries_json,pending_json,sync_at,discovery_json)
                VALUES(?,?,?,?,?,?) ON CONFLICT(room_id) DO UPDATE SET
                revision=excluded.revision,deliveries_json=excluded.deliveries_json,
                pending_json=excluded.pending_json,sync_at=excluded.sync_at,discovery_json=excluded.discovery_json''',
                (room_id,conn['revision'],deliveries_json,pending_json,sync_at,discovery_json))
            c.execute('UPDATE github_connections SET sync_at=? WHERE room_id=?',(sync_at,room_id))
        return True

    def snapshot(self,token):
        with self.db.connect() as c:
            principal=self.identity.resolve(c,token)
            conn=c.execute('SELECT * FROM github_connections WHERE room_id=?',(principal.room_id,)).fetchone()
            evidence=c.execute('SELECT * FROM github_evidence WHERE room_id=?',(principal.room_id,)).fetchone()
            deliveries=[];pending=[];events=[];discovery={}
            if conn:
                events=[dict(r) for r in c.execute('''SELECT delivery_id,event,status,received_at,completed_at,attempts
                    FROM github_inbox WHERE installation_id=? AND (repository_id=? OR repository_id IS NULL)
                    ORDER BY received_at DESC LIMIT 100''',(conn['installation_id'],conn['repository_id']))]
                if conn['status']=='active' and evidence and conn['sync_at'] and conn['sync_at']==evidence['sync_at']:
                    deliveries=json.loads(evidence['deliveries_json']);pending=json.loads(evidence['pending_json'])
                    discovery=json.loads(evidence['discovery_json'])
                    for row in deliveries+pending:
                        row['stale']=timestamp(evidence['sync_at'])<now()-timedelta(minutes=15)
            active_refs = {r['id']:(r['task_id'],r['ownership_epoch'],r['linked_at']) for r in c.execute('SELECT * FROM github_refs WHERE room_id=?',(principal.room_id,))}
            active_refs.update({'commit:'+str(r['id']):(r['task_id'],r['ownership_epoch'],r['linked_at']) for r in c.execute('SELECT * FROM github_commit_refs WHERE room_id=?',(principal.room_id,))})
            tasks = {r['id']:dict(r) for r in c.execute('SELECT * FROM tasks WHERE room_id=?',(principal.room_id,))}
            deliveries = [r for r in deliveries if r.get('ref_id') in active_refs
                and r['task_id'] in tasks and not tasks[r['task_id']]['cancelled_at']
                and r.get('ownership_epoch',0)==tasks[r['task_id']]['ownership_epoch']==active_refs[r['ref_id']][1]
                and r['sync_at'] >= active_refs[r['ref_id']][2]]
            snapshot={'connection':dict(conn) if conn else None,'deliveries':deliveries,'github_events':events,
                      'github_pending':pending,'github_discovery':discovery}
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
