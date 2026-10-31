"""Bounded, source-labelled projections of shared collaboration context."""
from datetime import datetime, timezone
import json
import hashlib

from .errors import ValidationError


MAX_ITEMS = 100
QUERY_SCHEMA = {
    'task_id':(int,False,None),'member_id':(str,False,None),'limit':(int,False,50),
    'scope':(str,False,''),'branch':(str,False,''),'delivery_kind':(str,False,''),'delivery_value':(str,False,''),
    'reference':(str,False,''),'query':(str,False,''),'source':(str,False,''),'offset':(int,False,0),'after':(str,False,'')}


def query_arguments(params):
    if any(k not in QUERY_SCHEMA or len(params.getlist(k))!=1 for k in params):
        raise ValidationError('Unsupported context query parameter')
    data=dict(params)
    try:
        for key in ('task_id','limit','offset'):
            if key in data:data[key]=int(data[key])
    except ValueError:
        raise ValidationError('Invalid context query parameter') from None
    return data

FRESH_SECONDS = {
    "session_registry": 15 * 60,
    "agent_report": 24 * 60 * 60,
    "local_git": 5 * 60,
    "github_verified": 15 * 60,
}


def _when(value):
    if not isinstance(value, str) or not value or len(value) > 50:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value):
    parsed = _when(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _freshness(observed_at, now, source):
    parsed = _when(observed_at)
    if parsed is None:
        return "unknown"
    age = (now - parsed).total_seconds()
    if age < -300:return "unknown"
    threshold = FRESH_SECONDS.get(source)
    if threshold is None:
        return "current"
    return "fresh" if age <= threshold else "stale"


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def _item(identifier, kind, source, scope, observed_at, data, now):
    observed = _iso(observed_at)
    if observed is None:
        return None
    return {
        "id": str(identifier) if len(str(identifier))<=120 else str(identifier)[:60]+":"+hashlib.sha256(str(identifier).encode()).hexdigest()[:40],
        "kind": kind,
        "source": source,
        "scope": scope,
        "observed_at": observed,
        "freshness": _freshness(observed, now, source),
        "privacy": "shared_structured",
        "data": data,
    }


def _matches(item, task_id=None, member_id=None):
    data = item["data"]
    if task_id is not None and data.get("task_id") != task_id:
        return False
    if member_id is not None and data.get("member_id") != member_id:
        return False
    return True


class ContextStore:
    """Project existing snapshot sections into a stable, bounded read model."""

    @staticmethod
    def project(snapshot, *, task_id=None, member_id=None, limit=50, now=None, scope='', branch='', delivery_kind='', delivery_value='', query='', source='', offset=0, after='', reference=''):
        if type(task_id) is not int and task_id is not None:
            raise ValidationError("Task id must be a positive integer")
        if type(task_id) is int and task_id <= 0:
            raise ValidationError("Task id must be a positive integer")
        if member_id is not None and (not isinstance(member_id, str) or not member_id.strip()):
            raise ValidationError("Member id must be a nonempty string")
        if type(limit) is not int or not 1 <= limit <= MAX_ITEMS:
            raise ValidationError("Context limit must be between 1 and 100")
        if not isinstance(snapshot, dict):
            raise ValidationError("Context source must be a snapshot object")
        for field,value in (('scope',scope),('branch',branch),('delivery_kind',delivery_kind),('delivery_value',delivery_value),('query',query),('source',source),('after',after),('reference',reference)):
            if not isinstance(value,str) or len(value)>500:
                raise ValidationError('Context filters require text of at most 500 characters')
        if member_id is not None and len(member_id)>120:raise ValidationError('Member id exceeds limit')
        if type(offset) is not int or not 0<=offset<=1000000:raise ValidationError('Invalid context offset')
        if after and (_when(after) is None or datetime.fromisoformat(after.replace('Z','+00:00')).tzinfo is None):
            raise ValidationError('after requires an ISO timestamp with timezone')
        if delivery_value and not delivery_kind:raise ValidationError('Delivery value requires a kind')
        if delivery_kind not in ('','branch','pr','commit','release'):raise ValidationError('Invalid delivery kind')
        now = now or datetime.now(timezone.utc)
        items = []

        for row in snapshot.get("tasks", []):
            if isinstance(row, dict) and type(row.get("id")) is int:
                items.append(_item(
                    "task:" + str(row["id"]), "task", "task", "project", row.get("epoch_started_at") or row.get("claimed_at") or row.get("created_at"),
                    {"task_id": row["id"], "title": _text(row.get("title"), 200),
                     "scope": _text(row.get("scope"), 250), "state": _text(row.get("state"), 40),
                     "member_id": row.get("owner_member_id"), "creator_member_id":row.get("creator_member_id"), "revision":row.get("revision"), "ownership_epoch":row.get("ownership_epoch")}, now))

        for row in snapshot.get("sessions", []):
            if isinstance(row, dict):
                items.append(_item(
                    "session:" + str(row.get("id", "")), "session", "session_registry", "member",
                    row.get("updated_at"),
                    {"session_id": row.get("id"), "member_id": _text(row.get("member_id"), 120),
                     "tool": _text(row.get("tool"), 60), "repository": _text(row.get("repository"), 500),
                     "branch": _text(row.get("branch"), 250), "task_id": row.get("task_id")}, now))

        for row in snapshot.get("progress", []):
            if isinstance(row, dict):
                items.append(_item(
                    "progress:" + str(row.get("task_id", "")), "progress", "agent_report", "task",
                    row.get("updated_at"),
                    {"task_id": row.get("task_id"), "member_id": _text(row.get("member_id"), 120),
                     "state": _text(row.get("state"), 40), "summary": _text(row.get("summary"), 1000),
                     "evidence": _text(row.get("evidence"), 1000)}, now))

        for row in snapshot.get("requests", []):
            if isinstance(row, dict):
                items.append(_item(
                    "request:" + str(row.get("id", "")), "request", "collaboration_request", "task",
                    row.get("created_at"),
                    {"request_id": row.get("id"), "task_id": row.get("task_id"),
                     "member_id": _text(row.get("sender_member_id"), 120),
                     "receiver_member_id": _text(row.get("receiver_member_id"), 120) or None,
                     "context_version": row.get("context_version"), "body": _text(row.get("body"), 4000),
                     "read_at": _iso(row.get("read_at")), "processed_at": _iso(row.get("processed_at")),
                     "resolved_at": _iso(row.get("resolved_at")),
                     "reply_count": len(row.get("replies", [])) if isinstance(row.get("replies"), list) else 0}, now))

        requests={r['id']:r for r in snapshot.get('requests',[]) if isinstance(r,dict) and 'id' in r}
        for row in snapshot.get('requests',[]):
            if not isinstance(row,dict):continue
            for reply in row.get('replies',[]):
                if not isinstance(reply,dict):continue
                items.append(_item('reply:'+str(reply.get('id','')), 'reply','collaboration_reply','task',reply.get('created_at'),
                    {'reply_id':reply.get('id'),'request_id':row['id'],'task_id':row.get('task_id'),
                     'member_id':reply.get('author_member_id'),'context_version':reply.get('context_version'),
                     'body':_text(reply.get('body'),4000),'evidence':_text(reply.get('evidence'),1000)},now))
        for row in snapshot.get('contracts',[]):
            if not isinstance(row,dict):continue
            for version in row.get('versions',[]):
                if not isinstance(version,dict):continue
                request=requests.get(version.get('source_request_id'),{})
                effective=version.get('version')==row.get('effective_version')
                decision=version.get('decision')
                items.append(_item('contract:'+str(row.get('id'))+':'+str(version.get('version')),'contract','contract','project',
                    version.get('decided_at') or version.get('created_at'),
                    {'contract_id':row.get('id'),'contract_key':_text(row.get('contract_key'),200),
                     'version':version.get('version'),'current_version':row.get('current_version'),'effective_version':row.get('effective_version'),
                     'effective':effective,'title':_text(version.get('title'),200),'body':_text(version.get('body'),4000),
                     'confirmation':'confirmed' if decision=='approved' else 'rejected' if decision=='rejected' else 'suggested',
                     'member_id':version.get('proposer_member_id'),'decided_by_member_id':version.get('decided_by_member_id'),
                     'source_request_id':version.get('source_request_id'),'task_id':request.get('task_id'),
                     'commit_ref':_text(version.get('commit_ref'),200)},now))
        for row in snapshot.get('dependencies',[]):
            if isinstance(row,dict):
                items.append(_item('dependency:'+str(row.get('id')),'dependency','dependency','task',row.get('updated_at'),
                    {'dependency_id':row.get('id'),'task_id':row.get('source_task_id'),'task_ids':[row.get('source_task_id'),row.get('target_task_id')],
                     'member_id':row.get('creator_member_id'),'need':_text(row.get('need'),500),'body':_text(row.get('context'),3000),
                     'status':row.get('status'),'revision':row.get('revision'),'routing_state':row.get('routing_state'),
                     'current_request_id':row.get('current_request_id')},now))
        for row in snapshot.get('assets',[]):
            if isinstance(row,dict):
                items.append(_item('asset:'+str(row.get('id')),'asset','shared_asset','project',row.get('created_at'),
                    {'asset_id':row.get('id'),'member_id':row.get('uploader_member_id'),'filename':_text(row.get('filename'),255),
                     'media_type':row.get('media_type'),'size_bytes':row.get('size_bytes'),'sha256':row.get('sha256'),
                     'source_type':row.get('source_type'),'source_ref':_text(row.get('source_ref'),500)},now))

        git = snapshot.get("git") if isinstance(snapshot.get("git"), dict) else {}
        for row in git.get("events", []):
            if isinstance(row, dict):
                items.append(_item(
                    "git:" + str(row.get("id", "")), "git_observation", "local_git", "task",
                    row.get("captured_at"),
                    {"task_id": row.get("task_id"), "member_id": _text(row.get("member_id"), 120),
                     "branch": _text(row.get("branch"), 250), "head": _text(row.get("head"), 64),
                     "paths": row.get("paths", [])[:50] if isinstance(row.get("paths"), list) else []}, now))
        for row in git.get("deliveries", []):
            if isinstance(row, dict):
                items.append(_item(
                    "delivery:" + str(row.get("ref_id", row.get("release_id", ""))), "delivery", "github_verified", "task",
                    row.get("sync_at"),
                    {key: row[key] for key in ("task_id", "branch", "commit_sha", "pr_number", "release_id", "tag_name", "state", "stale") if key in row}, now))

        graph=git.get('delivery_graph',{})
        for obj in graph.get('items',[]):
            for a in obj.get('associations',[]):
                item=_item('relation:'+str(obj.get('object_key'))+':'+str(a.get('task_id'))+':'+str(a.get('relationship_source')),
                    'delivery_relation','delivery_registry','task',a.get('linked_at'),
                    {'object_key':obj.get('object_key'),'delivery_kind':obj.get('kind'),'delivery_value':obj.get('value'),
                     'task_id':a.get('task_id'),'member_id':a.get('linked_by'),'relationship_source':a.get('relationship_source'),
                     'confirmation':'suggested' if a.get('relationship_source')=='suggested' else 'confirmed' if a.get('relationship_source')=='explicit' else 'observed',
                     'state':a.get('state'),'evidence':_text(a.get('evidence'),1000),'sync_at':a.get('sync_at'),
                     'stale':a.get('stale',False),'unavailable':a.get('unavailable',False)},now)
                items.append(item)
        from .project_activity import project_activity
        activity=project_activity(snapshot)
        for event in activity['items']:
            items.append(_item('activity:'+event['id'],'activity',event['source'],'task',event['occurred_at'],
                {'activity_id':event['id'],'task_id':event['task_id'],'member_id':event['actor_member_id'],
                 'summary':event['summary'],'event_type':event['type']},now))
        tasks={t['id']:t for t in snapshot.get('tasks',[]) if isinstance(t,dict) and 'id' in t}
        allowed_tasks=set(tasks)
        if scope:
            def overlaps(path):
                left,right=scope.rstrip('/'),path.rstrip('/')
                return left==right or left.startswith(right+'/') or right.startswith(left+'/')
            allowed_tasks={t for t in allowed_tasks if overlaps(tasks[t].get('scope',''))}
        if branch:
            branch_tasks={r.get('task_id') for r in snapshot.get('sessions',[]) if r.get('branch')==branch}
            branch_tasks.update(r.get('task_id') for r in git.get('events',[]) if r.get('branch')==branch)
            branch_tasks.update(r.get('task_id') for r in git.get('deliveries',[]) if r.get('branch')==branch)
            branch_tasks.update(t for o in graph.get('items',[]) if o.get('kind')=='branch' and o.get('value')==branch for t in o.get('task_ids',[]))
            allowed_tasks &= branch_tasks
        if delivery_kind:
            delivery_tasks={t for o in graph.get('items',[]) if o.get('kind')==delivery_kind and (not delivery_value or str(o.get('value'))==delivery_value) for t in o.get('task_ids',[])}
            allowed_tasks &= delivery_tasks
        filtered=[]
        for item in items:
            if not item:continue
            data=item['data']
            task_ids=set(data.get('task_ids',[]))|{data.get('task_id')}
            if task_id is not None and task_id not in task_ids:continue
            if member_id is not None and member_id not in (data.get('member_id'),data.get('receiver_member_id'),data.get('decided_by_member_id'),data.get('creator_member_id')):continue
            if (scope or branch or delivery_kind) and not task_ids.intersection(allowed_tasks):continue
            if source and source!=item['source']:continue
            if reference and reference!=item['id']:continue
            if query and query.casefold() not in json.dumps(data,ensure_ascii=False).casefold():continue
            if after and _when(item['observed_at'])<=_when(after):continue
            if data.get('unavailable') or data.get('state')=='unavailable':item['freshness']='unavailable'
            elif data.get('stale'):item['freshness']='stale'
            if 'confirmation' not in data:
                data['confirmation']=('agent_report' if item['source']=='agent_report' else 'observed' if item['source'] in ('local_git','github_verified','session_registry') else 'shared')
            data['reference']={'kind':item['kind'],'id':item['id']}
            filtered.append(item)
        filtered.sort(key=lambda item:(item['observed_at'],item['source'],item['id']),reverse=True)
        page=filtered[offset:offset+limit]
        truncated=offset+limit<len(filtered)
        filters={'task_id':task_id,'member_id':member_id}
        filters.update({k:v for k,v in dict(scope=scope,branch=branch,delivery_kind=delivery_kind,delivery_value=delivery_value,query=query,source=source,after=after,reference=reference).items() if v})
        return {'items':page,'truncated':truncated,'limit':limit,'offset':offset,'total':len(filtered),
            'next_offset':offset+limit if truncated else None,'filters':filters,'privacy':'shared_structured_only',
            'source_truncated':bool(activity['truncated'] or graph.get('truncated') or git.get('workspaces_truncated') or snapshot.get('lifecycle',{}).get('history_truncated')),
            'generated_at':now.astimezone(timezone.utc).isoformat().replace('+00:00','Z')}
