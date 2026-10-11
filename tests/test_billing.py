"""Billing domain tests retain every SQLite database under ignored .local/."""
import importlib
import json
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from crewmesh.accounts import AccountStore
from crewmesh.errors import AccessDenied, Conflict, ValidationError
from crewmesh.identity import IdentityStore
from crewmesh.workspaces import WorkspaceStore


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('crewmesh.billing'), 'Billing domain must exist')
        self.module = importlib.import_module('crewmesh.billing')
        root = Path('.local/c2-domain-tests')
        root.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(root / (str(uuid4()) + '.sqlite'))
        self.accounts = AccountStore(self.identity)
        self.accounts.bootstrap('owner', 'long password 123')
        self.owner = self.accounts.login('owner', 'long password 123')['session_token']
        self.workspaces = WorkspaceStore(self.accounts)
        self.team = self.workspaces.create_team(self.owner, 'Team')['team_id']
        self.catalog = self.module.BillingCatalog(
            free_members=2, free_projects=1, team_members=5, team_projects=4,
            team_monthly_price_id='price_fixture', provider_mode='test')
        self.billing = self.module.BillingStore(self.workspaces, mode='cloud', catalog=self.catalog)

    def join(self, name='member', role='member'):
        invite = self.workspaces.create_invite(self.owner, self.team, role)
        account = self.workspaces.accept_invite(invite['invite_token'], username=name, password='long password 123')['account']
        return account['id'], self.accounts.login(name, 'long password 123')['session_token']

    def bind(self, team=None, customer='cus_fixture'):
        return self.billing.bind_customer(team or self.team, customer, provider_mode='test')

    def snapshot(self, **changes):
        values = dict(customer_id='cus_fixture', subscription_id='sub_fixture', price_id='price_fixture',
                      provider_mode='test', status='active', current_invoice_id='in_fixture',
                      paid_invoice_id='in_fixture', paid_period_end=int(datetime.now(timezone.utc).timestamp()) + 3600,
                      cancel_at_period_end=False, risk_hold=False)
        values.update(changes)
        return self.module.SubscriptionSnapshot(**values)

    def apply(self, **changes):
        self.bind()
        claim = self.billing.start_sync(self.team)
        self.assertTrue(self.billing.apply_snapshot(claim, self.snapshot(**changes)))

    def event(self, event_id='evt_fixture', **changes):
        values = dict(event_type='invoice.paid', object_id='in_fixture', customer_id='cus_fixture',
                      subscription_id='sub_fixture', provider_mode='test')
        values.update(changes)
        return self.billing.ingest_event(event_id, **values)

    def test_catalog_validates_explicit_configuration(self):
        for changes in ({'free_members': 0}, {'team_projects': True}, {'free_projects': '1'},
                        {'provider_mode': 'mixed'}, {'team_monthly_price_id': ''},
                        {'team_members': 1}, {'team_projects': 0}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                replace(self.catalog, **changes)
        with self.assertRaises(ValidationError):
            self.module.BillingStore(self.workspaces, mode='trial', catalog=self.catalog)

    def test_unconfigured_and_self_hosted_are_unlimited_never_paid(self):
        for mode, catalog in [('cloud', None), ('self-hosted', self.catalog)]:
            self.billing = self.module.BillingStore(self.workspaces, mode=mode, catalog=catalog)
            for n in range(3):
                self.workspaces.create_project(self.owner, self.team, f'{mode}{n}')
            summary = self.billing.summary(self.owner, self.team)
            self.assertFalse(summary['enabled'])
            self.assertFalse(summary['paid'])
            self.assertEqual('unlimited', summary['plan'])
            self.assertEqual({'members': None, 'projects': None}, summary['limits'])
            with self.assertRaises(Conflict):
                self.bind()

    def test_summary_authorization_and_owner_only_management(self):
        _, admin = self.join(role='admin')
        self.bind()
        summary = self.billing.summary(admin, self.team)
        self.assertEqual({'members': 2, 'projects': 0}, summary['usage'])
        self.assertNotIn('billing', summary)
        self.assertEqual('cus_fixture', self.billing.summary(self.owner, self.team)['billing']['customer_id'])
        with self.assertRaises(AccessDenied):
            self.billing.require_owner(admin, self.team)
        other = self.workspaces.create_team(self.owner, 'other')['team_id']
        for method in (self.billing.summary, self.billing.require_owner):
            with self.assertRaises(AccessDenied):
                method(admin, other)
        self.assertEqual(self.accounts.authenticate(self.owner)['id'], self.billing.require_owner(self.owner, self.team)['id'])

    def test_role_change_and_membership_removal_take_effect_immediately(self):
        successor, session = self.join(role='owner')
        self.workspaces.change_role(session, self.team, self.accounts.authenticate(self.owner)['id'], 'member')
        with self.assertRaises(AccessDenied):
            self.billing.require_owner(self.owner, self.team)
        self.workspaces.remove_member(session, self.team, self.accounts.authenticate(self.owner)['id'])
        with self.assertRaises(AccessDenied):
            self.billing.summary(self.owner, self.team)

    def test_project_last_slot_concurrency(self):
        def create(n):
            try:
                self.workspaces.create_project(self.owner, self.team, f'project {n}')
                return True
            except Conflict:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([False, True], sorted(pool.map(create, range(2))))
        with self.accounts.db.connect() as c:
            self.assertEqual(1, c.execute('SELECT count(*) FROM rooms').fetchone()[0])
        self.assertEqual(1, self.billing.summary(self.owner, self.team)['usage']['projects'])

    def test_member_last_slot_concurrency_rolls_back_invite_and_account(self):
        invitations = [self.workspaces.create_invite(self.owner, self.team, role) for role in ('admin', 'owner')]
        def accept(n):
            try:
                self.workspaces.accept_invite(invitations[n]['invite_token'], username=f'new{n}', password='long password 123')
                return True
            except Conflict:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([False, True], sorted(pool.map(accept, range(2))))
        with self.accounts.db.connect() as c:
            self.assertEqual(2, c.execute('SELECT count(*) FROM accounts').fetchone()[0])
            self.assertEqual(1, c.execute('SELECT count(*) FROM team_invitations WHERE used_at IS NULL').fetchone()[0])

    def test_reactivation_checks_members_and_failed_invite_remains_usable(self):
        member, session = self.join()
        self.workspaces.remove_member(self.owner, self.team, member)
        replacement, _ = self.join('replacement')
        invite = self.workspaces.create_invite(self.owner, self.team)
        with self.assertRaises(Conflict):
            self.workspaces.accept_invite(invite['invite_token'], session_token=session)
        self.workspaces.remove_member(self.owner, self.team, replacement)
        self.workspaces.accept_invite(invite['invite_token'], session_token=session)
        self.assertEqual(2, self.billing.summary(self.owner, self.team)['usage']['members'])

    def test_legacy_claim_cannot_bypass_project_limit(self):
        self.workspaces.create_project(self.owner, self.team, 'full')
        old = self.identity.create_room('legacy', 'owner')
        with self.assertRaises(Conflict):
            self.workspaces.claim_legacy_project(self.owner, self.team, old['web_token'])
        self.identity.authenticate(old['web_token'])
        with self.accounts.db.connect() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM team_projects WHERE room_id=?', (old['room_id'],)).fetchone())

    def test_paid_policy_requires_current_paid_invoice_and_expiry(self):
        self.apply(cancel_at_period_end=True)
        self.assertEqual('team', self.billing.summary(self.owner, self.team)['plan'])
        for changes in ({'status': 'past_due'}, {'status': 'canceled'}, {'status': 'paused'},
                        {'paid_invoice_id': 'in_old'}, {'current_invoice_id': None},
                        {'paid_period_end': 1}, {'risk_hold': True}, {'price_id': 'price_other'}):
            with self.subTest(changes=changes):
                self.apply(**changes)
                self.assertEqual('free', self.billing.summary(self.owner, self.team)['plan'])

    def test_expiry_rechecked_without_event(self):
        self.apply()
        with self.accounts.db.connect(write=True) as c:
            c.execute('UPDATE billing_subscriptions SET paid_period_end=1')
        self.assertFalse(self.billing.summary(self.owner, self.team)['paid'])

    def test_paid_entitlement_requires_customer_and_subscription_bindings(self):
        self.apply()
        with self.accounts.db.connect(write=True) as c:
            c.execute('UPDATE billing_subscriptions SET customer_id=?', ('cus_unbound',))
        self.assertEqual('free', self.billing.summary(self.owner, self.team)['plan'])
        self.apply()
        with self.accounts.db.connect(write=True) as c:
            c.execute("UPDATE billing_teams SET provider_mode='live'")
            c.execute("UPDATE billing_subscription_bindings SET provider_mode='live'")
        self.assertEqual('free', self.billing.summary(self.owner, self.team)['plan'])
        with self.accounts.db.connect(write=True) as c:
            c.execute("UPDATE billing_teams SET provider_mode='test'")
            c.execute("UPDATE billing_subscription_bindings SET provider_mode='test'")
        with self.accounts.db.connect(write=True) as c:
            c.execute('UPDATE billing_subscriptions SET subscription_id=?', ('sub_unbound',))
        self.assertEqual('free', self.billing.summary(self.owner, self.team)['plan'])

    def test_downgrade_preserves_projects_credentials_and_members(self):
        self.apply()
        rooms = [self.workspaces.create_project(self.owner, self.team, str(n))['room_id'] for n in range(3)]
        self.join('one')
        self.join('two')
        web = self.workspaces.project_credential(self.owner, rooms[0])['web_token']
        self.apply(status='canceled')
        self.assertEqual(3, len(self.workspaces.list_projects(self.owner, self.team)))
        self.identity.authenticate(web)
        self.assertEqual({'members': True, 'projects': True}, self.billing.summary(self.owner, self.team)['over_limit'])
        with self.assertRaises(Conflict):
            self.workspaces.create_project(self.owner, self.team, 'blocked')
        with self.assertRaises(Conflict):
            self.join('blocked')

    def test_additive_migration_preserves_existing_team_and_is_repeatable(self):
        self.module.BillingStore(self.workspaces, mode='self-hosted')
        room = self.workspaces.create_project(self.owner, self.team, 'existing')['room_id']
        self.join()
        self.join('extra')
        for _ in range(2):
            self.billing = self.module.BillingStore(self.workspaces, mode='cloud', catalog=self.catalog)
        self.assertEqual(room, self.workspaces.list_projects(self.owner, self.team)[0]['room_id'])
        self.assertEqual(3, self.billing.summary(self.owner, self.team)['usage']['members'])

    def test_customer_idempotency_binding_mode_and_cross_team_guards(self):
        before = self.billing.customer_state(self.team)
        reopened = self.module.BillingStore(self.workspaces, mode='cloud', catalog=self.catalog)
        self.assertEqual(before, reopened.customer_state(self.team))
        self.bind()
        self.bind()
        with self.assertRaises(Conflict):
            self.bind(customer='cus_other')
        other = self.workspaces.create_team(self.owner, 'other')['team_id']
        with self.assertRaises(Conflict):
            self.bind(team=other)
        with self.assertRaises(ValidationError):
            self.billing.bind_customer(other, 'cus_live', provider_mode='live')
        with self.assertRaises(AccessDenied):
            self.billing.customer_state('unknown-team')
        self.assertEqual(self.team, self.billing.team_for_customer('cus_fixture', provider_mode='test'))

    def test_existing_only_checkout_refresh_never_creates_after_other_process_resolves(self):
        self.bind()
        self.assertIsNone(self.billing.reserve_checkout(self.team,refresh=True,existing_only=True))
        attempt=self.billing.reserve_checkout(self.team)
        self.assertTrue(self.billing.update_checkout(attempt,status='expired',checkout_id='cs_fixture'))
        self.assertIsNone(self.billing.reserve_checkout(self.team,refresh=True,existing_only=True))
        with self.billing.db.connect() as c:
            self.assertEqual(1,c.execute('SELECT COUNT(*) FROM billing_checkouts').fetchone()[0])
        self.apply()
        self.assertIsNone(self.billing.reserve_checkout(self.team,refresh=True,existing_only=True))

    def test_checkout_provider_opaque_fragment_persists_only_for_exact_host(self):
        self.bind();attempt=self.billing.reserve_checkout(self.team)
        url='https://checkout.stripe.com/c/pay/cs_test_fixture#fidkdWxOYHwn'
        self.assertTrue(self.billing.update_checkout(attempt,status='open',checkout_id='cs_fixture',
            checkout_url=url,expires_at=int(datetime.now(timezone.utc).timestamp())+3600))
        with self.billing.db.connect() as c:
            self.assertEqual(url,c.execute('SELECT checkout_url FROM billing_checkouts').fetchone()[0])
        for bad in ['https://other.example/c#opaque','https://checkout.stripe.com.evil/c#opaque',
                'https://checkout.stripe.com:444/c#opaque','https://user@checkout.stripe.com/c#opaque',
                'https://checkout.stripe.com/c#op aque','https://checkout.stripe.com/c#opaque\n']:
            with self.subTest(url=bad),self.assertRaises(ValidationError):
                self.billing.update_checkout(attempt,status='open',checkout_id='cs_fixture',checkout_url=bad,expires_at=1)

    def test_checkout_storage_rejects_raw_backslash_and_other_host_bare_fragment(self):
        self.bind();attempt=self.billing.reserve_checkout(self.team)
        for url in [r'https://checkout.stripe.com/c\pay#opaque',
                r'https://checkout.stripe.com/c/pay#opaque\suffix',
                'https://billing.stripe.com/p/session#','https://other.example/path#']:
            with self.subTest(url=url),self.assertRaises(ValidationError):
                self.billing.update_checkout(attempt,status='open',checkout_id='cs_fixture',
                    checkout_url=url,expires_at=2000000000)
        url='https://checkout.stripe.com:443/c/pay#opaque'
        self.assertTrue(self.billing.update_checkout(attempt,status='open',checkout_id='cs_fixture',
            checkout_url=url,expires_at=2000000000))
        with self.billing.db.connect() as c:
            self.assertEqual(url,c.execute('SELECT checkout_url FROM billing_checkouts').fetchone()[0])

    def test_checkout_has_one_unresolved_attempt_and_durable_lease(self):
        self.bind()
        with ThreadPoolExecutor(max_workers=2) as pool:
            reservations = list(pool.map(lambda _: self.billing.reserve_checkout(self.team), range(2)))
        self.assertEqual([False, True], sorted(x.claimed for x in reservations))
        self.assertEqual(1, len({x.idempotency_key for x in reservations}))
        first = next(x for x in reservations if x.claimed)
        reopened = self.module.BillingStore(self.workspaces, mode='cloud', catalog=self.catalog)
        self.assertFalse(reopened.reserve_checkout(self.team).claimed)
        with self.accounts.db.connect(write=True) as c:
            c.execute('UPDATE billing_checkouts SET lease_until=0')
        recovered = reopened.reserve_checkout(self.team)
        self.assertTrue(recovered.claimed)
        self.assertEqual(first.idempotency_key, recovered.idempotency_key)
        self.assertFalse(self.billing.update_checkout(first, status='open', checkout_id='cs_stale', checkout_url='https://checkout.stripe.com/stale', expires_at=2000000000))
        self.assertTrue(reopened.update_checkout(recovered, status='open', checkout_id='cs_fixture', checkout_url='https://checkout.stripe.com/fixture', expires_at=2000000000))
        self.assertFalse(reopened.reserve_checkout(self.team).claimed)
        self.assertEqual('https://checkout.stripe.com/fixture', reopened.reserve_checkout(self.team).checkout_url)

    def test_checkout_completed_waits_for_subscription_confirmation(self):
        self.bind()
        claim = self.billing.reserve_checkout(self.team)
        self.assertTrue(self.billing.update_checkout(claim, status='complete', checkout_id='cs_fixture', subscription_id='sub_fixture'))
        self.assertFalse(self.billing.reserve_checkout(self.team).claimed)
        self.assertEqual('free', self.billing.summary(self.owner, self.team)['plan'])
        self.apply()
        with self.accounts.db.connect() as c:
            self.assertEqual('confirmed', c.execute('SELECT status FROM billing_checkouts').fetchone()[0])
        with self.assertRaises(Conflict):
            self.billing.reserve_checkout(self.team)

    def test_checkout_cannot_bind_another_teams_subscription(self):
        self.apply()
        other = self.workspaces.create_team(self.owner, 'other')['team_id']
        self.bind(team=other, customer='cus_other')
        claim = self.billing.reserve_checkout(other)
        with self.assertRaises(Conflict):
            self.billing.update_checkout(claim, status='complete', checkout_id='cs_other', subscription_id='sub_fixture')
        with self.accounts.db.connect() as c:
            self.assertEqual('pending', c.execute('SELECT status FROM billing_checkouts WHERE team_id=?', (other,)).fetchone()[0])

    def test_snapshot_first_checkout_can_be_retrieved_and_completed_without_second_sync(self):
        self.bind()
        checkout = self.billing.reserve_checkout(self.team)
        self.billing.update_checkout(checkout, status='open', checkout_id='cs_fixture',
                                     checkout_url='https://checkout.stripe.com/fixture', expires_at=2000000000)
        self.apply()
        recovered = self.billing.reserve_checkout(self.team, refresh=True)
        self.assertTrue(recovered.claimed)
        self.assertEqual(checkout.attempt_id, recovered.attempt_id)
        self.assertEqual(checkout.idempotency_key, recovered.idempotency_key)
        self.assertTrue(self.billing.update_checkout(recovered, status='complete', checkout_id='cs_fixture',
                                                    subscription_id='sub_fixture'))
        with self.accounts.db.connect() as c:
            self.assertEqual('confirmed', c.execute('SELECT status FROM billing_checkouts').fetchone()[0])
        with self.assertRaises(Conflict):
            self.billing.reserve_checkout(self.team, refresh=True)

    def test_snapshot_first_incomplete_subscription_confirms_checkout_without_paid_grant(self):
        self.bind()
        checkout = self.billing.reserve_checkout(self.team)
        self.apply(status='incomplete', current_invoice_id=None, paid_invoice_id=None, paid_period_end=None)
        self.assertTrue(self.billing.update_checkout(checkout, status='complete', checkout_id='cs_fixture',
                                                    subscription_id='sub_fixture'))
        with self.accounts.db.connect() as c:
            self.assertEqual('confirmed', c.execute('SELECT status FROM billing_checkouts').fetchone()[0])
        self.assertEqual('free', self.billing.summary(self.owner, self.team)['plan'])

    def test_checkout_completion_racing_snapshot_always_converges_to_confirmed(self):
        from threading import Barrier
        self.bind()
        checkout = self.billing.reserve_checkout(self.team)
        sync = self.billing.start_sync(self.team)
        barrier = Barrier(2)
        def complete():
            barrier.wait()
            return self.billing.update_checkout(checkout, status='complete', checkout_id='cs_fixture',
                                                subscription_id='sub_fixture')
        def reconcile():
            barrier.wait()
            return self.billing.apply_snapshot(sync, self.snapshot())
        with ThreadPoolExecutor(max_workers=2) as pool:
            done = pool.submit(complete)
            applied = pool.submit(reconcile)
            self.assertTrue(done.result())
            self.assertTrue(applied.result())
        with self.accounts.db.connect() as c:
            self.assertEqual('confirmed', c.execute('SELECT status FROM billing_checkouts').fetchone()[0])

    def test_checkout_expiry_requires_provider_confirmed_terminal_state(self):
        self.bind()
        claim = self.billing.reserve_checkout(self.team)
        self.billing.update_checkout(claim, status='open', checkout_id='cs_fixture', checkout_url='https://checkout.stripe.com/fixture', expires_at=1)
        recovered = self.billing.reserve_checkout(self.team)
        self.assertTrue(recovered.claimed)
        self.assertEqual(claim.idempotency_key, recovered.idempotency_key)
        self.assertEqual('cs_fixture', recovered.checkout_id)
        self.billing.update_checkout(recovered, status='expired', checkout_id='cs_fixture')
        fresh = self.billing.reserve_checkout(self.team)
        self.assertTrue(fresh.claimed)
        self.assertNotEqual(claim.idempotency_key, fresh.idempotency_key)

    def test_event_dedup_persistence_retry_and_processing_only_after_apply(self):
        self.bind()
        self.assertTrue(self.event())
        self.assertFalse(self.event())
        job = self.billing.claim_job()
        self.assertIsNotNone(job)
        self.assertIsNone(self.billing.claim_job())
        self.assertTrue(self.billing.retry_job(job, 'provider_unavailable', retry_delay=0))
        reopened = self.module.BillingStore(self.workspaces, mode='cloud', catalog=self.catalog)
        retry = reopened.claim_job()
        self.assertEqual(2, retry.attempts)
        self.assertFalse(reopened.retry_job(job, 'late_error', retry_delay=0))
        sync = reopened.start_sync(self.team, job=retry)
        self.assertEqual('processing', reopened.event_state('evt_fixture')['state'])
        self.assertTrue(reopened.apply_snapshot(sync, self.snapshot()))
        self.assertEqual('processed', reopened.event_state('evt_fixture')['state'])
        self.assertIsNone(reopened.claim_job())

    def test_stale_sync_and_expired_event_leases_cannot_apply(self):
        self.bind()
        old = self.billing.start_sync(self.team)
        new = self.billing.start_sync(self.team)
        self.assertTrue(self.billing.apply_snapshot(new, self.snapshot(status='canceled')))
        self.assertFalse(self.billing.apply_snapshot(old, self.snapshot()))
        self.assertEqual('free', self.billing.summary(self.owner, self.team)['plan'])
        self.event()
        job = self.billing.claim_job()
        sync = self.billing.start_sync(self.team, job=job)
        with self.accounts.db.connect(write=True) as c:
            c.execute('UPDATE billing_events SET lease_until=0')
        self.assertFalse(self.billing.apply_snapshot(sync, self.snapshot()))
        self.assertEqual('processing', self.billing.event_state('evt_fixture')['state'])
        self.assertIsNotNone(self.billing.claim_job())

    def test_cross_customer_snapshot_and_event_cannot_change_entitlement(self):
        self.bind()
        other = self.workspaces.create_team(self.owner, 'other')['team_id']
        self.bind(team=other, customer='cus_other')
        claim = self.billing.start_sync(other)
        with self.assertRaises(Conflict):
            self.billing.apply_snapshot(claim, self.snapshot())
        self.event()
        job = self.billing.claim_job()
        with self.assertRaises(Conflict):
            self.billing.start_sync(other, job=job)
        claim = self.billing.start_sync(self.team)
        with self.assertRaises(ValidationError):
            self.billing.apply_snapshot(claim, self.snapshot(provider_mode='live'))

    def test_subscription_binding_cannot_switch_while_current_nonterminal(self):
        self.apply()
        claim = self.billing.start_sync(self.team)
        with self.assertRaises(Conflict):
            self.billing.apply_snapshot(claim, self.snapshot(subscription_id='sub_other'))
        self.apply(status='canceled')
        self.apply(subscription_id='sub_other')
        self.assertEqual('sub_other', self.billing.summary(self.owner, self.team)['billing']['subscription_id'])

    def test_unknown_verified_event_can_be_ignored_and_payload_is_minimal(self):
        self.assertTrue(self.event(event_type='unhandled.event', customer_id=None, subscription_id=None))
        job = self.billing.claim_job()
        self.assertTrue(self.billing.ignore_job(job, 'unsupported_event'))
        state = self.billing.event_state('evt_fixture')
        self.assertEqual('ignored', state['state'])
        self.assertIsNone(self.billing.claim_job())
        with self.assertRaises(ValidationError):
            self.event('evt_bad', object_id='sensitive\nraw body')
        with self.assertRaises(ValidationError):
            self.event('evt_live', provider_mode='live')
        with self.assertRaises(ValidationError):
            self.snapshot(risk_hold='false')

    def test_sync_failure_retains_verified_state_and_records_safe_error(self):
        self.apply()
        self.event()
        job = self.billing.claim_job()
        self.billing.start_sync(self.team, job=job)
        self.billing.retry_job(job, 'network_timeout', retry_delay=0)
        self.assertEqual('team', self.billing.summary(self.owner, self.team)['plan'])
        self.assertEqual('network_timeout', self.billing.event_state('evt_fixture')['last_error'])
        with self.assertRaises(ValidationError):
            self.billing.retry_job(job, 'secret full provider error text', retry_delay=0)

    def test_adapter_snapshot_read_and_bounded_team_inventory(self):
        self.assertTrue(callable(getattr(self.billing, 'current_snapshot', None)), 'Adapter snapshot read must exist')
        self.assertIsNone(self.billing.current_snapshot(self.team))
        self.apply()
        self.assertEqual('sub_fixture', self.billing.current_snapshot(self.team).subscription_id)
        other = self.workspaces.create_team(self.owner, 'other')['team_id']
        self.bind(team=other, customer='cus_other')
        self.workspaces.create_team(self.owner, 'unbound')
        first = self.billing.list_bound_teams(limit=1)
        second = self.billing.list_bound_teams(limit=1, after_team_id=first[0]['team_id'])
        self.assertEqual(sorted([self.team, other]), [first[0]['team_id'], second[0]['team_id']])
        self.assertEqual([], self.billing.list_bound_teams(after_team_id=second[0]['team_id']))
        for limit in (0, 1001, True):
            with self.assertRaises(ValidationError):
                self.billing.list_bound_teams(limit=limit)

    def test_manual_sync_failure_preserves_snapshot_and_stale_failure_is_rejected(self):
        self.assertTrue(callable(getattr(self.billing, 'fail_sync', None)), 'Generation-guarded failure recording must exist')
        self.apply()
        old = self.billing.start_sync(self.team)
        current = self.billing.start_sync(self.team)
        self.assertFalse(self.billing.fail_sync(old, 'old_timeout'))
        with self.assertRaises(ValidationError):
            self.billing.fail_sync(current, 'raw provider message containing secret')
        self.assertTrue(self.billing.fail_sync(current, 'network_timeout'))
        self.assertEqual('network_timeout', self.billing.summary(self.owner, self.team)['billing']['last_error'])
        self.assertEqual('team', self.billing.summary(self.owner, self.team)['plan'])
        self.assertFalse(self.billing.apply_snapshot(current, self.snapshot(status='canceled')))
        next_claim = self.billing.start_sync(self.team)
        self.assertTrue(self.billing.apply_snapshot(next_claim, self.snapshot()))
        self.assertIsNone(self.billing.summary(self.owner, self.team)['billing']['last_error'])

    def test_event_sync_failure_atomically_retries_and_expired_failure_cannot_write(self):
        self.assertTrue(callable(getattr(self.billing, 'fail_sync', None)), 'Generation-guarded failure recording must exist')
        self.apply()
        self.event()
        job = self.billing.claim_job()
        claim = self.billing.start_sync(self.team, job=job)
        self.assertTrue(self.billing.fail_sync(claim, 'network_timeout', retry_delay=0))
        self.assertEqual('pending', self.billing.event_state(job.event_id)['state'])
        retry = self.billing.claim_job()
        current = self.billing.start_sync(self.team, job=retry)
        with self.accounts.db.connect(write=True) as c:
            c.execute('UPDATE billing_teams SET sync_until=0')
        self.assertFalse(self.billing.fail_sync(current, 'late_timeout'))
        self.assertEqual('processing', self.billing.event_state(job.event_id)['state'])
        self.assertEqual('network_timeout', self.billing.summary(self.owner, self.team)['billing']['last_error'])

    def test_event_lookup_retry_cannot_overwrite_newer_manual_sync_success(self):
        self.apply()
        self.event()
        initial_job = self.billing.claim_job()
        initial_sync = self.billing.start_sync(self.team, job=initial_job)
        self.assertTrue(self.billing.fail_sync(initial_sync, 'network_timeout', retry_delay=0))
        retry = self.billing.claim_job()
        newer_sync = self.billing.start_sync(self.team)
        self.assertTrue(self.billing.apply_snapshot(newer_sync, self.snapshot()))
        self.assertTrue(self.billing.retry_job(retry, 'late_lookup_timeout', retry_delay=0))
        summary = self.billing.summary(self.owner, self.team)
        self.assertIsNone(summary['billing']['last_error'])
        self.assertEqual('team', summary['plan'])
        event = self.billing.event_state(retry.event_id)
        self.assertEqual('pending', event['state'])
        self.assertEqual('late_lookup_timeout', event['last_error'])

    def test_claims_and_reconciliation_survive_fresh_process(self):
        self.bind()
        customer = self.billing.customer_state(self.team)
        checkout = self.billing.reserve_checkout(self.team)
        self.event()
        job = self.billing.claim_job()
        old_sync = self.billing.start_sync(self.team, job=job)
        with self.accounts.db.connect(write=True) as c:
            c.execute('UPDATE billing_checkouts SET lease_until=0')
            c.execute('UPDATE billing_events SET lease_until=0')
        script = '''
import json, sys
from dataclasses import asdict
from crewmesh.identity import IdentityStore
from crewmesh.accounts import AccountStore
from crewmesh.workspaces import WorkspaceStore
from crewmesh.billing import BillingStore, BillingCatalog, SubscriptionSnapshot
b = BillingStore(WorkspaceStore(AccountStore(IdentityStore(sys.argv[1]))), 'cloud', BillingCatalog(**json.loads(sys.argv[3])))
r = b.reserve_checkout(sys.argv[2])
assert b.update_checkout(r, status='complete', checkout_id='cs_recovered', subscription_id='sub_fixture')
j = b.claim_job()
s = b.start_sync(sys.argv[2], job=j)
assert b.apply_snapshot(s, SubscriptionSnapshot(**json.loads(sys.argv[4])))
print(json.dumps({'customer': b.customer_state(sys.argv[2]), 'key': r.idempotency_key, 'attempts': j.attempts, 'generation': s.generation}))
'''
        from dataclasses import asdict
        recovered = json.loads(subprocess.check_output([sys.executable, '-c', script, str(self.accounts.db.path),
                                self.team, json.dumps(asdict(self.catalog)), json.dumps(asdict(self.snapshot()))], text=True))
        self.assertEqual(customer, recovered['customer'])
        self.assertEqual(checkout.idempotency_key, recovered['key'])
        self.assertEqual(2, recovered['attempts'])
        self.assertGreater(recovered['generation'], old_sync.generation)
        self.assertFalse(self.billing.apply_snapshot(old_sync, self.snapshot(status='canceled')))
        self.assertFalse(self.billing.update_checkout(checkout, status='expired', checkout_id='cs_recovered'))
        self.assertEqual('processed', self.billing.event_state(job.event_id)['state'])
        self.assertEqual('team', self.billing.summary(self.owner, self.team)['plan'])


if __name__ == '__main__':
    unittest.main()
