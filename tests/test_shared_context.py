import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import ValidationError
from transport_support import LiveService


class SharedContextTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path('.local/test-evidence/shared-context') / uuid4().hex
        self.folder.mkdir(parents=True)
        self.service = CoordinationService(self.folder / "context.sqlite3")
        self.owner = self.service.identity.create_room("Context", "Owner")
        self.member = self.service.identity.add_member(self.owner["web_token"], "Member")

    def test_context_is_bounded_source_labelled_and_excludes_private_payloads(self):
        task = self.service.tasks.create_task(self.owner["web_token"], "context-task", "Share context", "src")
        claimed = self.service.tasks.claim_task(self.owner["agent_token"], task["id"], session_key="session")
        self.service.activity.register_session(self.owner["agent_token"], "session", "codex-cli", "github.com/o/r", "main", task_id=task["id"], ownership_epoch=claimed["ownership_epoch"])
        self.service.activity.report_progress(self.owner["agent_token"], task["id"], "working", "Public progress", "commit abc", session_key="session", ownership_epoch=claimed["ownership_epoch"])
        self.service.messages.send_request(self.owner["agent_token"], "request", self.member["member_id"], task["id"], 1, "Need the API shape")
        result = self.service.read_context(self.owner["web_token"], limit=3)
        self.assertEqual(result["limit"], 3)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["privacy"], "shared_structured_only")
        self.assertTrue(all(item["privacy"] == "shared_structured" for item in result["items"]))
        self.assertTrue(all(set(item) == {"id", "kind", "source", "scope", "observed_at", "freshness", "privacy", "data"}
                            for item in result["items"]))
        encoded = json.dumps(result)
        self.assertNotIn("transcript", encoded)
        self.assertNotIn("tool_input", encoded)

    def test_filters_and_freshness_are_explicit(self):
        task = self.service.tasks.create_task(self.owner["web_token"], "fresh-task", "Freshness", "src")
        claimed = self.service.tasks.claim_task(self.owner["agent_token"], task["id"], session_key="fresh-session")
        self.service.activity.register_session(self.owner["agent_token"], "fresh-session", "codex-cli", "github.com/o/r", "main", task_id=task["id"], ownership_epoch=claimed["ownership_epoch"])
        result = self.service.read_context(self.owner["web_token"], task_id=task["id"], member_id=self.owner["member_id"])
        self.assertTrue(result["items"])
        self.assertTrue(all(item["data"].get("task_id") == task["id"] or item["kind"] == "task" for item in result["items"]))
        session = next(item for item in result["items"] if item["kind"] == "session")
        self.assertEqual(session["freshness"], "fresh")
        self.assertEqual(result["filters"]["member_id"], self.owner["member_id"])

    def test_invalid_limits_are_rejected(self):
        for limit in (0, 101, True, "10"):
            with self.subTest(limit=limit), self.assertRaises(ValidationError):
                self.service.read_context(self.owner["web_token"], limit=limit)

    def test_http_context_query_uses_the_same_structured_projection(self):
        live = LiveService()
        self.addCleanup(live.close)
        owner, _ = live.bootstrap()
        task = live.request("POST", "/api/tasks", owner["web_token"],
                            {"intent_key": "http-context", "title": "HTTP context", "scope": "src"})[1]
        status, result, _ = live.request("GET", "/api/context?task_id=%d&limit=1" % task["id"], owner["web_token"])
        self.assertEqual(status, 200, result)
        self.assertEqual(result["filters"], {"task_id": task["id"], "member_id": None})
        self.assertEqual(result["items"][0]["data"]["task_id"], task["id"])

    def test_effective_and_proposed_contracts_dependencies_assets_and_replies_are_queryable(self):
        task=self.service.tasks.create_task(self.owner['web_token'],'rich','Rich context','src/api')
        target=self.service.tasks.create_task(self.owner['web_token'],'dep','Dependency target','src/db')
        claimed=self.service.tasks.claim_task(self.owner['agent_token'],task['id'])
        self.service.tasks.claim_task(self.member['agent_token'],target['id'])
        request=self.service.messages.send_request(self.owner['agent_token'],'q',self.member['member_id'],task['id'],1,'API question')
        self.service.messages.reply(self.member['agent_token'],request['id'],'answer',1,'Shared answer','explicit evidence')
        contract=self.service.contracts.propose(self.owner['agent_token'],'schema',0,'Approved v1','Effective API body',request['id'])
        self.service.contracts.decide(self.owner['web_token'],contract['id'],1,'approved')
        self.service.contracts.propose(self.owner['agent_token'],'schema',1,'Proposed v2','Pending API body',request['id'])
        self.service.dependencies.create_dependency(self.owner['agent_token'],task['id'],target['id'],'Need schema',claimed['revision'],'need',context='Structured dependency')
        asset=self.service.assets.upload(self.owner['web_token'],'guide.md','text/markdown',b'# explicit asset')
        view=self.service.read_context(self.owner['agent_token'],limit=100)
        kinds={i['kind'] for i in view['items']}
        self.assertTrue({'contract','dependency','asset','reply'}<=kinds)
        effective=next(i for i in view['items'] if i['kind']=='contract' and i['data'].get('version')==1)
        proposal=next(i for i in view['items'] if i['kind']=='contract' and i['data'].get('version')==2)
        self.assertEqual(effective['data']['confirmation'],'confirmed')
        self.assertEqual(effective['data']['body'],'Effective API body')
        self.assertEqual(proposal['data']['confirmation'],'suggested')
        self.assertEqual(next(i for i in view['items'] if i['kind']=='asset')['data']['asset_id'],asset['id'])
        scoped=self.service.read_context(self.owner['agent_token'],task_id=task['id'])
        self.assertTrue(any(i['kind']=='contract' for i in scoped['items']))
        self.assertTrue(any(i['kind']=='reply' for i in scoped['items']))
        self.assertIsNone(self.service.messages.list_requests(self.owner['web_token'])[0]['read_at'])

    def test_scope_branch_delivery_query_pagination_and_late_tasks(self):
        from coopagents.context import ContextStore
        stamp='2026-01-01T00:00:00Z'
        tasks=[dict(id=i,title='Task '+str(i),scope='src/api' if i==250 else 'docs',created_at=stamp,owner_member_id='m') for i in range(1,251)]
        source={'tasks':tasks,'sessions':[dict(id=1,member_id='m',tool='cursor',repository='repo',branch='feature',task_id=250,updated_at=stamp)],
            'git':{'delivery_graph':{'items':[{'object_key':'pr:7','kind':'pr','value':7,'task_ids':[250],
                'associations':[{'task_id':250,'linked_by':'m','linked_at':stamp,'relationship_source':'explicit','state':'pending_sync','stale':False,'unavailable':False}]}]}}}
        for args in ({'scope':'src/api'},{'branch':'feature'},{'delivery_kind':'pr','delivery_value':'7'},{'query':'Task 250'}):
            view=ContextStore.project(source,**args,limit=100)
            self.assertTrue(any(i['data'].get('task_id')==250 for i in view['items']),args)
        first=ContextStore.project(source,limit=2)
        second=ContextStore.project(source,limit=2,offset=first['next_offset'])
        self.assertFalse({i['id'] for i in first['items']} & {i['id'] for i in second['items']})
        self.assertTrue(first['truncated'])

    def test_projection_uses_source_freshness_and_does_not_leak_unknown_fields(self):
        from coopagents.context import ContextStore
        stamp='2026-01-01T00:00:00Z'
        result=ContextStore.project({'tasks':[], 'git':{'deliveries':[dict(ref_id=1,task_id=1,source='github_verified',sync_at=stamp,state='unavailable',stale=True,transcript='PRIVATE-TEXT',prompt='PRIVATE-PROMPT')]}})
        item=result['items'][0]
        self.assertEqual(item['freshness'],'unavailable')
        self.assertNotIn('PRIVATE',json.dumps(result))


if __name__ == "__main__":
    unittest.main()
