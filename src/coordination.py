"""Shared collaboration service independent of transport and account hosting."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .identity import IdentityStore
from .tasks import TaskStore
from .activity import ActivityStore
from .messages import MessageStore
from .contracts import ContractStore
from .protocol import fields, validate


class CoordinationService:
    def __init__(self, database_path, github_app=None):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(path)
        self.tasks = TaskStore(self.identity)
        from .task_lifecycle import TaskLifecycleStore, ACTIONS
        self.lifecycle = TaskLifecycleStore(self.identity)
        from .dependencies import DependencyStore, schemas as dependency_schemas
        self.dependencies = DependencyStore(self.identity)
        self.activity = ActivityStore(self.identity)
        self.messages = MessageStore(self.identity)
        self.contracts = ContractStore(self.identity)
        from .checkpoints import CheckpointStore
        self.checkpoints = CheckpointStore(self.identity)
        from .repositories import RepositoryStore
        self.repositories = RepositoryStore(self.identity)
        from .github_app import GitHubApp
        from .github_sync import GitHubSync
        self.github = GitHubSync(self.identity, self.repositories, github_app or GitHubApp())
        from .events import EventStore
        self.change_events = EventStore(self.identity)
        from .wake_digest import WakeDigest
        self.wake = WakeDigest(self.identity)
        self.operations = {
            'wake_digest': ('agent', self.wake.digest, fields()),
            'checkpoint': ('agent', self.checkpoints.checkpoint, fields('session_key tool event', {'task_id': None, 'ownership_epoch': None})),
            'diagnostic_start': ('agent', self.checkpoints.diagnostic_start, fields('challenge')),
            'diagnostic_read': ('agent', self.checkpoints.diagnostic_read, fields('diagnostic_id')),
            'diagnostic_complete': ('agent', self.checkpoints.diagnostic_complete, fields('diagnostic_id proof')),
            'create_room': (None, self.identity.create_room, fields('name owner_name', {'repository': ''})),
            'join': (None, self.identity.join_invite, fields('invite_token display_name')),
            'invite': ('web', self.identity.create_invite, fields('', {'hours': 1})),
            'revoke_invite': ('web', self.identity.revoke_invite, fields('invite_token')),
            'revoke_member': ('web', self.identity.revoke_member, fields('member_id')),
            'rotate_agent': ('web', self.identity.rotate_agent, fields()),
            'connect_agent': ('web', self.identity.connect_agent, fields()),
            'create_task': ('web', self.tasks.create_task, fields('intent_key title scope')),
            'claim_task': ('agent', self.tasks.claim_task, fields('task_id', {'session_key': None})),
            'register_session': ('agent', self.activity.register_session, fields('session_key tool repository branch', {'task_id': None, 'ownership_epoch': None})),
            'report_progress': ('agent', self.activity.report_progress, fields('task_id state summary', {'evidence': '', 'session_key': None, 'ownership_epoch': None})),
            'send_request': ('agent', self.messages.send_request, fields('request_key context_version body', {'receiver_member_id': None, 'task_id': None})),
            'read_inbox': ('agent', self.messages.read_inbox, fields('', {'after_id': 0, 'limit': 50})),
            'acknowledge': ('agent', self.messages.acknowledge, fields('request_id')),
            'reply': ('agent', self.messages.reply, fields('request_id request_key context_version body', {'evidence': ''})),
            'resolve_request': ('any', self.messages.resolve_request, fields('request_id context_version')),
            'assign': ('web', self.messages.assign_receiver, fields('request_id receiver_member_id')),
            'propose_contract': ('agent', self.contracts.propose, fields('contract_key expected_version title body', {'source_request_id': None, 'commit_ref': ''})),
            'decision': ('web', self.contracts.decide, fields('contract_id version decision')),
            'bind_repository': ('web', self.repositories.bind_repository, fields('repository')),
            'observe_repository': ('agent', self.repositories.observe, {'task_id': (int, True, None), 'observation': (dict, True, None)}),
            'repo_checkpoint': ('agent', self.repo_checkpoint, {'task_id': (int, True, None), 'observation': (dict, True, None)}),
            'read_git_team': ('agent', lambda token: self.snapshot(token, web=False), fields()),
            'link_delivery': ('any', self.github.associate, {'task_id': (int, True, None),
                'branch': (str, False, ''), 'pr_number': (int, False, None), 'commit_sha': (str, False, ''),
                'release_id': (int, False, None)}),
        }
        for name, schema in dependency_schemas(fields).items():
            self.operations[name] = ('any', getattr(self.dependencies, name), schema)
        for action in ACTIONS:
            optional = {'session_key': None, 'ownership_epoch': None} if action in ('release_task', 'propose_handoff') else {}
            required = 'task_id expected_revision request_key summary'
            if action in ('propose_handoff', 'force_handoff'):
                required += ' target_member_id'
            self.operations[action] = ('any' if action in ('release_task', 'propose_handoff') else 'web',
                                       getattr(self.lifecycle, action), fields(required, optional))
        self.operations['read_task_history'] = ('any', self.lifecycle.read_task_history, fields('task_id', {'before_id':None,'limit':20}))
        for name in ('observe_repository', 'repo_checkpoint', 'link_delivery'):
            self.operations[name][2].update(fields('', {'session_key': None, 'ownership_epoch': None}))
        self.reads = {'tasks': self.tasks.list_tasks, 'sessions': self.activity.list_sessions,
                      'progress': self.activity.list_progress, 'overlaps': self.activity.overlaps,
                      'requests': self.messages.list_requests, 'contracts': self.contracts.list_contracts,
                      'events': self.contracts.list_events, 'members': self.identity.list_members}
        self.reads['git'] = self.git_snapshot
        self.reads['collaboration'] = self.checkpoints.snapshot
        self.reads['lifecycle'] = self.lifecycle.snapshot
        self.reads['dependencies'] = self.dependencies.snapshot

    def git_snapshot(self, token):
        result = self.repositories.snapshot(token)
        result.update(self.github.snapshot(token))
        result['github_configured'] = self.github.app.enabled
        return result

    def repo_checkpoint(self, token, task_id, observation, session_key=None, ownership_epoch=None):
        observed = self.repositories.observe(token, task_id, observation, session_key, ownership_epoch)
        return {'observation': observed, 'team': self.snapshot(token, web=False),
                'inbox': self.messages.read_inbox(token)}

    def me(self, token):
        return {'me': asdict(self.identity.authenticate(token)), 'room': self.identity.room_info(token)}

    def snapshot(self, token, *, web=True):
        self.identity.authenticate(token, required_kind='web' if web else 'agent')
        result = self.me(token)
        result.update({name: read(token) for name, read in self.reads.items()})
        from .project_activity import project_activity
        result['activity'] = project_activity(result)
        result['server_time'] = datetime.now(timezone.utc).isoformat()
        return result

    def call(self, operation, token, data):
        kind, method, schema = self.operations[operation]
        if kind:
            self.identity.authenticate(token, required_kind=None if kind == 'any' else kind)
        data = validate(dict(data) if isinstance(data, dict) else data, schema)
        return method(token, **data) if kind else method(**data)
