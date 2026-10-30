import json
from pathlib import Path
import unittest
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, ValidationError


class EventsTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/events-tests') / (str(uuid4()) + '.sqlite3')
        self.service = CoordinationService(self.path)
        self.room = self.service.identity.create_room('room', 'owner')
        self.token = self.room['web_token']

    def test_transaction_replay_and_room_isolation(self):
        feed = self.service.change_events
        cursor = feed.read(self.token)['cursor']
        task = self.service.tasks.create_task(self.token, 'key', 'SECRET TITLE', 'SECRET SCOPE')
        page = feed.read(self.token, cursor, 1)
        self.assertEqual(page['events'][0]['topic'], 'tasks')
        self.assertEqual(page['events'][0]['entity_id'], str(task['id']))
        self.assertNotIn('SECRET', json.dumps(page))
        before = feed.read(self.token)['cursor']
        with self.assertRaises(RuntimeError):
            with self.service.identity.db.connect(write=True) as c:
                c.execute('UPDATE tasks SET title=? WHERE id=?', ('rolled back', task['id']))
                raise RuntimeError('rollback')
        self.assertEqual(feed.read(self.token)['cursor'], before)
        other = self.service.identity.create_room('other', 'owner')
        self.assertFalse(any(e['room_id'] == self.room['room_id'] for e in feed.read(other['web_token'])['events']))
        self.assertEqual(feed.read(self.token)['cursor'], before)
        self.service.tasks.create_task(self.token, 'second', 'title', 'scope')
        self.assertEqual(feed.read(self.token, before)['events'][0]['id'], before + 1)
        restarted = CoordinationService(self.path)
        self.assertEqual(restarted.change_events.read(self.token, cursor), feed.read(self.token, cursor))

    def test_auth_and_cursor_bounds_and_revocation(self):
        feed = self.service.change_events
        with self.assertRaises(AccessDenied):
            feed.read('invalid')
        for cursor in (-1, True, '2', 2**63):
            with self.assertRaises(ValidationError):
                feed.read(self.token, cursor)
        for limit in (0, True, 201):
            with self.assertRaises(ValidationError):
                feed.read(self.token, limit=limit)
        self.assertEqual(feed.read(self.token, 999999)['reset'], 'future_cursor')
        self.service.identity.rotate_agent(self.token)
        self.assertTrue(any(e['topic'] == 'identity' for e in feed.read(self.token)['events']))
        with self.assertRaises(AccessDenied):
            feed.read(self.room['agent_token'])
        with self.service.identity.db.connect() as c:
            serialized = json.dumps([dict(r) for r in c.execute('SELECT * FROM room_change_events')])
        self.assertNotIn(self.token, serialized)
        self.assertNotIn('token_hash', serialized)

    def test_bounded_paging_expired_cursor_and_message_redaction(self):
        feed = self.service.change_events
        cursor = feed.read(self.token)['cursor']
        self.service.messages.send_request(self.room['agent_token'], 'secret-key', None, None, 1, 'SECRET BODY')
        page = feed.read(self.token, cursor, 1)
        self.assertEqual(page['events'][0]['topic'], 'messages')
        self.assertLessEqual(len(page['events']), 1)
        self.assertNotIn('SECRET BODY', json.dumps(page))
        with self.service.identity.db.connect(write=True) as c:
            c.execute('UPDATE room_event_streams SET floor=? WHERE room_id=?', (cursor, self.room['room_id']))
        self.assertEqual(feed.read(self.token, 0)['reset'], 'expired_cursor')

    def test_domain_table_trigger_coverage_without_historical_backfill(self):
        with self.service.identity.db.connect() as c:
            triggers = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            for table in ('tasks', 'progress', 'sessions', 'message_requests', 'message_replies',
                          'contracts', 'contract_versions', 'task_lifecycle_events', 'task_handoffs',
                          'task_dependencies', 'dependency_reads', 'repo_bindings', 'git_observations',
                          'github_connections', 'github_release_refs', 'github_evidence', 'credentials'):
                self.assertIn('change_' + table + '_update', triggers)
        before = self.service.change_events.read(self.token)
        self.service.change_events.install_triggers()
        self.assertEqual(self.service.change_events.read(self.token), before)

    def test_diagnostic_event_does_not_break_domain_write(self):
        result = self.service.checkpoints.diagnostic_start(self.room['agent_token'], 'challenge')
        events = self.service.change_events.read(self.token)['events']
        self.assertTrue(any(e['entity_id'] == result['diagnostic_id'] for e in events))


if __name__ == '__main__':
    unittest.main()
