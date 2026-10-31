"""Normalized delivery relationships and confirmation-required suggestions."""
from .errors import Conflict, NotFound, ValidationError
from .github_app import complete_sha, positive_id
from .repositories import require_manager, visible_task
from .github_sync import branch_name
from .tasks import _text, _utc_now

MAX_ITEMS = 200

def _object(kind, value):
    if kind not in ('branch', 'pr', 'commit', 'release'):
        raise ValidationError('Delivery kind must be branch, pr, commit or release')
    if kind == 'branch':
        return 'branch:' + branch_name(value)
    if kind == 'pr':
        positive_id(value); return 'pr:' + str(value)
    if kind == 'commit':
        complete_sha(value); return 'commit:' + value
    positive_id(value); return 'release:' + str(value)

class DeliveryStore:
    def __init__(self, service):
        self.service, self.identity, self.db = service, service.identity, service.identity.db
        with self.db.connect(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS delivery_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, task_id INTEGER NOT NULL,
                member_id TEXT NOT NULL, object_key TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
                evidence TEXT NOT NULL, ownership_epoch INTEGER NOT NULL, request_key TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected','stale')),
                created_at TEXT NOT NULL, decided_by TEXT, decided_at TEXT,
                UNIQUE(room_id,member_id,request_key),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id))''')

    def suggest(self, token, task_id, request_key, evidence='', branch='', pr_number=None, commit_sha='', release_id=None, session_key=None, ownership_epoch=None):
        request_key = _text(request_key, 'Request key', 200)
        evidence = _text(evidence, 'Evidence', 1000) if evidence else ''
        refs = [(('branch', branch), bool(branch)), (('pr', pr_number), pr_number is not None),
                (('commit', commit_sha), bool(commit_sha)), (('release', release_id), release_id is not None)]
        selected = [item for item, present in refs if present]
        if len(selected) != 1:
            raise ValidationError('Specify exactly one delivery object')
        kind, value = selected[0]; object_key = _object(kind, value)
        with self.db.connect(write=True) as db:
            principal = self.identity.resolve(db, token, required_kind='agent')
            task = visible_task(db, principal, task_id, session_key=session_key, ownership_epoch=ownership_epoch)
            existing = db.execute('SELECT * FROM delivery_suggestions WHERE room_id=? AND member_id=? AND request_key=?',
                                  (principal.room_id, principal.member_id, request_key)).fetchone()
            if existing:
                if existing['object_key'] != object_key or existing['evidence'] != evidence or existing['task_id'] != task_id or existing['ownership_epoch'] != task['ownership_epoch']:
                    raise Conflict('Suggestion key already has a different payload')
                return dict(existing)
            cursor = db.execute('''INSERT INTO delivery_suggestions
                (room_id,task_id,member_id,object_key,kind,value,evidence,ownership_epoch,request_key,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,'pending',?)''',
                (principal.room_id, task_id, principal.member_id, object_key, kind, str(value), evidence,
                 task['ownership_epoch'], request_key, _utc_now()))
            return dict(db.execute('SELECT * FROM delivery_suggestions WHERE id=?', (cursor.lastrowid,)).fetchone())

    def decide(self, token, suggestion_id, decision):
        if type(suggestion_id) is not int or not 0 < suggestion_id < 2**63:
            raise ValidationError('Suggestion id must be a positive integer')
        if decision not in ('confirmed', 'rejected'):
            raise ValidationError('Delivery decision must be confirmed or rejected')
        with self.db.connect(write=True) as db:
            principal = self.identity.resolve(db, token, required_kind='web')
            require_manager(self.identity, db, principal)
            row = db.execute('SELECT * FROM delivery_suggestions WHERE id=? AND room_id=?',
                             (suggestion_id, principal.room_id)).fetchone()
            if row is None: raise NotFound('Delivery suggestion not found')
            task = db.execute('SELECT * FROM tasks WHERE id=? AND room_id=?', (row['task_id'],principal.room_id)).fetchone()
            if row['ownership_epoch'] != task['ownership_epoch']:
                raise Conflict('Delivery suggestion belongs to an earlier task ownership epoch')
            if row['status'] != 'pending':
                if row['status'] == decision: return dict(row)
                raise Conflict('Delivery suggestion already has a decision')
            if decision == 'confirmed':
                payload = {'task_id':row['task_id']}
                field = {'branch':'branch','pr':'pr_number','commit':'commit_sha','release':'release_id'}[row['kind']]
                payload[field] = int(row['value']) if row['kind'] in ('pr','release') else row['value']
                self.service.github._enabled()
                self.service.github._associate_in_transaction(db,token,**payload)
            db.execute('UPDATE delivery_suggestions SET status=?,decided_by=?,decided_at=? WHERE id=?',
                       (decision,principal.member_id,_utc_now(),suggestion_id))
            return dict(db.execute('SELECT * FROM delivery_suggestions WHERE id=?',(suggestion_id,)).fetchone())

    def read(self, token, task_id=None, kind='', value=''):
        if task_id is not None and (type(task_id) is not int or not 0 < task_id < 2**63):
            raise ValidationError('Task id must be a positive integer')
        if not isinstance(kind,str) or kind not in ('','branch','pr','commit','release'):
            raise ValidationError('Unsupported delivery kind')
        if not isinstance(value,str) or len(value)>250 or value and not kind:
            raise ValidationError('Delivery value requires a kind and at most 250 characters')
        object_key = None
        if value:
            lookup = int(value) if kind in ('pr','release') and value.isascii() and value.isdigit() else value
            object_key = _object(kind,lookup)
        github = self.service.github.snapshot(token)
        local = self.service.repositories.snapshot(token)
        grouped = {}
        def add(k,v,association):
            key=k+':'+str(v)
            item=grouped.setdefault(key,{'object_key':key,'kind':k,'value':v,'repository':repository,
                'task_ids':[],'associations':[]})
            if association['task_id'] is not None:item['task_ids'].append(association['task_id'])
            item['associations'].append(association)
        with self.db.connect() as db:
            db.execute('BEGIN')
            principal=self.identity.resolve(db,token)
            binding=db.execute('SELECT repository FROM repo_bindings WHERE room_id=?',(principal.room_id,)).fetchone()
            repository=binding['repository'] if binding else None
            tasks={r['id']:dict(r) for r in db.execute('SELECT * FROM tasks WHERE room_id=?',(principal.room_id,))}
            for table in ('github_refs','github_commit_refs','github_release_refs'):
                for r in db.execute('SELECT * FROM '+table+' WHERE room_id=?',(principal.room_id,)):
                    row=dict(r)
                    if table=='github_refs':
                        k,v,ref_id=('pr',row['pr_number'],row['id']) if row['pr_number'] else ('branch',row['branch'],row['id'])
                    elif table=='github_commit_refs':k,v,ref_id='commit',row['commit_sha'],'commit:'+str(row['id'])
                    else:k,v,ref_id='release',row['release_id'],'release:'+str(row['id'])
                    matches=[d for d in github['deliveries'] if d.get('ref_id')==ref_id and d.get('ownership_epoch',0)==row['ownership_epoch']
                             and d.get('sync_at','')>=row['linked_at']]
                    matched=matches[0] if matches else None
                    revoked=not github.get('connection') or github['connection']['status']!='active'
                    relation={'task_id':row['task_id'],'relationship_source':'explicit','status':'confirmed',
                        'state':matched['state'] if matched else 'unavailable' if revoked else 'pending_sync',
                        'linked_by':row['linked_by'],'linked_at':row['linked_at'],'ownership_epoch':row['ownership_epoch'],
                        'sync_at':matched.get('sync_at') if matched else None,'source':'github_verified' if matched else 'member_link',
                        'ref_id':ref_id,'stale':bool(matched and matched.get('stale')),
                        'unavailable':revoked or bool(matched and matched['state']=='unavailable')}
                    add(k,v,relation)
                    for d in matches:
                        if k=='branch' and d.get('pr_number'):
                            add('pr',d['pr_number'],dict(relation,relationship_source='observed',evidence='GitHub PR head matches linked branch',url=d.get('url','')))
            for w in local['workspaces']:
                for k,v in (('branch',w['branch']),('commit',w['head'])):
                    if v:
                        add(k,v,{'task_id':w['task_id'],'relationship_source':'observed','status':'observed','source':'local_git',
                            'state':'observed','linked_by':w['member_id'],'linked_at':w['captured_at'],'sync_at':w['received_at'],
                            'ownership_epoch':w['ownership_epoch'],'stale':w['stale'],'unavailable':False,'observation_id':w['id'],
                            'evidence':'Explicit local Git checkpoint'})
            suggestions=[dict(r) for r in db.execute('SELECT * FROM delivery_suggestions WHERE room_id=? ORDER BY id DESC LIMIT 1001',(principal.room_id,))]
            for r in suggestions[:1000]:
                if r['status']=='confirmed':continue
                task=tasks.get(r['task_id'])
                historical=not task or task['ownership_epoch']!=r['ownership_epoch'] or bool(task['cancelled_at'])
                add(r['kind'],int(r['value']) if r['kind'] in ('pr','release') else r['value'],
                    {'task_id':r['task_id'],'relationship_source':'suggested','status':r['status'],
                     'state':'historical' if historical else 'rejected' if r['status']=='rejected' else 'pending_confirmation',
                     'suggestion_id':r['id'],'linked_by':r['member_id'],'linked_at':r['created_at'],'evidence':r['evidence'],
                     'ownership_epoch':r['ownership_epoch'],'source':'agent_suggestion','stale':historical,'unavailable':False,
                     'decided_by':r['decided_by'],'decided_at':r['decided_at']})
        items=[]
        for item in grouped.values():
            item['task_ids']=sorted(set(item['task_ids']))
            if task_id is not None and task_id not in item['task_ids']:continue
            if kind and kind!=item['kind']:continue
            if object_key and object_key!=item['object_key']:continue
            items.append(item)
        items.sort(key=lambda i:(max((a['linked_at'] for a in i['associations']),default=''),i['object_key']),reverse=True)
        return {'items':items[:MAX_ITEMS],'truncated':len(items)>MAX_ITEMS or len(suggestions)>1000 or local['workspaces_truncated'],
            'limit':MAX_ITEMS,'filters':{'task_id':task_id,'kind':kind or None,'value':value or None},'source':'delivery_registry'}
