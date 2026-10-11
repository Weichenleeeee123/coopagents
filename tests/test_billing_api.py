"""Billing HTTP boundaries using real random-port servers and retained SQLite evidence."""
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import socket
import secrets
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
import uvicorn
from crewmesh.api import create_app
from crewmesh.billing import BillingCatalog
from crewmesh.billing_config import BillingConfig
from crewmesh.stripe_billing import StripeClient
from test_billing_service import FixtureTransport

CATALOG = BillingCatalog(3, 1, 20, 10, 'price_fixture', 'test')
CONFIG = BillingConfig(True, CATALOG, 'sk_test_fixture', 'whsec_fixture')
ORIGIN = 'https://team.example'


def event(event_id='evt_http', kind='customer.subscription.updated', object_id='sub_fixture'):
    return json.dumps(dict(id=event_id, type=kind, livemode=False,
        data={'object': {'id': object_id, 'object': 'subscription', 'customer': 'cus_fixture'}})).encode()


def signature(raw):
    timestamp = str(int(time.time()))
    digest = hmac.new(b'whsec_fixture', timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return 't=' + timestamp + ',v1=' + digest


class BillingHTTP:
    def __init__(self, *, mode='cloud', config=CONFIG, database=None, transport=None):
        self.database = database or Path('.local/c2-http-tests') / (str(uuid4()) + '.sqlite3')
        self.transport = transport or FixtureTransport()
        original = StripeClient.__init__
        def initialize(client, *args, **kwargs):
            kwargs['transport'] = self.transport
            original(client, *args, **kwargs)
        with patch.object(StripeClient, '__init__', initialize):
            self.app = create_app(self.database, mode=mode, public_url=ORIGIN,
                bootstrap_secret=secrets.token_urlsafe(32), billing_config=config)
        self.service = self.app.state.service
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='critical', access_log=False,
            proxy_headers=False))
        self.thread = threading.Thread(target=lambda: self.server.run(sockets=[self.socket]), daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Fixture service did not start')
            time.sleep(.01)

    def close(self):
        self.server.should_exit = True
        self.thread.join(15)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError('Fixture service did not stop')

    def account(self, name='owner'):
        account = self.service.accounts.oauth_account('github', str(int(hashlib.sha256(name.encode()).hexdigest()[:10], 16)), name)
        return self.service.accounts.create_session(account['id'])

    def request(self, method, path, session=None, data=None, raw=None, headers=None, raw_response=False):
        values = [('Host', 'team.example')]
        if session:
            values += [('Cookie', 'crewmesh_account=' + session['session_token'])]
            if method == 'POST':
                values += [('Origin', ORIGIN), ('X-Crewmesh-CSRF', session['csrf_token'])]
        if data is not None:
            raw = json.dumps(data).encode()
            values += [('Content-Type', 'application/json')]
        if headers:
            # A list deliberately supports duplicate security headers.
            names = {name.lower() for name, _ in headers}
            values = [(name, value) for name, value in values if name.lower() not in names] + headers
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.putrequest(method, path, skip_host=True)
        for name, value in values:
            conn.putheader(name, value)
        conn.putheader('Content-Length', str(len(raw or b'')))
        conn.endheaders(raw)
        response = conn.getresponse()
        body = response.read()
        result = response.status, body if raw_response else (json.loads(body) if body else None), response.getheaders()
        conn.close()
        return result


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('Expected state not reached')
        time.sleep(.02)


class BillingAPITests(unittest.TestCase):
    def setUp(self):
        self.live = BillingHTTP()
        self.addCleanup(self.live.close)
        self.owner = self.live.account()
        self.team = self.live.service.workspaces.create_team(self.owner['session_token'], 'Team')['team_id']
        self.path = '/account/teams/' + self.team + '/billing'

    def test_summary_owner_and_strict_mutation(self):
        status, summary, _ = self.live.request('GET', self.path, self.owner)
        self.assertEqual(status, 200)
        self.assertEqual(summary['plan'], 'free')
        self.assertEqual(summary['price']['amount'], 1900)
        self.assertTrue(summary['checkout_available'])
        status, checkout, _ = self.live.request('POST', self.path + '/checkout', self.owner, {})
        self.assertEqual(status, 200)
        self.assertEqual(checkout['kind'], 'checkout')
        for data in ({'price_id': 'price_evil'}, [], None):
            raw = b'null' if data is None else None
            status, _, _ = self.live.request('POST', self.path + '/sync', self.owner, data, raw=raw,
                headers=[('Content-Type', 'application/json')])
            self.assertEqual(status, 400)
        self.assertEqual(self.live.request('POST', self.path + '/portal', self.owner, {})[0], 200)
        self.assertEqual(self.live.request('POST', self.path + '/sync', self.owner, {})[0], 200)

    def test_cookie_origin_csrf_and_role_denial_preserves_sessions(self):
        for headers, status in (([('Authorization', 'Bearer irrelevant')], 401),
            ([('Cookie', 'crewmesh_account=x; crewmesh_account=y')], 401),
            ([('Origin', 'https://foreign.example')], 403),
            ([('X-Crewmesh-CSRF', 'wrong')], 401),
            ([('Origin', ORIGIN), ('Origin', ORIGIN)], 403),
            ([('X-Crewmesh-CSRF', self.owner['csrf_token']), ('X-Crewmesh-CSRF', self.owner['csrf_token'])], 401)):
            session = None if headers[0][0] == 'Authorization' else self.owner
            self.assertEqual(self.live.request('POST', self.path + '/checkout', session, {}, headers=headers)[0], status)
        for role in ('member', 'admin'):
            account = self.live.account(role)
            invite = self.live.service.workspaces.create_invite(self.owner['session_token'], self.team, role)
            self.live.service.workspaces.accept_invite(invite['invite_token'], session_token=account['session_token'])
            status, summary, _ = self.live.request('GET', self.path, account)
            self.assertEqual(status, 200)
            self.assertNotIn('billing', summary)
            for suffix in ('checkout', 'portal', 'sync'):
                status, _, headers = self.live.request('POST', self.path + '/' + suffix, account, {})
                self.assertEqual(status, 401)
                self.assertFalse(any(name.lower() == 'set-cookie' for name, _ in headers))
            self.assertEqual(self.live.request('GET', '/account/session', account)[0], 200)
        stranger = self.live.account('stranger')
        self.assertEqual(self.live.request('GET', self.path, stranger)[0], 401)

    def test_configured_cloud_enforces_workspace_quota_over_http(self):
        path = '/account/teams/' + self.team + '/projects'
        self.assertEqual(self.live.request('POST', path, self.owner, {'name': 'First'})[0], 200)
        self.assertEqual(self.live.request('POST', path, self.owner, {'name': 'Second'})[0], 409)

    def test_foreign_provider_url_is_safe_typed_error(self):
        original = self.live.transport.__call__
        def foreign(*args):
            status, raw = original(*args)
            if args[0] == 'POST' and '/checkout/sessions' in args[1]:
                obj = json.loads(raw); obj['url'] = 'https://evil.example/secret'
                raw = json.dumps(obj).encode()
            return status, raw
        self.live.service.billing.client.transport = foreign
        status, body, _ = self.live.request('POST', self.path + '/checkout', self.owner, {})
        self.assertEqual(status, 503)
        self.assertEqual(body['error'], 'BillingUnavailable')
        self.assertNotIn('evil', json.dumps(body))

    def test_webhook_signature_before_json_and_boundary(self):
        path = '/billing/stripe/webhook'
        malformed = b'{private broken json'
        status, body, _ = self.live.request('POST', path, raw=malformed,
            headers=[('Stripe-Signature', 'wrong')])
        self.assertEqual(status, 400)
        self.assertEqual(body['code'], 'invalid_signature')
        self.assertEqual(self.live.request('POST', path, raw=malformed,
            headers=[('Stripe-Signature', signature(malformed))])[1]['code'], 'invalid_provider_json')
        raw = event()
        for headers, suffix, expected in (([('Stripe-Signature', signature(raw)), ('Stripe-Signature', signature(raw))], '', 400),
            ([('Stripe-Signature', signature(raw)), ('Host', 'foreign.example')], '', 400),
            ([('Stripe-Signature', signature(raw)), ('Origin', 'https://foreign.example')], '', 403),
            ([('Stripe-Signature', signature(raw))], '?x=y', 400)):
            self.assertEqual(self.live.request('POST', path + suffix, raw=raw, headers=headers)[0], expected)
        self.assertEqual(self.live.request('POST', path, raw=b'x' * 65537)[0], 413)
        self.assertEqual(self.live.request('POST', path + '/', raw=malformed)[1]['message'], 'Malformed JSON')

    def test_webhook_persists_before_ack_duplicates_and_unknown_ignore(self):
        self.live.service.billing.store.bind_customer(self.team, 'cus_fixture', provider_mode='test')
        self.live.transport.objects['/customers/cus_fixture'] = dict(id='cus_fixture', object='customer', livemode=False)
        self.live.transport.paid()
        entered, release = threading.Event(), threading.Event()
        def block(method, path):
            if path == '/subscriptions/sub_fixture':
                entered.set(); release.wait(8)
        self.live.transport.callback = block
        self.addCleanup(release.set)
        raw = event()
        try:
            status, _, _ = self.live.request('POST', '/billing/stripe/webhook', raw=raw,
                headers=[('Stripe-Signature', signature(raw))])
            self.assertEqual(status, 200)
            self.assertIsNotNone(self.live.service.billing.store.event_state('evt_http'))
            self.assertTrue(entered.wait(5))
            self.assertFalse(self.live.service.billing.store.summary(self.owner['session_token'], self.team)['paid'])
            self.assertEqual(self.live.request('POST', '/billing/stripe/webhook', raw=raw,
                headers=[('Stripe-Signature', signature(raw))])[0], 200)
            self.assertEqual(self.live.request('GET', '/health')[0], 200)
            self.assertEqual(self.live.request('GET', '/account/teams/' + self.team + '/projects', self.owner)[0], 200)
        finally:
            release.set()
        wait_for(lambda: self.live.service.billing.store.event_state('evt_http')['state'] == 'processed')
        raw = event('evt_irrelevant', 'product.updated', 'prod_fixture')
        self.assertEqual(self.live.request('POST', '/billing/stripe/webhook', raw=raw,
            headers=[('Stripe-Signature', signature(raw))])[0], 200)
        wait_for(lambda: self.live.service.billing.store.event_state('evt_irrelevant')['state'] == 'ignored')

    def test_valid_supported_webhook_for_unbound_customer_is_ignored(self):
        self.live.transport.objects['/customers/cus_fixture'] = dict(id='cus_fixture', object='customer', livemode=False)
        self.live.transport.paid()
        raw = event('evt_unrelated_customer')
        self.assertEqual(self.live.request('POST', '/billing/stripe/webhook', raw=raw,
            headers=[('Stripe-Signature', signature(raw))])[0], 200)
        wait_for(lambda: self.live.service.billing.store.event_state('evt_unrelated_customer')['state'] == 'ignored')
        self.assertFalse(self.live.service.billing.store.summary(self.owner['session_token'], self.team)['paid'])

    def test_billing_provider_capacity_does_not_starve_other_accounts(self):
        entered, release = threading.Event(), threading.Event()
        def block(method, path):
            if path == '/prices/price_fixture':
                entered.set(); release.wait(8)
        self.live.transport.callback = block
        threads = [threading.Thread(target=lambda: self.live.request('GET', self.path, self.owner)) for _ in range(2)]
        try:
            for thread in threads: thread.start()
            self.assertTrue(entered.wait(3))
            wait_for(lambda: len(self.live.transport.calls) >= 2)
            self.assertEqual(self.live.request('GET', self.path, self.owner)[0], 503)
            self.assertEqual(self.live.request('GET', '/health')[0], 200)
            self.assertEqual(self.live.request('GET', '/account/session', self.owner)[0], 200)
        finally:
            release.set()
            for thread in threads: thread.join(10)


class BillingConfigurationTests(unittest.TestCase):
    def test_disabled_modes_have_unlimited_no_client_or_webhook(self):
        for mode, config in (('self-hosted', CONFIG), ('cloud', None)):
            with patch.object(StripeClient, '__init__', side_effect=AssertionError('No provider client allowed')):
                live = BillingHTTP(mode=mode, config=config)
            try:
                owner = live.account()
                team = live.service.workspaces.create_team(owner['session_token'], 'Team')['team_id']
                status, body, _ = live.request('GET', '/account/teams/' + team + '/billing', owner)
                self.assertEqual(status, 200)
                self.assertEqual(body['plan'], 'unlimited')
                self.assertIsNone(body['limits']['projects'])
                self.assertFalse(live.service.billing.store.enabled)
                stranger = live.account('stranger')
                for suffix in ('checkout', 'portal', 'sync'):
                    path = '/account/teams/' + team + '/billing/' + suffix
                    self.assertEqual(live.request('POST', path, owner, {})[0], 409)
                    status, _, headers = live.request('POST', path, stranger, {})
                    self.assertEqual(status, 401)
                    self.assertFalse(any(name.lower() == 'set-cookie' for name, _ in headers))
                    self.assertEqual(live.request('POST', '/account/teams/missing/billing/' + suffix, owner, {})[0], 401)
                self.assertEqual(live.request('GET', '/account/session', stranger)[0], 200)
                # The absent route falls through the existing authenticated MCP mount.
                # Anonymous callers see its 401; an authenticated agent sees 404.
                self.assertFalse(any(getattr(route, 'path', None) == '/billing/stripe/webhook'
                                     for route in live.app.app.routes))
                self.assertEqual(live.request('POST', '/billing/stripe/webhook', data={})[0], 401)
                agent = live.service.identity.create_room('Webhook boundary', 'Agent owner')['agent_token']
                status, body, _ = live.request('POST', '/billing/stripe/webhook', data={},
                    headers=[('Authorization', 'Bearer ' + agent)], raw_response=True)
                self.assertEqual(status, 404)
                self.assertEqual(body, b'Not Found')
            finally: live.close()

    def test_enabled_requires_valid_direct_config_and_https_origin(self):
        for config, origin in ((CONFIG, None), (BillingConfig(True), ORIGIN),
            (BillingConfig(True, CATALOG, 'sk_live_wrong', 'whsec_fixture'), ORIGIN),
            (BillingConfig(True, CATALOG, 'sk_test_secret', 'bad_secret'), ORIGIN), (object(), ORIGIN)):
            database = Path('.local/c2-http-tests') / (str(uuid4()) + '.sqlite3')
            with self.subTest(config=config), self.assertRaises(ValueError):
                create_app(database, mode='cloud', billing_config=config, public_url=origin)
            self.assertFalse(database.exists())

class BillingRuntimeCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancellation_keeps_capacity_until_physical_completion(self):
        import asyncio
        from crewmesh.billing_api import BillingRuntime, BillingBusy
        runtime = BillingRuntime()
        release = threading.Event()
        entered = threading.Event()
        def block():
            entered.set(); release.wait(5)
        first = asyncio.create_task(runtime.execute(block))
        second = asyncio.create_task(runtime.execute(block))
        try:
            await asyncio.to_thread(entered.wait, 2)
            first.cancel(); await asyncio.sleep(.02)
            first.cancel(); await asyncio.sleep(.02)
            self.assertFalse(first.done(), 'Cancelled task must still own its blocking work')
            with self.assertRaises(BillingBusy):
                await runtime.execute(lambda: None)
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await runtime.close()

    async def test_cancelled_shutdown_waits_for_every_owned_pool(self):
        import asyncio
        from crewmesh.billing_api import BillingRuntime
        runtime = BillingRuntime()
        release_provider, release_ingestion = threading.Event(), threading.Event()
        entered_provider, entered_ingestion = threading.Event(), threading.Event()
        def provider(): entered_provider.set(); release_provider.wait(5)
        def ingest(): entered_ingestion.set(); release_ingestion.wait(5)
        provider_task = asyncio.create_task(runtime.execute(provider))
        ingest_task = asyncio.create_task(runtime.execute(ingest, ingestion=True))
        await asyncio.to_thread(entered_provider.wait, 2)
        await asyncio.to_thread(entered_ingestion.wait, 2)
        closing = asyncio.create_task(runtime.close())
        try:
            await asyncio.sleep(.02)
            closing.cancel(); await asyncio.sleep(.02)
            closing.cancel(); await asyncio.sleep(.02)
            release_provider.set()
            await asyncio.sleep(.1)
            self.assertFalse(closing.done(), 'Shutdown must still wait for ingestion after cancelled provider join')
        finally:
            release_provider.set(); release_ingestion.set()
            await asyncio.gather(provider_task, ingest_task, closing, return_exceptions=True)
            await runtime.close()

class BillingWorkerHTTPTests(unittest.TestCase):
    def fixture(self):
        live = BillingHTTP()
        owner = live.account()
        team = live.service.workspaces.create_team(owner['session_token'], 'Worker Team')['team_id']
        live.service.billing.store.bind_customer(team, 'cus_fixture', provider_mode='test')
        live.transport.objects['/customers/cus_fixture'] = dict(id='cus_fixture', object='customer', livemode=False)
        live.transport.paid()
        return live, owner, team

    def enqueue(self, live, event_id):
        raw = event(event_id)
        self.assertEqual(live.request('POST', '/billing/stripe/webhook', raw=raw,
            headers=[('Stripe-Signature', signature(raw))])[0], 200)

    def test_transient_failure_backoff_and_retry_after_restart(self):
        live, owner, team = self.fixture()
        transport, database = live.transport, live.database
        transport.fail = lambda method, path: True
        try:
            self.enqueue(live, 'evt_retry_restart')
            wait_for(lambda: live.service.billing.store.event_state('evt_retry_restart')['attempts'] == 1)
            wait_for(lambda: live.service.billing.store.event_state('evt_retry_restart')['state'] == 'pending')
            state = live.service.billing.store.event_state('evt_retry_restart')
            self.assertGreater(state['next_attempt'], int(time.time()))
            self.assertEqual(state['last_error'], 'provider_unavailable')
        finally: live.close()
        transport.fail = None
        with live.service.billing.store.db.connect(write=True) as connection:
            connection.execute("UPDATE billing_events SET next_attempt=0 WHERE event_id='evt_retry_restart'")
        fresh = BillingHTTP(database=database, transport=transport)
        try:
            wait_for(lambda: fresh.service.billing.store.event_state('evt_retry_restart')['state'] == 'processed')
            self.assertTrue(fresh.service.billing.store.summary(owner['session_token'], team)['paid'])
            self.assertEqual(fresh.service.billing.store.event_state('evt_retry_restart')['attempts'], 2)
        finally: fresh.close()

    def test_held_lease_survives_restart_until_expired_then_is_processed(self):
        live, owner, team = self.fixture()
        live.close()
        store = live.service.billing.store
        raw = event('evt_held_lease')
        live.service.billing.ingest_webhook(raw, signature(raw))
        job = store.claim_job(lease_seconds=120)
        self.assertIsNotNone(job)
        fresh = BillingHTTP(database=live.database, transport=live.transport)
        try:
            time.sleep(.4)
            self.assertEqual(store.event_state('evt_held_lease')['attempts'], 1)
            with store.db.connect(write=True) as connection:
                connection.execute("UPDATE billing_events SET lease_until=0 WHERE event_id='evt_held_lease'")
            wait_for(lambda: store.event_state('evt_held_lease')['state'] == 'processed')
            self.assertEqual(store.event_state('evt_held_lease')['attempts'], 2)
            self.assertTrue(store.summary(owner['session_token'], team)['paid'])
        finally: fresh.close()

    def test_unexpected_worker_failure_retains_lease_and_worker_stays_alive(self):
        from crewmesh.billing_service import BillingService
        live, _, _ = self.fixture()
        live.close()
        raw = event('evt_unexpected', 'product.updated', 'prod_fixture')
        live.service.billing.ingest_webhook(raw, signature(raw))
        original = BillingService.process_next
        calls = []
        def flaky(billing):
            if not calls:
                calls.append(True)
                billing.store.claim_job()
                raise RuntimeError('sk_test_SECRET private payload')
            return original(billing)
        with patch.object(BillingService, 'process_next', flaky), self.assertLogs('crewmesh.billing_worker', level='ERROR') as logs:
            fresh = BillingHTTP(database=live.database, transport=live.transport)
            try:
                wait_for(lambda: bool(calls))
                self.assertEqual(fresh.service.billing.store.event_state('evt_unexpected')['state'], 'processing')
                # An unrelated event proves the same owned worker continues.
                raw = event('evt_after_failure', 'product.updated', 'prod_other')
                fresh.service.billing.ingest_webhook(raw, signature(raw))
                wait_for(lambda: fresh.service.billing.store.event_state('evt_after_failure')['state'] == 'ignored')
                self.assertFalse(fresh.app.state.billing_worker.task.done())
                with fresh.service.billing.store.db.connect(write=True) as connection:
                    connection.execute("UPDATE billing_events SET lease_until=0 WHERE event_id='evt_unexpected'")
                wait_for(lambda: fresh.service.billing.store.event_state('evt_unexpected')['state'] == 'ignored')
            finally: fresh.close()
        self.assertNotIn('SECRET', '\n'.join(logs.output))
        self.assertNotIn('private payload', '\n'.join(logs.output))

    def test_shutdown_waits_for_owned_provider_work_and_no_later_writes(self):
        live, _, _ = self.fixture()
        entered, release = threading.Event(), threading.Event()
        def block(method, path):
            if path == '/subscriptions/sub_fixture':
                entered.set(); release.wait(8)
        live.transport.callback = block
        try:
            self.enqueue(live, 'evt_shutdown')
            self.assertTrue(entered.wait(5))
            live.server.should_exit = True
            time.sleep(.3)
            self.assertTrue(live.thread.is_alive())
            self.assertEqual(live.service.billing.store.event_state('evt_shutdown')['state'], 'processing')
        finally:
            release.set(); live.close()
        self.assertEqual(live.service.billing.store.event_state('evt_shutdown')['state'], 'processed')
        before = live.database.read_bytes()
        time.sleep(.3)
        self.assertEqual(before, live.database.read_bytes())
        self.assertFalse(live.thread.is_alive())

class BillingServerConfigurationTests(unittest.TestCase):
    def environment(self):
        return {'CREWMESH_MODE': 'cloud', 'CREWMESH_PUBLIC_URL': ORIGIN,
            'CREWMESH_BILLING_MODE': 'test', 'CREWMESH_STRIPE_SECRET_KEY': 'sk_test_fixture',
            'CREWMESH_STRIPE_WEBHOOK_SECRET': 'whsec_fixture', 'CREWMESH_TEAM_MONTHLY_PRICE_ID': 'price_fixture',
            'CREWMESH_FREE_MEMBERS': '3', 'CREWMESH_FREE_PROJECTS': '1',
            'CREWMESH_TEAM_MEMBERS': '20', 'CREWMESH_TEAM_PROJECTS': '10'}

    def test_server_loads_explicit_billing_only_when_enabled(self):
        from crewmesh.server import main
        env = self.environment()
        with patch.dict('os.environ', env, clear=True), patch('sys.argv', ['crewmesh']), patch('crewmesh.api.create_app', return_value='app') as create, patch('uvicorn.run') as run:
            main()
            self.assertEqual(create.call_args.kwargs['billing_config'], CONFIG)
            self.assertEqual(create.call_args.kwargs['mode'], 'cloud')
            run.assert_called_once()
        env = {'CREWMESH_MODE': 'cloud', 'CREWMESH_PUBLIC_URL': ORIGIN}
        with patch.dict('os.environ', env, clear=True), patch('sys.argv', ['crewmesh']), patch('crewmesh.api.create_app', return_value='app') as create, patch('uvicorn.run'):
            main()
            self.assertNotIn('billing_config', create.call_args.kwargs)

    def test_partial_cloud_configuration_fails_before_server_start(self):
        import io
        from crewmesh.server import main
        env = self.environment(); env.pop('CREWMESH_STRIPE_WEBHOOK_SECRET')
        with patch.dict('os.environ', env, clear=True), patch('sys.argv', ['crewmesh']), patch('sys.stderr', new_callable=io.StringIO) as error, patch('crewmesh.api.create_app') as create, patch('uvicorn.run') as run:
            with self.assertRaises(SystemExit) as failure: main()
            self.assertEqual(failure.exception.code, 2)
            create.assert_not_called(); run.assert_not_called()
            self.assertNotIn('sk_test_fixture', error.getvalue())

    def test_selfhost_ignores_billing_secret_files_and_create_app_never_reads_environment(self):
        from crewmesh.billing_config import load_billing_config
        env = self.environment(); env['CREWMESH_STRIPE_SECRET_KEY_FILE'] = 'C:/nonexistent-billing-secret'
        with patch.dict('os.environ', env, clear=True), patch('pathlib.Path.open', side_effect=AssertionError('Secret files must not be read')):
            self.assertFalse(load_billing_config('self-hosted').enabled)
        with patch.dict('os.environ', self.environment(), clear=True), patch.object(StripeClient, '__init__', side_effect=AssertionError('No implicit provider construction')):
            database = Path('.local/c2-http-tests') / (str(uuid4()) + '.sqlite3')
            app = create_app(database, mode='cloud', public_url=ORIGIN)
            self.assertFalse(app.state.service.billing.store.enabled)

class BillingProductionTransportShutdownTests(unittest.TestCase):
    def test_transport_timeout_joins_service_work_but_retains_bounded_daemon_and_late_dns_cannot_post(self):
        import crewmesh.stripe_billing as stripe
        entered, release = threading.Event(), threading.Event()
        connections, physical_threads, wire_requests = [], [], []
        fixture = FixtureTransport()
        price_body = json.dumps(fixture.price).encode()
        class Socket:
            def settimeout(self, value): pass
        class Response:
            status = 200
            def __init__(self): self.read = False
            def read1(self, bound):
                if self.read: return b''
                self.read = True; return price_body
            def close(self): pass
        class Connection:
            def __init__(self, *args, **kwargs):
                self.sock = Socket(); self.index = len(connections)
                connections.append(self)
            def connect(self):
                physical_threads.append(threading.current_thread())
                if self.index > 0:
                    entered.set(); release.wait(8)
            def request(self, method, path, **kwargs):
                wire_requests.append((method, path))
            def getresponse(self): return Response()
            def close(self): pass
        live = BillingHTTP()
        owner = live.account()
        team = live.service.workspaces.create_team(owner['session_token'], 'Timeout Team')['team_id']
        path = '/account/teams/' + team + '/billing/checkout'
        client = live.service.billing.client
        client.transport = stripe.https_transport
        client.timeout = .05
        with patch.object(stripe.http.client, 'HTTPSConnection', Connection), patch.object(stripe, '_transport_slots', threading.BoundedSemaphore(2)):
            try:
                self.assertEqual(live.request('POST', path, owner, {})[0], 503)
                self.assertTrue(entered.is_set())
                # A second slow DNS call fills the bounded physical capacity.
                with self.assertRaises(stripe.StripeError) as timeout:
                    stripe.https_transport('POST', 'https://api.stripe.com/v1/customers', {}, b'fixture', .05, 100)
                self.assertEqual(timeout.exception.code, 'provider_unavailable')
                with self.assertRaises(stripe.StripeError) as busy:
                    stripe.https_transport('POST', 'https://api.stripe.com/v1/customers', {}, b'fixture', .05, 100)
                self.assertEqual(busy.exception.code, 'provider_busy')
                self.assertEqual(len(connections), 3)
                residue = [thread for thread in physical_threads if thread.is_alive()]
                self.assertEqual(len(residue), 2)
                self.assertTrue(all(thread.daemon and thread.name == 'crewmesh-stripe' for thread in residue))
                # Owned service jobs have finished; shutdown must not wait for
                # an unbounded OS DNS resolution in a daemon transport helper.
                started = time.monotonic()
                live.close()
                self.assertLess(time.monotonic() - started, 3)
                self.assertTrue(all(thread.is_alive() for thread in residue))
                with live.service.billing.store.db.connect() as connection:
                    pending = dict(connection.execute("SELECT * FROM billing_outbound_operations WHERE purpose='customer'").fetchone())
                self.assertEqual(pending['state'], 'pending')
                before = live.database.read_bytes()
                release.set()
                for thread in physical_threads: thread.join(3)
                self.assertTrue(all(not thread.is_alive() for thread in physical_threads))
                self.assertEqual(wire_requests, [('GET', '/v1/prices/price_fixture')])
                self.assertEqual(before, live.database.read_bytes())
            finally:
                release.set()
                for thread in physical_threads: thread.join(3)
                live.close()
        # Restart uses the persisted idempotency key rather than inventing a
        # new key when the customer-create attempt had an uncertain outcome.
        fresh = BillingHTTP(database=live.database, transport=fixture)
        try:
            self.assertEqual(fresh.request('POST', path, owner, {})[0], 200)
            keys = [key for method, endpoint, key, _ in fixture.calls if method == 'POST' and endpoint == '/customers']
            self.assertEqual(keys, [pending['idempotency_key']])
        finally: fresh.close()
