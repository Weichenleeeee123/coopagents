from datetime import datetime, timezone
import unittest
from transport_support import LiveService


class GitHTTPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()
        self.task = self.live.request('POST','/api/tasks',self.owner['web_token'],
            {'intent_key':'git','title':'Git task','scope':'src'})[1]
        self.live.request('POST',f"/api/tasks/{self.task['id']}/claim",self.member['agent_token'],{})

    def observation(self):
        return dict(request_key='checkpoint',workspace_id='a'*64,repository='github.com/acme/demo',
                    branch='feature',head='b'*40,paths=['src/auth.py'],captured_at=datetime.now(timezone.utc).isoformat())

    def test_project_binding_and_checkpoint_snapshot(self):
        status, binding, _ = self.live.request('POST','/api/git/binding',self.owner['web_token'],{'repository':'https://github.com/acme/demo.git'})
        self.assertEqual(status,200,binding)
        status, checkpoint, _ = self.live.request('POST','/api/git/checkpoint',self.member['agent_token'],
            {'task_id':self.task['id'],'observation':self.observation()})
        self.assertEqual(status,200,checkpoint)
        self.assertEqual(checkpoint['team']['git']['workspaces'][0]['source'],'local_git')
        self.assertEqual(checkpoint['inbox']['requests'],[])
        status, snap, _ = self.live.request('GET','/api/snapshot',self.owner['web_token'])
        self.assertEqual(status,200,snap)
        self.assertEqual(snap['git']['binding']['repository'],'github.com/acme/demo')

    def test_permissions_and_strict_schema(self):
        for token in [self.member['web_token'],self.owner['agent_token']]:
            self.assertEqual(self.live.request('POST','/api/git/binding',token,{'repository':'github.com/acme/demo'})[0],401)
        self.live.request('POST','/api/git/binding',self.owner['web_token'],{'repository':'github.com/acme/demo'})
        self.assertEqual(self.live.request('POST','/api/git/checkpoint',self.owner['agent_token'],
            {'task_id':self.task['id'],'observation':self.observation()})[0],401)
        self.assertEqual(self.live.request('POST','/api/git/checkpoint',self.member['agent_token'],
            {'task_id':self.task['id'],'observation':self.observation(),'author':'someone'})[0],400)
