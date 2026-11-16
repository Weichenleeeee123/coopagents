"""Agreement reliance is explicit, approved-version and execution scoped."""
from pathlib import Path
import unittest
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError


class AgreementUsageTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('agreement-use-' + str(uuid4()) + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.a = self.s.identity.create_room('Project', 'Frontend')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Backend')
        task = self.s.tasks.create_task(self.a['web_token'], 'front', 'Frontend', 'src/ui')
        self.task = self.s.tasks.claim_task(self.a['agent_token'], task['id'], 'front')
        self.auth = dict(session_key='front', ownership_epoch=self.task['ownership_epoch'])
        self.contract = self.s.contracts.propose(self.b['agent_token'], 'pagination', 0, 'Pagination', 'Use cursor')

    def approve(self, version):
        return self.s.contracts.decide(self.a['web_token'], self.contract['id'], version, 'approved')

    def record(self, version=1, **extra):
        self.assertIn('record_agreement_use', self.s.operations, 'agreement reliance operation missing')
        args = dict(task_id=self.task['id'], contract_id=self.contract['id'], version=version, **self.auth)
        args.update(extra)
        return self.s.call('record_agreement_use', self.a['agent_token'], args)

    def impacts(self):
        with self.s.identity.db.connect() as db:
            p = self.s.identity.resolve(db, self.a['agent_token'])
            return self.s.agreement_usage.project(db, p, self.task['id'])

    def test_only_approved_versions_can_be_recorded_by_current_execution(self):
        with self.assertRaises(Conflict):
            self.record()
        self.approve(1)
        first = self.record()
        self.assertEqual(first['baseline_version'], 1)
        self.assertFalse(first['review_required'])
        self.assertEqual(self.record()['id'], first['id'])
        with self.assertRaises((Conflict, AccessDenied)):
            self.record(session_key='old')
        with self.assertRaises(AccessDenied):
            self.s.call('record_agreement_use', self.b['agent_token'], dict(task_id=self.task['id'],
                contract_id=self.contract['id'], version=1, **self.auth))
        with self.assertRaises(AccessDenied):
            self.s.call('record_agreement_use', self.a['web_token'], dict(task_id=self.task['id'],
                contract_id=self.contract['id'], version=1, **self.auth))

    def test_drafts_do_not_replace_effective_version_and_old_retries_cannot_downgrade(self):
        self.approve(1)
        self.record()
        self.s.contracts.propose(self.b['agent_token'], 'pagination', 1, 'Pagination', 'Use page')
        self.assertFalse(self.impacts()[0]['review_required'])
        self.approve(2)
        impact = self.impacts()[0]
        self.assertEqual((impact['baseline_version'], impact['effective_version']), (1, 2))
        self.assertTrue(impact['review_required'])
        self.assertEqual(self.record(2)['baseline_version'], 2)
        self.assertEqual(self.record(1)['baseline_version'], 2)
        self.assertFalse(self.impacts()[0]['review_required'])
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM task_agreement_uses').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM contract_decisions').fetchone()[0], 2)

    def test_room_isolation_and_retired_epoch(self):
        self.approve(1)
        self.record()
        other = self.s.identity.create_room('Other', 'Other')
        foreign = self.s.contracts.propose(other['agent_token'], 'c', 0, 'Other', 'Other')
        self.s.contracts.decide(other['web_token'], foreign['id'], 1, 'approved')
        with self.assertRaises(NotFound):
            self.record(contract_id=foreign['id'])
        changed = self.s.call('force_handoff', self.a['web_token'], dict(task_id=self.task['id'],
            expected_revision=self.task['revision'], request_key='move', summary='New owner',
            target_member_id=self.b['member_id']))
        self.s.tasks.claim_task(self.b['agent_token'], changed['id'], 'backend')
        self.assertEqual(self.impacts(), [])
        with self.assertRaises((Conflict, AccessDenied)):
            self.record()
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM task_agreement_uses').fetchone()[0], 1)

    def test_legacy_use_does_not_follow_a_new_execution_session(self):
        task = self.s.tasks.create_task(self.a['web_token'], 'legacy', 'Legacy', 'legacy')
        self.task = self.s.tasks.claim_task(self.a['agent_token'], task['id'])
        self.auth = {}
        self.approve(1)
        self.record()
        self.assertEqual(len(self.impacts()), 1)
        self.s.tasks.claim_task(self.a['agent_token'], task['id'], 'fresh')
        self.assertEqual(self.impacts(), [])

    def test_oversized_identifiers_are_validation_errors_before_sql_binding(self):
        self.approve(1)
        for data in (dict(contract_id=2**63), dict(version=2**63)):
            with self.subTest(field=next(iter(data))):
                with self.assertRaises(ValidationError):
                    self.record(**data)
