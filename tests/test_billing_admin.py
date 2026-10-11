"""Local maintenance never creates a database and uses canonical provider fixtures."""
import contextlib
import hashlib
import importlib
import io
import json
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from crewmesh.api import create_app
from crewmesh.billing import BillingCatalog
from crewmesh.billing_config import BillingConfig
from crewmesh.stripe_billing import StripeClient
from test_billing_service import FixtureTransport
from test_billing_api import CATALOG, CONFIG, ORIGIN, event, signature


class BillingAdminTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('crewmesh.billing_admin'), 'Existing-database recovery CLI must exist')
        self.admin = importlib.import_module('crewmesh.billing_admin')
        self.root = Path('.local/c2-admin-tests'); self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / (str(uuid4()) + '.sqlite3')
        self.transport = FixtureTransport()

    def fixture(self):
        app = create_app(self.database, mode='cloud', public_url=ORIGIN, billing_config=CONFIG)
        service = app.state.service
        account = service.accounts.oauth_account('github', '123', 'Owner')
        token = service.accounts.create_session(account['id'])['session_token']
        team = service.workspaces.create_team(token, 'Team')['team_id']
        service.billing.store.bind_customer(team, 'cus_fixture', provider_mode='test')
        self.transport.objects['/customers/cus_fixture'] = dict(id='cus_fixture', object='customer', livemode=False)
        self.transport.paid()
        return service, token, team

    def open(self, config=CONFIG):
        original = StripeClient.__init__
        def init(client, *args, **kwargs):
            kwargs['transport'] = self.transport
            original(client, *args, **kwargs)
        with patch.object(StripeClient, '__init__', init):
            return self.admin.open_billing(self.database, config, ORIGIN)

    def test_missing_and_unrelated_database_unchanged_no_provider_construction(self):
        with patch.object(StripeClient, '__init__', side_effect=AssertionError('No network setup')):
            with self.assertRaises(ValueError): self.open()
            self.assertFalse(self.database.exists())
            with contextlib.closing(sqlite3.connect(self.database)) as connection:
                connection.execute('CREATE TABLE unrelated(value TEXT)')
            before = self.database.read_bytes()
            with self.assertRaises(ValueError): self.open()
            self.assertEqual(before, self.database.read_bytes())

    def test_schema_and_catalog_rejected_before_mutation(self):
        self.fixture()
        before = self.database.read_bytes()
        config = BillingConfig(True, BillingCatalog(3, 2, 20, 10, 'price_fixture', 'test'), 'sk_test_fixture', 'whsec_fixture')
        with self.assertRaises(ValueError): self.open(config)
        self.assertEqual(before, self.database.read_bytes())
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute('ALTER TABLE billing_events RENAME COLUMN next_attempt TO unexpected')
            connection.commit()
        before = self.database.read_bytes()
        with self.assertRaises(ValueError): self.open()
        self.assertEqual(before, self.database.read_bytes())

    def test_connections_remain_existing_only_after_validation(self):
        self.fixture()
        billing = self.open()
        moved = self.database.with_suffix('.retained.sqlite3')
        self.database.rename(moved)
        with self.assertRaises(sqlite3.OperationalError):
            with billing.store.db.connect(write=True): pass
        self.assertFalse(self.database.exists())
        self.assertTrue(moved.exists())

    def test_bounded_retry_ignores_future_and_processes_durable_events(self):
        service, token, team = self.fixture()
        for index in range(3):
            service.billing.ingest_webhook(event('evt_admin_' + str(index)), signature(event('evt_admin_' + str(index))))
        billing = self.open()
        result = self.admin.retry(billing, max_jobs=2)
        self.assertEqual(result['attempted'], 2)
        states = [billing.store.event_state('evt_admin_' + str(index))['state'] for index in range(3)]
        self.assertEqual(states.count('processed'), 2)
        self.assertTrue(service.billing.store.summary(token, team)['paid'])
        self.transport.fail = lambda method, path: True
        result = self.admin.retry(billing, max_jobs=10)
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['failed'], 1)
        result = self.admin.retry(billing, max_jobs=10)
        self.assertEqual(result['attempted'], 0)
        self.assertFalse(any(method == 'POST' for method, *_ in self.transport.calls))

    def test_reconcile_existing_bindings_only_and_explicit_max(self):
        service, token, team = self.fixture()
        other = service.workspaces.create_team(token, 'Unbound')['team_id']
        billing = self.open()
        result = self.admin.reconcile(billing, max_teams=1)
        self.assertEqual(result, {'attempted': 1, 'succeeded': 1, 'failed': 0})
        self.assertTrue(service.billing.store.summary(token, team)['paid'])
        with billing.store.db.connect() as connection:
            self.assertIsNone(connection.execute('SELECT * FROM billing_teams WHERE team_id=?', (other,)).fetchone())
        self.assertFalse(any(method == 'POST' for method, *_ in self.transport.calls))

    def test_reconcile_keyset_pages_obey_global_bound(self):
        service, token, team = self.fixture()
        for index in range(101):
            other = service.workspaces.create_team(token, 'Bound ' + str(index))['team_id']
            customer = 'cus_page_' + str(index)
            service.billing.store.bind_customer(other, customer, provider_mode='test')
            self.transport.objects['/customers/' + customer] = dict(id=customer, object='customer', livemode=False)
        billing = self.open()
        result = self.admin.reconcile(billing, max_teams=101)
        self.assertEqual(result, {'attempted': 101, 'succeeded': 101, 'failed': 0})
        with billing.store.db.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM billing_subscriptions').fetchone()[0], 101)
            self.assertEqual(connection.execute('SELECT count(*) FROM billing_teams WHERE last_sync IS NULL').fetchone()[0], 1)
        self.assertFalse(any(method == 'POST' for method, *_ in self.transport.calls))

    def test_reconcile_expires_only_verified_saved_competing_checkout(self):
        service, token, team = self.fixture()
        service.billing.client.transport = self.transport
        self.transport.lists['/subscriptions'] = []
        service.billing.checkout(token, team)
        self.transport.paid()
        self.transport.calls.clear()
        billing = self.open()
        self.assertEqual(self.admin.reconcile(billing, max_teams=1)['succeeded'], 1)
        mutations = [(method, path) for method, path, *_ in self.transport.calls if method == 'POST']
        self.assertEqual(mutations, [('POST', '/checkout/sessions/cs_fixture/expire')])
        self.assertTrue(service.billing.store.summary(token, team)['paid'])

    def test_cli_safe_output_codes_and_no_provider_ids_or_secrets_in_arguments(self):
        self.fixture()
        billing = self.open()
        output, error = io.StringIO(), io.StringIO()
        with patch.object(self.admin, 'load_billing_config', return_value=CONFIG), patch.object(self.admin, 'open_billing', return_value=billing), patch.dict('os.environ', {'CREWMESH_PUBLIC_URL': ORIGIN}, clear=True), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            self.assertEqual(self.admin.main(['--database', str(self.database), 'reconcile', '--max-teams', '1']), 0)
            self.transport.fail = lambda method, path: True
            self.assertEqual(self.admin.main(['--database', str(self.database), 'reconcile', '--max-teams', '1']), 1)
        combined = output.getvalue() + error.getvalue()
        for value in ('cus_fixture', 'sub_fixture', 'sk_test_fixture', 'whsec_fixture', 'fixture timeout'):
            self.assertNotIn(value, combined)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            self.admin.main(['--database', str(self.database), 'retry', '--secret-key', 'forbidden'])
        self.assertEqual(failure.exception.code, 2)

    def test_reject_invalid_bounds_without_mutation(self):
        self.fixture(); billing = self.open(); before = self.database.read_bytes()
        for value in (0, -1, 1001, True):
            with self.assertRaises(ValueError): self.admin.retry(billing, max_jobs=value)
            with self.assertRaises(ValueError): self.admin.reconcile(billing, max_teams=value)
        self.assertEqual(before, self.database.read_bytes())
