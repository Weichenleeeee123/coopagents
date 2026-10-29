import json
import unittest

from coopagents.project_activity import project_activity
from coopagents.coordination import CoordinationService
from pathlib import Path
from uuid import uuid4


class ProjectActivityTests(unittest.TestCase):
    def test_explicit_progress_and_structured_events_are_ordered_without_private_payloads(self):
        snapshot = {
            'progress': [{'task_id': 1, 'member_id': 'm1', 'state': 'working',
                'summary': 'Tests pass', 'evidence': 'ci run 12', 'updated_at': '2026-01-03T00:00:00Z',
                'prompt': 'PRIVATE-PROMPT', 'assistant_response': 'PRIVATE-ANSWER'}],
            'lifecycle': {'history': [{'id': 8, 'task_id': 1, 'actor_member_id': 'm1',
                'action': 'claim_task', 'summary': 'Agent claimed the task',
                'created_at': '2026-01-02T00:00:00Z', 'context': {'tool_input': 'PRIVATE-TOOL'}}]},
            'requests': [{'id': 7, 'task_id': 1, 'sender_member_id': 'm1',
                'receiver_member_id': 'm2', 'created_at': '2026-01-01T00:00:00Z',
                'read_at': None, 'processed_at': None, 'resolved_at': None,
                'body': 'PRIVATE-REQUEST', 'replies': [{'author_member_id': 'm2',
                    'created_at': '2026-01-04T00:00:00Z', 'body': 'PRIVATE-REPLY'}]}],
            'transcript': 'PRIVATE-TRANSCRIPT',
            'tool_result': 'PRIVATE-TOOL-RESULT',
        }
        feed = project_activity(snapshot)
        encoded = json.dumps(feed)
        self.assertEqual([item['type'] for item in feed['items']],
                         ['reply_sent', 'progress_reported', 'claim_task', 'request_sent'])
        self.assertIn('Tests pass', encoded)
        for secret in ('PRIVATE-PROMPT', 'PRIVATE-ANSWER', 'PRIVATE-REQUEST', 'PRIVATE-REPLY',
                       'PRIVATE-TRANSCRIPT', 'PRIVATE-TOOL', 'PRIVATE-TOOL-RESULT', 'ci run 12'):
            self.assertNotIn(secret, encoded)

    def test_activity_page_is_bounded_and_reports_truncation(self):
        snapshot = {'progress': [dict(task_id=index, member_id='m', state='working',
            summary='progress', evidence='', updated_at=f'2026-01-{1 + index // 24:02}T{index % 24:02}:00:00Z')
            for index in range(130)]}
        feed = project_activity(snapshot)
        self.assertEqual(len(feed['items']), 100)
        self.assertTrue(feed['truncated'])
        self.assertEqual(feed['items'][0]['task_id'], 129)

    def test_only_allowlisted_activity_properties_are_emitted(self):
        feed = project_activity({'git': {'deliveries': [{'task_id': 1, 'release_id': 42,
            'tag_name': 'v1.2.3', 'state': 'published', 'source': 'github_verified',
            'sync_at': '2026-01-02T00:00:00Z', 'url': 'https://github.com/acme/demo/releases/tag/v1.2.3',
            'body': 'PRIVATE-RELEASE-NOTES', 'transcript_path': 'PRIVATE-PATH'}]}})
        item = feed['items'][0]
        self.assertEqual(item['type'], 'release_verified')
        self.assertEqual(item['reference'], {'release_id': 42, 'tag_name': 'v1.2.3',
            'state': 'published', 'url': 'https://github.com/acme/demo/releases/tag/v1.2.3'})
        self.assertNotIn('body', item)
        self.assertNotIn('transcript_path', item)

    def test_local_git_observation_keeps_actor_task_and_safe_reference_fields(self):
        feed = project_activity({'git': {'events': [{'id': 12, 'member_id': 'member-7',
            'task_id': 5, 'branch': 'feature/release', 'head': 'a' * 40,
            'captured_at': '2026-01-02T00:00:00Z', 'tool_input': 'PRIVATE-INPUT'}]}})
        item = feed['items'][0]
        self.assertEqual(item['actor_member_id'], 'member-7')
        self.assertEqual(item['task_id'], 5)
        self.assertEqual(item['reference'], {'branch': 'feature/release', 'head': 'a' * 40})
        self.assertNotIn('PRIVATE-INPUT', json.dumps(item))

    def test_session_keys_and_noncanonical_github_hosts_are_not_shared(self):
        feed = project_activity({'sessions': [{'id': 8, 'session_key': 'PRIVATE-SESSION-KEY',
            'member_id': 'm1', 'tool': 'codex-cli', 'branch': 'main',
            'updated_at': '2026-01-02T00:00:00Z'}],
            'git': {'deliveries': [{'task_id': 1, 'release_id': 42, 'tag_name': 'v1.2.3',
                'state': 'published', 'source': 'github_verified', 'sync_at': '2026-01-03T00:00:00Z',
                'url': 'https://github.com.evil.test/acme/demo/releases/tag/v1.2.3'}]}})
        encoded = json.dumps(feed)
        self.assertNotIn('PRIVATE-SESSION-KEY', encoded)
        release = next(item for item in feed['items'] if item['type'] == 'release_verified')
        self.assertNotIn('url', release['reference'])

    def test_common_service_snapshot_exposes_activity_from_task_progress(self):
        evidence = Path('.local/test-evidence') / ('project-activity-' + uuid4().hex)
        evidence.mkdir(parents=True)
        service = CoordinationService(evidence / 'activity.sqlite3')
        owner = service.identity.create_room('Activity', 'Owner')
        task = service.tasks.create_task(owner['web_token'], 'activity-task', 'Release integration', 'src')
        claimed = service.tasks.claim_task(owner['agent_token'], task['id'])
        service.activity.report_progress(owner['agent_token'], task['id'], 'working', 'Release metadata verified')
        snapshot = service.snapshot(owner['web_token'])
        self.assertIn('activity', snapshot)
        self.assertTrue(any(item['task_id'] == task['id'] and item['summary'] == 'Release metadata verified'
                            for item in snapshot['activity']['items']))


if __name__ == '__main__':
    unittest.main()
