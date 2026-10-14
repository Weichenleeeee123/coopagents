"""Shared coordination behavior; all local test databases are retained."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from uuid import uuid4

from crewmesh.errors import AccessDenied, Conflict, NotFound, ValidationError


class CoordinationCoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('crewmesh.coordination'),
                             'Shared coordination module must exist')
        from crewmesh.coordination import CoordinationService
        self.path = Path('.local/test-evidence') / ('coordination-' + str(uuid4()) + '.sqlite3')
        self.service = CoordinationService(self.path)
        self.owner = self.service.call('create_room', None, {'name': 'Team', 'owner_name': 'Owner'})
        invite = self.service.call('invite', self.owner['web_token'], {})
        self.peer = self.service.call('join', None, {'invite_token': invite['invite_token'], 'display_name': 'Peer'})
        self.other = self.service.call('create_room', None, {'name': 'Other', 'owner_name': 'Other'})

    def task(self):
        return self.service.call('create_task', self.owner['web_token'],
                                 {'intent_key': 'task', 'title': 'Shared task', 'scope': 'src'})

    def test_core_import_and_construction_without_host_dependencies(self):
        isolated_path = self.path.with_name('isolated-' + str(uuid4()) + '.sqlite3')
        script = textwrap.dedent('''
            import importlib.abc
            import sys
            class BlockHostImports(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split('.')[0] in {'starlette', 'mcp'} or fullname in {
                        'crewmesh.api', 'crewmesh.accounts', 'crewmesh.workspaces', 'crewmesh.oauth'
                    } or fullname.startswith(('crewmesh.billing', 'crewmesh.stripe_billing')):
                        raise AssertionError('Host dependency imported: ' + fullname)
            sys.meta_path.insert(0, BlockHostImports())
            from crewmesh.coordination import CoordinationService
            from crewmesh.protocol import fields, validate
            service = CoordinationService(sys.argv[1])
            assert not hasattr(service, 'accounts')
            assert not hasattr(service, 'workspaces')
            owner = service.call('create_room', None, {'name': 'Independent', 'owner_name': 'Owner'})
            snapshot = service.snapshot(owner['agent_token'], web=False)
            assert snapshot['git']['github_configured'] is False
            assert service.github.app.enabled is False
            assert service.github.app._client is None
            assert validate({'task_id': 1}, fields('task_id')) == {'task_id': 1}
        ''')
        completed = subprocess.run([sys.executable, '-c', script, str(isolated_path)],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_creation_invite_join_and_task_contention(self):
        self.assertEqual(self.owner['room_id'], self.peer['room_id'])
        self.assertNotEqual(self.owner['member_id'], self.peer['member_id'])
        task = self.task()
        claim = self.service.call('claim_task', self.owner['agent_token'], {'task_id': task['id']})
        self.assertEqual(claim['owner_member_id'], self.owner['member_id'])
        with self.assertRaises(Conflict) as failure:
            self.service.call('claim_task', self.peer['agent_token'], {'task_id': task['id']})
        self.assertEqual(failure.exception.owner_member_id, self.owner['member_id'])

    def test_cross_space_isolation(self):
        task = self.task()
        self.assertEqual(self.service.snapshot(self.other['web_token'])['tasks'], [])
        with self.assertRaises(NotFound):
            self.service.call('claim_task', self.other['agent_token'], {'task_id': task['id']})
        with self.assertRaises(NotFound):
            self.service.call('send_request', self.other['agent_token'], {
                'request_key': 'foreign', 'context_version': 1, 'body': 'Foreign',
                'receiver_member_id': self.peer['member_id']})

    def test_agent_cannot_perform_management(self):
        for operation, data in (
            ('invite', {}), ('rotate_agent', {}), ('connect_agent', {}),
            ('create_task', {'intent_key': 'denied', 'title': 'Denied', 'scope': 'src'}),
            ('bind_repository', {'repository': 'https://github.com/example/project'}),
            ('decision', {'contract_id': 1, 'version': 1, 'decision': 'approved'}),
        ):
            with self.subTest(operation=operation), self.assertRaises(AccessDenied):
                self.service.call(operation, self.owner['agent_token'], data)
        with self.assertRaises(AccessDenied):
            self.service.snapshot(self.owner['agent_token'])

    def test_message_read_is_separate_from_processing_and_resolution(self):
        request = self.service.call('send_request', self.owner['agent_token'], {
            'request_key': 'request', 'context_version': 1, 'body': 'Coordinate',
            'receiver_member_id': self.peer['member_id']})
        before = self.service.snapshot(self.owner['web_token'])['requests'][0]
        self.assertIsNone(before['read_at'])
        read = self.service.call('read_inbox', self.peer['agent_token'], {})['requests'][0]
        self.assertEqual(read['id'], request['id'])
        self.assertIsNotNone(read['read_at'])
        self.assertIsNone(read['processed_at'])
        self.assertIsNone(read['resolved_at'])
        self.assertEqual(read['replies'], [])

    def test_api_composes_shared_core_and_preserves_function_identity(self):
        from crewmesh.api import Service, fields, validate
        from crewmesh.coordination import CoordinationService
        from crewmesh.protocol import fields as core_fields, validate as core_validate
        from crewmesh.accounts import AccountStore
        from crewmesh.workspaces import WorkspaceStore
        hosted = Service(self.path.with_name('hosted-' + str(uuid4()) + '.sqlite3'))
        self.assertIsInstance(hosted, CoordinationService)
        self.assertIsInstance(hosted.accounts, AccountStore)
        self.assertIsInstance(hosted.workspaces, WorkspaceStore)
        self.assertIs(fields, core_fields)
        self.assertIs(validate, core_validate)
        for method in ('call', 'snapshot', 'git_snapshot', 'repo_checkpoint', 'me'):
            self.assertIs(getattr(Service, method), getattr(CoordinationService, method))
        self.assertEqual(set(hosted.operations), set(self.service.operations))
        self.assertEqual(set(hosted.reads), set(self.service.reads))
        for name in hosted.operations:
            self.assertEqual(hosted.operations[name][0], self.service.operations[name][0])
            self.assertEqual(hosted.operations[name][2], self.service.operations[name][2])
        owner = hosted.call('create_room', None, {'name': 'Hosted', 'owner_name': 'Owner'})
        view = hosted.snapshot(owner['web_token'])
        self.assertEqual(set(view), set(self.service.snapshot(self.owner['web_token'])))
        self.assertEqual(view['git'], self.service.snapshot(self.owner['web_token'])['git'])

    def test_shared_validation_retains_strict_types_defaults_and_unicode(self):
        from crewmesh.protocol import fields, validate
        schema = fields('task_id title', {'ownership_epoch': None, 'evidence': ''})
        self.assertEqual(validate({'task_id': 1, 'title': 'T'}, schema),
                         {'task_id': 1, 'title': 'T', 'ownership_epoch': None, 'evidence': ''})
        for payload in ([], {'task_id': True, 'title': 'T'}, {'task_id': 1},
                        {'task_id': 1, 'title': '\ud800'}, {'task_id': 1, 'title': 'T', 'unknown': 1}):
            with self.subTest(payload=repr(payload)), self.assertRaises(ValidationError):
                validate(payload, schema)


if __name__ == '__main__':
    unittest.main()
