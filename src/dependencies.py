"""Explicit task dependencies: transactional owner routing and read-before-confirm."""
import hashlib
import json
from uuid import uuid4

from .errors import AccessDenied, Conflict, NotFound, ValidationError
from .task_lifecycle import execution_task, manager, task_row
from .tasks import _text, _utc_now


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS task_dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
        source_task_id INTEGER NOT NULL, target_task_id INTEGER NOT NULL,
        need TEXT NOT NULL, context TEXT NOT NULL, creator_member_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', revision INTEGER NOT NULL DEFAULT 0,
        route_version INTEGER NOT NULL DEFAULT 0, routing_state TEXT NOT NULL DEFAULT 'waiting_source',
        current_request_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        closed_at TEXT, closed_reason TEXT,
        FOREIGN KEY(source_task_id,room_id) REFERENCES tasks(id,room_id),
        FOREIGN KEY(target_task_id,room_id) REFERENCES tasks(id,room_id))''')
    db.execute('CREATE INDEX IF NOT EXISTS dependency_room_status ON task_dependencies(room_id,status,id)')
    db.execute('CREATE INDEX IF NOT EXISTS dependency_target ON task_dependencies(target_task_id,status)')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS dependency_active_edge ON task_dependencies(source_task_id,target_task_id) WHERE status='active'")
    db.execute('''CREATE TABLE IF NOT EXISTS dependency_routes (
        request_id INTEGER PRIMARY KEY, dependency_id INTEGER NOT NULL, route_version INTEGER NOT NULL,
        source_member_id TEXT NOT NULL,target_member_id TEXT NOT NULL,created_at TEXT NOT NULL,
        UNIQUE(dependency_id,route_version),
        FOREIGN KEY(dependency_id) REFERENCES task_dependencies(id),
        FOREIGN KEY(request_id) REFERENCES message_requests(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS dependency_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, dependency_id INTEGER NOT NULL,
        actor_member_id TEXT,actor_kind TEXT NOT NULL,action TEXT NOT NULL,request_key TEXT,
        payload_hash TEXT,revision INTEGER NOT NULL,summary TEXT NOT NULL,created_at TEXT NOT NULL,
        result_json TEXT NOT NULL, UNIQUE(room_id,actor_member_id,request_key),
        FOREIGN KEY(dependency_id) REFERENCES task_dependencies(id))''')
    db.execute('CREATE INDEX IF NOT EXISTS dependency_event_history ON dependency_events(dependency_id,id)')
    db.execute('''CREATE TABLE IF NOT EXISTS dependency_reads (
        dependency_id INTEGER NOT NULL,member_id TEXT NOT NULL,actor_kind TEXT NOT NULL,
        session_key TEXT NOT NULL,ownership_epoch INTEGER NOT NULL,revision INTEGER NOT NULL,
        reply_id INTEGER NOT NULL,read_at TEXT NOT NULL,
        PRIMARY KEY(dependency_id,member_id,actor_kind,session_key,ownership_epoch),
        FOREIGN KEY(dependency_id) REFERENCES task_dependencies(id),
        FOREIGN KEY(reply_id) REFERENCES message_replies(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS dependency_reply_actors (
        reply_id INTEGER PRIMARY KEY,actor_kind TEXT NOT NULL,session_key TEXT,ownership_epoch INTEGER,
        FOREIGN KEY(reply_id) REFERENCES message_replies(id))''')


def linked_request(db, request_id):
    return db.execute('SELECT dependency_id FROM dependency_routes WHERE request_id=?',(request_id,)).fetchone()


def _row(db, principal, dependency_id):
    if type(dependency_id) is not int or not 0<dependency_id<2**63:
        raise ValidationError('Dependency id must be a positive integer')
    row=db.execute('SELECT * FROM task_dependencies WHERE id=? AND room_id=?',(dependency_id,principal.room_id)).fetchone()
    if row is None: raise NotFound('Dependency not found')
    return row


def _latest(db, dep):
    row=db.execute('''SELECT r.*,a.actor_kind,a.session_key,a.ownership_epoch FROM message_replies r
        JOIN dependency_reply_actors a ON a.reply_id=r.id WHERE r.request_id=? ORDER BY r.id DESC LIMIT 1''',
        (dep['current_request_id'],)).fetchone()
    return dict(row) if row else None


def project(db, dep, history=False):
    result=dict(dep)
    for prefix in ('source','target'):
        task=db.execute('SELECT id,title,scope,owner_member_id,creator_member_id,cancelled_at FROM tasks WHERE id=?',(dep[prefix+'_task_id'],)).fetchone()
        result[prefix]=dict(task)
    result['latest_reply']=_latest(db,dep)
    result['blocked']=dep['status']=='active'
    if history:
        result['routes']=[dict(r) for r in db.execute('SELECT * FROM dependency_routes WHERE dependency_id=? ORDER BY route_version',(dep['id'],))]
        result['history']=[{k:r[k] for k in ('id','actor_member_id','actor_kind','action','revision','summary','created_at')}
            for r in db.execute('SELECT * FROM dependency_events WHERE dependency_id=? ORDER BY id DESC LIMIT 100',(dep['id'],))]
    return result


def _route(db,dep,actor=None,kind='system',reason='Task responsibility changed'):
    source=db.execute('SELECT * FROM tasks WHERE id=?',(dep['source_task_id'],)).fetchone()
    target=db.execute('SELECT * FROM tasks WHERE id=?',(dep['target_task_id'],)).fetchone()
    now=_utc_now(); request=None
    if source['cancelled_at']:
        db.execute("UPDATE task_dependencies SET status='cancelled',closed_at=?,closed_reason=?,revision=revision+1,updated_at=? WHERE id=?",(now,reason,now,dep['id']))
        action='source_cancelled'
    else:
        state='target_cancelled' if target['cancelled_at'] else 'waiting_source' if not source['owner_member_id'] else 'unassigned' if not target['owner_member_id'] else 'routed'
        version=dep['route_version']+1
        if state=='routed':
            body='Dependency #'+str(dep['id'])+': '+dep['need']+'\n'+dep['context']
            cursor=db.execute('''INSERT INTO message_requests (room_id,sender_member_id,receiver_member_id,
                initial_receiver_member_id,task_id,context_version,body,request_key,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',(dep['room_id'],source['owner_member_id'],target['owner_member_id'],
                target['owner_member_id'],source['id'],version,body,'dependency:'+str(uuid4()),now))
            request=cursor.lastrowid
            db.execute('INSERT INTO message_deliveries(request_id,room_id,receiver_member_id) VALUES(?,?,?)',(request,dep['room_id'],target['owner_member_id']))
            db.execute('INSERT INTO dependency_routes VALUES(?,?,?,?,?,?)',(request,dep['id'],version,source['owner_member_id'],target['owner_member_id'],now))
        db.execute('''UPDATE task_dependencies SET current_request_id=?,routing_state=?,route_version=?,revision=revision+1,updated_at=? WHERE id=?''',(request,state,version,now,dep['id']))
        action='rerouted'
    revision=dep['revision']+1
    db.execute('''INSERT INTO dependency_events(room_id,dependency_id,actor_member_id,actor_kind,action,revision,summary,created_at,result_json)
        VALUES(?,?,?,?,?,?,?,?,?)''',(dep['room_id'],dep['id'],actor,kind,action,revision,reason,now,'{}'))


def ownership_changed(db,task_id,old_owner,new_owner,actor=None,kind='system',reason='Task responsibility changed'):
    # Called inside the task transaction. No nested connection or identity rewrite.
    for dep in db.execute("SELECT * FROM task_dependencies WHERE status='active' AND (source_task_id=? OR target_task_id=?)",(task_id,task_id)).fetchall():
        _route(db,dep,actor,kind,reason)


def schemas(fields):
    auth={'session_key':None,'ownership_epoch':None}
    return {
        'lookup_owner':fields('',{'task_id':None,'scope':None}),
        'create_dependency':fields('source_task_id target_task_id need expected_revision request_key',{'context':'',**auth}),
        'read_dependency':fields('dependency_id',auth),
        'reply_dependency':fields('dependency_id expected_revision request_key body',{'evidence':'',**auth}),
        'resolve_dependency':fields('dependency_id expected_revision reply_id request_key summary',auth),
        'cancel_dependency':fields('dependency_id expected_revision request_key summary',auth),
    }


class DependencyStore:
    def __init__(self,identity):
        self.identity,self.db=identity,identity.db

    def _authority(self,db,p,task,session_key,ownership_epoch,*,confirm=False):
        if p.kind=='agent':
            execution_task(db,p,task['id'],session_key,ownership_epoch)
        elif confirm:
            if task['owner_member_id']!=p.member_id: raise AccessDenied('Current task owner required for this decision')
        elif not (task['owner_member_id']==p.member_id or manager(self.identity,db,p) or
                  (not task['owner_member_id'] and task['creator_member_id']==p.member_id)):
            raise AccessDenied('Task owner or project manager required')

    @staticmethod
    def _digest(action,payload):
        return hashlib.sha256(json.dumps([action,payload],sort_keys=True).encode()).hexdigest()

    def _retry(self,db,p,key,digest):
        row=db.execute('SELECT * FROM dependency_events WHERE room_id=? AND actor_member_id=? AND request_key=?',(p.room_id,p.member_id,key)).fetchone()
        if row:
            if row['payload_hash']!=digest or row['actor_kind']!=p.kind: raise Conflict('Request key already has a different payload')
            return json.loads(row['result_json'])

    def _record(self,db,p,dep,action,key,digest,summary):
        result=project(db,dep)
        db.execute('''INSERT INTO dependency_events(room_id,dependency_id,actor_member_id,actor_kind,action,
            request_key,payload_hash,revision,summary,created_at,result_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (p.room_id,dep['id'],p.member_id,p.kind,action,key,digest,dep['revision'],summary,_utc_now(),json.dumps(result)))
        return result

    @staticmethod
    def _revision(dep,expected):
        if type(expected) is not int or expected<0: raise ValidationError('Expected revision must be a nonnegative integer')
        if dep['revision']!=expected: raise Conflict('Dependency revision changed; refresh and read the latest reply')
        if dep['status']!='active': raise Conflict('Dependency is no longer active')

    def lookup_owner(self,token,task_id=None,scope=None):
        if (task_id is None)==(scope is None): raise ValidationError('Provide exactly one of task_id or scope')
        if scope is not None:
            scope=_text(scope,'Scope',500).replace('\\','/').strip('/')
            if not scope or any(part in ('','..','.') for part in scope.split('/')): raise ValidationError('Scope must contain explicit path segments')
        with self.db.connect() as db:
            p=self.identity.resolve(db,token)
            rows=[task_row(db,p,task_id)] if task_id is not None else db.execute('SELECT * FROM tasks WHERE room_id=? AND cancelled_at IS NULL ORDER BY id',(p.room_id,)).fetchall()
            found=[]
            for task in rows:
                declared=task['scope'].replace('\\','/').strip('/')
                if task['cancelled_at']: continue
                if scope is not None and not (scope==declared or scope.startswith(declared+'/') or declared.startswith(scope+'/')): continue
                found.append({k:task[k] for k in ('id','title','scope','owner_member_id','revision','execution_session_key','ownership_epoch')})
                found[-1]['evidence']='Exact task id' if task_id is not None else 'Equal declared scope' if declared==scope else 'Slash-segment prefix overlap'
            return {'status':'not_found' if not found else 'ambiguous' if len(found)>1 else 'owned' if found[0]['owner_member_id'] else 'unassigned','candidates':found}

    def create_dependency(self,token,source_task_id,target_task_id,need,expected_revision,request_key,context='',session_key=None,ownership_epoch=None):
        need=_text(need,'Need',500); request_key=_text(request_key,'Request key',200)
        if not isinstance(context,str) or len(context.strip())>3000: raise ValidationError('Context must contain at most 3000 characters')
        context=context.strip()
        payload=[source_task_id,target_task_id,need,expected_revision,context,session_key,ownership_epoch]
        digest=self._digest('create',payload)
        with self.db.connect(write=True) as db:
            p=self.identity.resolve(db,token); source=task_row(db,p,source_task_id); target=task_row(db,p,target_task_id)
            self._authority(db,p,source,session_key,ownership_epoch)
            retry=self._retry(db,p,request_key,digest)
            if retry: return retry
            if type(expected_revision) is not int or expected_revision!=source['revision']: raise Conflict('Source task revision changed; refresh before creating dependency')
            if source['cancelled_at'] or target['cancelled_at']: raise Conflict('Cancelled tasks cannot create a new dependency')
            if source_task_id==target_task_id: raise Conflict('A task cannot depend on itself')
            if db.execute("SELECT 1 FROM task_dependencies WHERE source_task_id=? AND target_task_id=? AND status='active'",(source_task_id,target_task_id)).fetchone(): raise Conflict('An active dependency already connects these tasks')
            graph={}
            for edge in db.execute("SELECT source_task_id,target_task_id FROM task_dependencies WHERE room_id=? AND status='active'",(p.room_id,)):
                graph.setdefault(edge[0],[]).append(edge[1])
            stack=[(target_task_id,[source_task_id,target_task_id])]; seen=set()
            while stack:
                current,path=stack.pop()
                if current==source_task_id: raise Conflict('Dependency cycle: '+' -> '.join('task #'+str(i) for i in path))
                if current not in seen:
                    seen.add(current); stack.extend((n,path+[n]) for n in graph.get(current,[]))
            now=_utc_now()
            identifier=db.execute('''INSERT INTO task_dependencies(room_id,source_task_id,target_task_id,need,context,
                creator_member_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)''',(p.room_id,source_task_id,target_task_id,need,context,p.member_id,now,now)).lastrowid
            _route(db,_row(db,p,identifier),p.member_id,p.kind,'Dependency created')
            return self._record(db,p,_row(db,p,identifier),'created',request_key,digest,need)

    def snapshot(self,token):
        with self.db.connect() as db:
            p=self.identity.resolve(db,token)
            return [project(db,r) for r in db.execute('SELECT * FROM task_dependencies WHERE room_id=? ORDER BY id',(p.room_id,))]

    def read_dependency(self,token,dependency_id,session_key=None,ownership_epoch=None):
        with self.db.connect(write=True) as db:
            p=self.identity.resolve(db,token); dep=_row(db,p,dependency_id)
            source=task_row(db,p,dep['source_task_id']); latest=_latest(db,dep)
            recorded=False
            if source['owner_member_id']==p.member_id and latest and dep['status']=='active' and dep['routing_state']=='routed':
                self._authority(db,p,source,session_key,ownership_epoch,confirm=True)
                db.execute('''INSERT INTO dependency_reads VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(dependency_id,member_id,actor_kind,session_key,ownership_epoch)
                    DO UPDATE SET revision=excluded.revision,reply_id=excluded.reply_id,read_at=excluded.read_at''',
                    (dep['id'],p.member_id,p.kind,(session_key or '') if p.kind=='agent' else '',source['ownership_epoch'],dep['revision'],latest['id'],_utc_now()))
                recorded=True
            return {**project(db,dep,True),'read_recorded':recorded}

    def reply_dependency(self,token,dependency_id,expected_revision,request_key,body,evidence='',session_key=None,ownership_epoch=None):
        body=_text(body,'Body',4000); request_key=_text(request_key,'Request key',200)
        if not isinstance(evidence,str) or len(evidence.strip())>1000: raise ValidationError('Evidence must contain at most 1000 characters')
        evidence=evidence.strip(); digest=self._digest('reply',[dependency_id,expected_revision,body,evidence,session_key,ownership_epoch])
        with self.db.connect(write=True) as db:
            p=self.identity.resolve(db,token); dep=_row(db,p,dependency_id); target=task_row(db,p,dep['target_task_id'])
            # Even a project manager cannot reply on behalf of the current assignee.
            self._authority(db,p,target,session_key,ownership_epoch,confirm=True)
            retry=self._retry(db,p,request_key,digest)
            if retry: return retry
            self._revision(dep,expected_revision)
            if dep['routing_state']!='routed': raise Conflict('Both tasks need active owners before replying')
            reply_id=db.execute('''INSERT INTO message_replies(request_id,room_id,author_member_id,request_key,context_version,body,evidence,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',(dep['current_request_id'],p.room_id,p.member_id,'dependency:'+str(uuid4()),dep['route_version'],body,evidence,_utc_now())).lastrowid
            db.execute('INSERT INTO dependency_reply_actors VALUES(?,?,?,?)',(reply_id,p.kind,session_key if p.kind=='agent' else None,target['ownership_epoch']))
            db.execute('UPDATE task_dependencies SET revision=revision+1,updated_at=? WHERE id=?',(_utc_now(),dependency_id))
            return self._record(db,p,_row(db,p,dependency_id),'replied',request_key,digest,body)

    def resolve_dependency(self,token,dependency_id,expected_revision,reply_id,request_key,summary,session_key=None,ownership_epoch=None):
        if type(reply_id) is not int or not 0<reply_id<2**63:
            raise ValidationError('Reply id must be positive')
        return self._close(token,dependency_id,expected_revision,request_key,summary,session_key,ownership_epoch,reply_id)

    def cancel_dependency(self,token,dependency_id,expected_revision,request_key,summary,session_key=None,ownership_epoch=None):
        return self._close(token,dependency_id,expected_revision,request_key,summary,session_key,ownership_epoch,None)

    def _close(self,token,dependency_id,expected_revision,request_key,summary,session_key,ownership_epoch,reply_id):
        summary=_text(summary,'Summary',4000); request_key=_text(request_key,'Request key',200)
        action='cancelled' if reply_id is None else 'satisfied'
        if reply_id is not None and (type(reply_id) is not int or not 0<reply_id<2**63): raise ValidationError('Reply id must be positive')
        digest=self._digest(action,[dependency_id,expected_revision,summary,reply_id,session_key,ownership_epoch])
        with self.db.connect(write=True) as db:
            p=self.identity.resolve(db,token); dep=_row(db,p,dependency_id); source=task_row(db,p,dep['source_task_id'])
            self._authority(db,p,source,session_key,ownership_epoch,confirm=reply_id is not None)
            retry=self._retry(db,p,request_key,digest)
            if retry: return retry
            self._revision(dep,expected_revision)
            if reply_id is not None:
                latest=_latest(db,dep)
                if dep['routing_state']!='routed' or not latest or latest['id']!=reply_id: raise Conflict('Latest reply in the current route is required')
                read=db.execute('''SELECT 1 FROM dependency_reads WHERE dependency_id=? AND member_id=? AND actor_kind=?
                    AND session_key=? AND ownership_epoch=? AND revision=? AND reply_id=?''',
                    (dependency_id,p.member_id,p.kind,(session_key or '') if p.kind=='agent' else '',source['ownership_epoch'],expected_revision,reply_id)).fetchone()
                if not read: raise Conflict('Use read_dependency to read the latest reply before confirming satisfaction')
                db.execute('UPDATE message_requests SET resolved_at=? WHERE id=?',(_utc_now(),dep['current_request_id']))
            db.execute('UPDATE task_dependencies SET status=?,closed_reason=?,closed_at=?,updated_at=?,revision=revision+1 WHERE id=?',(action,summary,_utc_now(),_utc_now(),dependency_id))
            return self._record(db,p,_row(db,p,dependency_id),action,request_key,digest,summary)
