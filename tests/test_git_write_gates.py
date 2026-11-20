"""Overlap gates: fresh observations block, stale pass, overrides unblock (W3)."""
import json
import unittest
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import Conflict, ValidationError
from coopagents.github_sync import GitHubSync
from coopagents.identity import IdentityStore
from coopagents.repositories import RepositoryStore, now
from coopagents.tasks import TaskStore
from test_github_write import WriteFakeProvider


def fresh():
    return now().isoformat()


def stale():
    return (now() - timedelta(minutes=10)).isoformat()


class GateFixture:
    def build(self, root):
        self.identity = IdentityStore(root)
        self.owner = self.identity.create_room('Team', 'Owner')
        self.member = self.identity.add_member(self.owner['web_token'], 'Member')
        self.other = self.identity.add_member(self.owner['web_token'], 'Other')
        self.repositories = RepositoryStore(self.identity)
        self.repositories.bind_repository(self.owner['web_token'], 'github.com/acme/demo')
        self.repositories.set_git_write_enabled(self.owner['web_token'], True)
        self.tasks = TaskStore(self.identity)
        self.first = self.tasks.create_task(self.owner['web_token'], 'first', 'Build Login', 'src')
        self.tasks.claim_task(self.member['agent_token'], self.first['id'], session_key='s1')
        self.second = self.tasks.create_task(self.owner['web_token'], 'second', 'Fix Shared', 'src')
        self.tasks.claim_task(self.other['agent_token'], self.second['id'], session_key='s2')

    def observe(self, token, task_id, paths, captured_at, session_key, workspace_id):
        return self.repositories.observe(token, task_id, {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': workspace_id,
            'repository': 'github.com/acme/demo', 'branch': 'main', 'head': 'a' * 40,
            'paths': paths, 'captured_at': captured_at}, session_key=session_key, ownership_epoch=1)

    def blocks(self, gate=None):
        with self.identity.db.connect() as c:
            rows = c.execute('SELECT * FROM git_conflict_blocks').fetchall()
            rows = [dict(row) for row in rows]
            return [row for row in rows if gate is None or row['gate'] == gate]

    def add_override(self, task_id, paths, epoch=1, reason='manager review'):
        with self.identity.db.connect(write=True) as c:
            c.execute('''INSERT INTO git_overlap_overrides(room_id,task_id,ownership_epoch,
                paths_json,reason,overridden_by,created_at) VALUES(?,?,?,?,?,?,?)''',
                (self.owner['room_id'], task_id, epoch, json.dumps(paths), reason,
                 self.owner['member_id'], now().isoformat()))


class CheckOverlapTests(GateFixture, unittest.TestCase):
    def setUp(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        self.build(root / 'gates.sqlite3')

    def check(self, **overrides):
        args = {'token': self.member['agent_token'], 'task_id': self.first['id'],
                'session_key': 's1', 'ownership_epoch': 1}
        args.update(overrides)
        return self.repositories.check_overlap(**args)

    def test_pure_read_uses_caller_fresh_paths_and_records_nothing(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        result = self.check()
        self.assertTrue(result['blocked'])
        self.assertEqual(result['paths_checked'], ['src/shared.py'])
        self.assertEqual(len(result['conflicts']), 1)
        self.assertEqual(result['conflicts'][0]['task_id'], self.second['id'])
        self.assertEqual(self.blocks(), [])

    def test_explicit_paths_are_checked_instead_of_observations(self):
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        result = self.check(paths=['src/shared.py'])
        self.assertTrue(result['blocked'])
        self.assertEqual(result['paths_checked'], ['src/shared.py'])
        self.assertFalse(self.check(paths=['src/own.py'])['blocked'])

    def test_stale_observations_never_block(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], stale(), 's2', 'workspace-second-1')
        result = self.check()
        self.assertFalse(result['blocked'])
        self.assertEqual(result['conflicts'], [])

    def test_stale_caller_checkpoint_checks_no_paths(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], stale(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        result = self.check()
        self.assertFalse(result['fresh_checkpoint'])
        self.assertEqual(result['paths_checked'], [])
        self.assertFalse(result['blocked'])

    def test_gated_read_records_and_upserts_one_block_row(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        self.check(gate='claim')
        self.check(gate='claim')
        rows = self.blocks('claim')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['task_id'], self.first['id'])
        self.assertEqual(json.loads(rows[0]['conflicts_json'])[0]['task_id'], self.second['id'])

    def test_gated_read_without_conflict_records_nothing(self):
        self.check(gate='delivery')
        self.assertEqual(self.blocks(), [])

    def test_gated_read_with_flag_off_is_rejected_and_records_nothing(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        with self.assertRaises(Conflict):
            self.check(gate='claim')
        with self.assertRaises(Conflict):
            self.check(gate='delivery')
        self.assertEqual(self.blocks(), [])

    def test_pure_read_with_flag_off_still_works_and_records_nothing(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        self.repositories.set_git_write_enabled(self.owner['web_token'], False)
        result = self.check()
        self.assertTrue(result['blocked'])
        self.assertEqual(self.blocks(), [])

    def test_invalid_gate_and_paths_rejected(self):
        with self.assertRaises(ValidationError):
            self.check(gate='merge')
        with self.assertRaises(ValidationError):
            self.check(paths=['../escape.py'])
        with self.assertRaises(ValidationError):
            self.check(paths='src/shared.py')

    def test_override_subtracts_covered_paths_only(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/a.py', 'src/b.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/a.py', 'src/b.py'], fresh(), 's2', 'workspace-second-1')
        self.add_override(self.first['id'], ['src/a.py'])
        result = self.check()
        self.assertTrue(result['blocked'])
        self.assertEqual(result['conflicts'][0]['paths'], ['src/b.py'])
        self.add_override(self.first['id'], ['src/b.py'])
        self.assertFalse(self.check()['blocked'])

    def test_override_is_epoch_keyed(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        self.add_override(self.first['id'], ['src/shared.py'], epoch=2)
        self.assertTrue(self.check()['blocked'])


class ClaimGateTests(GateFixture, unittest.TestCase):
    def setUp(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        self.build(root / 'gates.sqlite3')
        self.branch = 'coopagents/task-%d-1-build-login' % self.first['id']

    def record(self, preview=False):
        return self.repositories.record_branch(self.member['agent_token'], self.first['id'],
                                               self.branch, 'a' * 40, 'branch-key',
                                               session_key='s1', ownership_epoch=1, preview=preview)

    def test_fresh_overlap_blocks_claim_and_records_block(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        with self.assertRaises(Conflict) as caught:
            self.record()
        self.assertIn('src/shared.py', str(caught.exception))
        self.assertIn(str(self.second['id']), str(caught.exception))
        self.assertEqual(len(self.blocks('claim')), 1)
        self.assertIsNone(self.repositories.get_branch(
            self.member['agent_token'], self.first['id'], session_key='s1', ownership_epoch=1))

    def test_preview_reports_block_without_recording_or_raising(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        result = self.record(preview=True)
        self.assertTrue(result['blocked'])
        self.assertEqual(result['conflicts'][0]['task_id'], self.second['id'])
        self.assertEqual(self.blocks(), [])

    def test_claim_passes_without_caller_observation(self):
        result = self.record()
        self.assertEqual(result['branch'], self.branch)
        self.assertEqual(self.blocks(), [])

    def test_claim_passes_when_other_observation_is_stale(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], stale(), 's2', 'workspace-second-1')
        self.assertEqual(self.record()['branch'], self.branch)

    def test_successful_claim_clears_earlier_block(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        with self.assertRaises(Conflict):
            self.record()
        self.assertEqual(len(self.blocks('claim')), 1)
        self.observe(self.other['agent_token'], self.second['id'], ['src/elsewhere.py'], fresh(), 's2', 'workspace-second-1')
        self.assertEqual(self.record()['branch'], self.branch)
        self.assertEqual(self.blocks('claim'), [])

    def test_override_unblocks_claim(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        self.add_override(self.first['id'], ['src/shared.py'])
        self.assertEqual(self.record()['branch'], self.branch)


class DeliveryGateTests(GateFixture, unittest.TestCase):
    def setUp(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        self.build(root / 'gates.sqlite3')
        self.app = WriteFakeProvider()
        self.sync = GitHubSync(self.identity, self.repositories, self.app)
        begun = self.sync.begin_authorization(self.owner['web_token'])
        self.sync.complete_authorization(begun['state'], 'code')
        self.sync.finish_authorization(self.owner['web_token'], begun['state'])
        self.branch = 'coopagents/task-%d-1-build-login' % self.first['id']
        self.repositories.record_branch(self.member['agent_token'], self.first['id'], self.branch,
                                        'a' * 40, 'branch-key', session_key='s1', ownership_epoch=1)

    def deliver(self, **overrides):
        args = {'token': self.member['agent_token'], 'task_id': self.first['id'], 'branch': self.branch,
                'head_sha': 'c' * 40, 'base_branch': 'main', 'title': 'Task 1: Build it',
                'body': 'Delivery body', 'request_key': 'd1', 'session_key': 's1', 'ownership_epoch': 1}
        args.update(overrides)
        return self.sync.open_pr(**args)

    def test_delivery_requires_fresh_checkpoint(self):
        with self.assertRaises(Conflict) as caught:
            self.deliver()
        self.assertIn('fresh checkpoint', str(caught.exception))
        self.assertEqual(self.app.lookups, [])
        self.assertEqual(self.app.creates, [])

    def test_delivery_preview_reports_stale_checkpoint_without_raising(self):
        result = self.deliver(preview=True)
        self.assertFalse(result['fresh_checkpoint'])
        self.assertFalse(result['blocked'])

    def test_fresh_overlap_blocks_delivery_and_records_block(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        with self.assertRaises(Conflict) as caught:
            self.deliver()
        self.assertIn('src/shared.py', str(caught.exception))
        self.assertEqual(len(self.blocks('delivery')), 1)
        self.assertEqual(self.app.lookups, [])
        self.assertEqual(self.app.creates, [])

    def test_delivery_preview_reports_block_without_api_calls(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        result = self.deliver(preview=True)
        self.assertTrue(result['blocked'])
        self.assertEqual(result['conflicts'][0]['task_id'], self.second['id'])
        self.assertEqual(self.blocks(), [])
        self.assertEqual(self.app.lookups, [])
        self.assertEqual(self.app.creates, [])

    def test_successful_delivery_clears_delivery_block(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        with self.assertRaises(Conflict):
            self.deliver()
        self.assertEqual(len(self.blocks('delivery')), 1)
        self.observe(self.other['agent_token'], self.second['id'], ['src/elsewhere.py'], fresh(), 's2', 'workspace-second-1')
        result = self.deliver()
        self.assertEqual(result['state'], 'pr_opened')
        self.assertEqual(self.blocks('delivery'), [])

    def test_override_unblocks_delivery(self):
        self.observe(self.member['agent_token'], self.first['id'], ['src/shared.py'], fresh(), 's1', 'workspace-first-1')
        self.observe(self.other['agent_token'], self.second['id'], ['src/shared.py'], fresh(), 's2', 'workspace-second-1')
        self.add_override(self.first['id'], ['src/shared.py'])
        self.assertEqual(self.deliver()['state'], 'pr_opened')


class ConflictCardTests(unittest.TestCase):
    def test_block_surfaces_as_manager_decision_card(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        service = CoordinationService(root / 'cards.sqlite3')
        owner = service.identity.create_room('Team', 'Owner')
        member = service.identity.add_member(owner['web_token'], 'Member')
        other = service.identity.add_member(owner['web_token'], 'Other')
        service.repositories.bind_repository(owner['web_token'], 'github.com/acme/demo')
        service.repositories.set_git_write_enabled(owner['web_token'], True)
        first = service.tasks.create_task(owner['web_token'], 'first', 'Build Login', 'src')
        service.tasks.claim_task(member['agent_token'], first['id'], session_key='s1')
        second = service.tasks.create_task(owner['web_token'], 'second', 'Fix Shared', 'src')
        service.tasks.claim_task(other['agent_token'], second['id'], session_key='s2')

        def observe(token, task_id, paths, session_key, workspace_id):
            service.repositories.observe(token, task_id, {
                'request_key': 'k-' + str(uuid4()), 'workspace_id': workspace_id,
                'repository': 'github.com/acme/demo', 'branch': 'main', 'head': 'a' * 40,
                'paths': paths, 'captured_at': fresh()},
                session_key=session_key, ownership_epoch=1)

        observe(member['agent_token'], first['id'], ['src/shared.py'], 's1', 'workspace-first-1')
        observe(other['agent_token'], second['id'], ['src/shared.py'], 's2', 'workspace-second-1')
        service.repositories.check_overlap(member['agent_token'], first['id'], session_key='s1',
                                          ownership_epoch=1, gate='claim')
        workflow = service.call('read_workflow', owner['web_token'], {})
        cards = [card for card in workflow['decisions'] if card['kind'] == 'git_conflict']
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card['task_id'], first['id'])
        self.assertEqual(card['blocking_task_id'], second['id'])
        self.assertEqual(card['operation'], 'override_overlap')
        self.assertEqual(card['required_input'], ['reason'])
        self.assertTrue(card['eligible'])
        self.assertTrue(card['requires_human'])
        self.assertEqual(card['authority'], 'project_manager_web_user')
        self.assertIn('src/shared.py', card['summary'])


class OverlapCheckHttpTests(unittest.TestCase):
    def test_overlap_check_route_answers_the_adapter_call(self):
        from starlette.testclient import TestClient

        from coopagents.api import create_app
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        app = create_app(root / 'http.sqlite3', base_url='http://127.0.0.1')
        service = app.state.service
        owner = service.identity.create_room('Team', 'Owner')
        member = service.identity.add_member(owner['web_token'], 'Member')
        other = service.identity.add_member(owner['web_token'], 'Other')
        service.repositories.bind_repository(owner['web_token'], 'github.com/acme/demo')
        first = service.tasks.create_task(owner['web_token'], 'first', 'Build Login', 'src')
        service.tasks.claim_task(member['agent_token'], first['id'], session_key='s1')
        second = service.tasks.create_task(owner['web_token'], 'second', 'Fix Shared', 'src')
        service.tasks.claim_task(other['agent_token'], second['id'], session_key='s2')
        service.repositories.observe(other['agent_token'], second['id'], {
            'request_key': 'k-' + str(uuid4()), 'workspace_id': 'workspace-second-1',
            'repository': 'github.com/acme/demo', 'branch': 'main', 'head': 'a' * 40,
            'paths': ['src/shared.py'], 'captured_at': fresh()},
            session_key='s2', ownership_epoch=1)
        agent = {'Authorization': 'Bearer ' + member['agent_token']}
        with TestClient(app, base_url='http://127.0.0.1') as client:
            blocked = client.post('/api/git/overlap-check', headers=agent, json={
                'task_id': first['id'], 'paths': ['src/shared.py'],
                'session_key': 's1', 'ownership_epoch': 1})
            self.assertEqual(blocked.status_code, 200, blocked.text)
            self.assertTrue(blocked.json()['blocked'])
            self.assertEqual(blocked.json()['conflicts'][0]['task_id'], second['id'])
            clear = client.post('/api/git/overlap-check', headers=agent, json={
                'task_id': first['id'], 'paths': ['src/own.py'],
                'session_key': 's1', 'ownership_epoch': 1})
            self.assertEqual(clear.status_code, 200, clear.text)
            self.assertFalse(clear.json()['blocked'])


class PolicyGateTests(unittest.TestCase):
    def test_git_write_gates_rule_is_published(self):
        from coopagents.collaboration_policy import DAILY_COLLABORATION_POLICY, POLICY_RULES, POLICY_VERSION
        self.assertIn('git_write_gates', POLICY_RULES)
        rule = POLICY_RULES['git_write_gates']
        self.assertIn('overlap', rule)
        self.assertIn('human', rule)
        self.assertIn(POLICY_VERSION, DAILY_COLLABORATION_POLICY)
        from coopagents.collaboration_policy import policy_for_event
        self.assertIn(rule, policy_for_event('completion', task_bound=True)['instructions'])
        self.assertNotIn(rule, DAILY_COLLABORATION_POLICY)


if __name__ == '__main__':
    unittest.main()
