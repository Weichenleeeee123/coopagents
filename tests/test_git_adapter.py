from pathlib import Path
import json
import subprocess
import unittest
from uuid import uuid4
import asyncio
import os
import sys
import sqlite3
import threading
from contextlib import closing
from mcp import Client, StdioServerParameters
from crewmesh.git_adapter import LocalAdapter, service_origin
from crewmesh.errors import ValidationError
from transport_support import LiveService


class AdapterTests(unittest.TestCase):
    def test_service_origin_is_explicit_and_redirect_safe(self):
        for bad in ['http://example.com','https://user:secret@example.com','https://example.com/api','https://example.com?token=x','file:///tmp']:
            with self.assertRaises(ValidationError): service_origin(bad)
        self.assertEqual(service_origin('https://example.com/'),'https://example.com')

    def test_offline_capture_is_durable_before_network_validation(self):
        root=Path('.local/test-evidence')/str(uuid4());repo=root/'repo';repo.mkdir(parents=True)
        subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'remote','add','origin','https://github.com/acme/demo'],check=True,capture_output=True)
        adapter=LocalAdapter(repo,'http://127.0.0.1:1',str(uuid4()),'valid-token',state_root=root/'queue')
        for bad in [-1,0,True,'1']:
            with self.assertRaises(ValidationError):adapter.checkpoint(bad)
        self.assertFalse((root/'queue').exists())
        with self.assertRaises(ValidationError): adapter.checkpoint(1)
        queued=list((root/'queue').glob('*.sqlite3'))
        self.assertEqual(len(queued),1)
        def records():
            with closing(sqlite3.connect(queued[0])) as connection:
                return connection.execute('SELECT payload,status FROM checkpoints ORDER BY id').fetchall()
        original=json.loads(records()[0][0])
        with self.assertRaises(ValidationError): adapter.checkpoint(1)
        self.assertEqual(json.loads(records()[0][0]),original)
        self.assertEqual(len(records()),2)
        calls=[]
        def online(path,data=None):
            calls.append((path,data))
            if path=='/api/me': return {'me':{'room_id':adapter.project}}
            if path=='/api/git/binding': return {'repository':'github.com/acme/demo'}
            return {'observation':data['observation']}
        adapter.request=online
        adapter.checkpoint(1)
        self.assertEqual(next(data for path,data in calls if path=='/api/git/checkpoint'),original)
        self.assertTrue(all(status=='completed' for _,status in records()))

    def test_concurrent_queue_returns_each_callers_observation(self):
        root=Path('.local/test-evidence')/str(uuid4());repo=root/'repo';repo.mkdir(parents=True)
        subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'remote','add','origin','https://github.com/acme/demo'],check=True,capture_output=True)
        adapters=[LocalAdapter(repo,'http://127.0.0.1:1','project','valid-token',state_root=root/'queue') for _ in range(2)]
        barrier=threading.Barrier(2);results={};errors=[]
        for adapter in adapters:
            adapter.validate_project=lambda local:barrier.wait(timeout=10)
            adapter.request=lambda path,data=None:{'observation':{'task_id':data['task_id'],**data['observation']}}
        def run(index):
            try:results[index]=adapters[index].checkpoint(index+1)
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=run,args=(i,)) for i in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(15)
        self.assertFalse(errors,errors)
        self.assertEqual([results[i]['observation']['task_id'] for i in range(2)],[1,2])

    def test_two_local_clones_checkpoint_into_live_project(self):
        live = LiveService(); self.addCleanup(live.close)
        owner, member = live.bootstrap()
        live.request('POST','/api/git/binding',owner['web_token'],{'repository':'github.com/acme/demo'})
        root = Path('.local/test-evidence') / str(uuid4()); root.mkdir(parents=True)
        seed=root/'source';seed.mkdir()
        def seed_git(*args):
            return subprocess.run(['git','-c','core.hooksPath='+os.devnull,'-C',str(seed),*args],check=True,capture_output=True)
        seed_git('init');seed_git('config','user.email','test@example.invalid');seed_git('config','user.name','Test')
        (seed/'auth.py').write_text('v1');seed_git('add','auth.py');seed_git('commit','-m','initial')
        adapters=[]
        for index, identity in enumerate([owner,member]):
            repo = root / str(index); repo.mkdir()
            subprocess.run(['git','-c','core.hooksPath='+os.devnull,'clone','--no-hardlinks',str(seed.resolve()),str(repo.resolve())],check=True,capture_output=True)
            def git(*args):
                return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
            git('remote','set-url','origin','https://github.com/acme/demo.git')
            (repo/'auth.py').write_text('v2')
            task = live.request('POST','/api/tasks',owner['web_token'],{'intent_key':str(index),'title':'Task','scope':'src'})[1]
            live.request('POST',f"/api/tasks/{task['id']}/claim",identity['agent_token'],{})
            adapter = LocalAdapter(repo,live.url,owner['room_id'],identity['agent_token'],state_root=root/'state')
            adapters.append(adapter)
            result = adapter.checkpoint(task['id'])
            self.assertEqual(result['observation']['paths'],['auth.py'])
            self.assertEqual(result['team']['me']['member_id'],identity['member_id'])
            if index==0:
                contract=adapter.forward('propose_contract',{'contract_key':'login','expected_version':0,'title':'Login','body':'v1 returns user_id'})
                status,_,_=live.request('POST',f"/api/contracts/{contract['id']}/decision",owner['web_token'],{'version':1,'decision':'approved'})
                self.assertEqual(status,200)
            if index == 1:
                async def stdio_checkpoint():
                    params=StdioServerParameters(command=sys.executable,
                        args=['-m','crewmesh.git_adapter','--repository',str(repo.resolve()),'--service',live.url,'--project',owner['room_id']],
                        env={**os.environ,'CREWMESH_AGENT_TOKEN':identity['agent_token'],'LOCALAPPDATA':str((root/'appdata').resolve())})
                    async with Client(params,cache=None) as client:
                        names={t.name for t in (await client.list_tools()).tools}
                        self.assertIn('repo_checkpoint',names)
                        invalid=await client.call_tool('claim_task',{'task_id':True})
                        self.assertTrue(invalid.is_error)
                        self.assertIn('Invalid field type',invalid.content[0].text)
                        checkpoint=await client.call_tool('repo_checkpoint',{'task_id':task['id']})
                        self.assertFalse(checkpoint.is_error,checkpoint.content)
                        self.assertEqual(checkpoint.structured_content['team']['me']['member_id'],identity['member_id'])
                        self.assertEqual(checkpoint.structured_content['team']['contracts'][0]['effective_version'],1)
                asyncio.run(stdio_checkpoint())
        self.assertEqual(result['team']['git']['overlaps'][0]['paths'],['auth.py'])
        contract=adapters[1].forward('propose_contract',{'contract_key':'login','expected_version':1,'title':'Login v2','body':'v2 adds login_ticket'})
        self.assertEqual(live.request('POST',f"/api/contracts/{contract['id']}/decision",owner['web_token'],{'version':2,'decision':'approved'})[0],200)
        team=adapters[0].forward('read_team',{})
        self.assertEqual(team['contracts'][0]['effective_version'],2)
        request=adapters[0].forward('send_request',{'request_key':'login-check','context_version':2,'body':'Confirm login_ticket','receiver_member_id':member['member_id']})
        inbox=adapters[1].forward('read_inbox',{})
        self.assertEqual(inbox['requests'][0]['id'],request['id'])
        adapters[1].forward('acknowledge',{'request_id':request['id']})
        adapters[1].forward('reply',{'request_id':request['id'],'request_key':'login-reply','context_version':2,'body':'login_ticket confirmed'})
        adapters[0].forward('resolve_request',{'request_id':request['id'],'context_version':2})
        wrong = LocalAdapter(repo,live.url,str(uuid4()),member['agent_token'],state_root=root/'wrong')
        with self.assertRaises(ValidationError): wrong.checkpoint(task['id'])
        with self.assertRaises(ValidationError): wrong.forward('claim_task',{'task_id':task['id']})
        config_dir=repo/'.crewmesh'; config_dir.mkdir()
        (config_dir/'project.json').write_text(json.dumps({'schema_version':1,'project_ref':str(uuid4()),'repository':'github.com/acme/demo'}))
        with self.assertRaises(ValidationError): adapter.checkpoint(task['id'])
