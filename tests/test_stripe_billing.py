"""Stripe fixtures only: no account, credentials, or external network."""
import importlib
import hashlib
import hmac
import json
import time
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4


class StripeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.stripe_billing'), 'Stripe adapter must exist')
        self.s = importlib.import_module('coopagents.stripe_billing')

    def signed(self, body, stamp=None, secret='whsec_fixture'):
        stamp = int(time.time()) if stamp is None else stamp
        mac = hmac.new(secret.encode(), str(stamp).encode() + b'.' + body, hashlib.sha256).hexdigest()
        return f't={stamp},v1={mac}'

    def event(self, **changes):
        values = dict(id='evt_fixture', type='invoice.paid', livemode=False,
                      data={'object': {'id': 'in_fixture'}})
        values.update(changes)
        return json.dumps(values, separators=(',', ':')).encode()

    def test_authenticates_original_bytes_and_rotated_signatures(self):
        raw = self.event()
        header = self.signed(raw) + ',v1=' + '0' * 64
        event = self.s.verify_event(raw, header, 'whsec_fixture', 'test')
        self.assertEqual({'event_id': 'evt_fixture', 'event_type': 'invoice.paid',
                          'object_id': 'in_fixture', 'provider_mode': 'test'}, event)
        with self.assertRaises(self.s.StripeError):
            self.s.verify_event(raw + b' ', header, 'whsec_fixture', 'test')

    def test_rejects_duplicate_timestamps_stale_future_malformed_json_mode_and_ids(self):
        now = int(time.time())
        raw = self.event()
        for header in [self.signed(raw, now-301), self.signed(raw, now+301),
                       self.signed(raw) + f',t={now}', 't=1.0,v1='+'0'*64,
                       self.signed(raw)+',bad', self.signed(raw)+',t=01']:
            with self.subTest(header=header), self.assertRaises(self.s.StripeError):
                self.s.verify_event(raw, header, 'whsec_fixture', 'test', now=now)
        for raw in [b'{', b'{"id":"evt_a","id":"evt_b"}', self.event(livemode=0),
                    self.event(livemode=True), self.event(id='evil'),
                    self.event(data={'object': {'id': 'cus_wrong'}})]:
            with self.subTest(raw=raw), self.assertRaises(self.s.StripeError):
                self.s.verify_event(raw, self.signed(raw), 'whsec_fixture', 'test')

    def test_client_pins_version_and_encodes_persistent_key_no_secret_errors(self):
        calls = []
        def transport(method, url, headers, body, timeout, max_bytes):
            calls.append((method, url, headers, body, timeout, max_bytes))
            return 200, json.dumps({'id':'cus_fixture','object':'customer','livemode':False}).encode()
        client = self.s.StripeClient('sk_test_fixture', 'test', transport=transport)
        self.assertEqual('cus_fixture', client.create_customer('server_key','team_a')['id'])
        self.assertEqual('2026-09-30.endive', calls[0][2]['Stripe-Version'])
        self.assertEqual('server_key', calls[0][2]['Idempotency-Key'])
        self.assertNotIn('sk_test_fixture', repr(client))
        self.assertIn(b'metadata%5Bcustomer_key%5D=server_key', calls[0][3])
        for status, body in [(302,b'{}'), (401,b'{"error":"sk_test_fixture"}'),
                             (200,b'x'*1048577), (200,b'{"id":"cus_a","id":"cus_b"}'),
                             (200,b'{"id":"cus_a","object":"customer","livemode":true}')]:
            client = self.s.StripeClient('sk_test_fixture','test',transport=lambda *args:(status,body))
            with self.subTest(status=status), self.assertRaises(self.s.StripeError) as error:
                client.retrieve_customer('cus_a')
            self.assertNotIn('sk_test_fixture', str(error.exception))

    def test_network_exceptions_are_classified(self):
        def transport(*args):
            raise TimeoutError('sk_test_fixture')
        client = self.s.StripeClient('sk_test_fixture','test',transport=transport)
        with self.assertRaises(self.s.StripeError) as error:
            client.retrieve_customer('cus_a')
        self.assertEqual('provider_unavailable', error.exception.code)
        self.assertNotIn('sk_test_fixture', str(error.exception))

    def test_strict_price_verification_and_urls(self):
        price = dict(id='price_fixture',object='price',livemode=False,active=True,
                     unit_amount=1900,currency='usd',billing_scheme='per_unit',type='recurring',
                     recurring={'interval':'month','interval_count':1,'usage_type':'licensed'})
        client = self.s.StripeClient('sk_test_fixture','test',transport=lambda *args:(200,json.dumps(price).encode()))
        self.assertEqual({'amount':1900,'currency':'usd','interval':'month'}, client.verify_price('price_fixture'))
        for change in [dict(active=False),dict(unit_amount=0),dict(unit_amount=True),dict(currency='USD'),
                       dict(billing_scheme='tiered'),dict(livemode=1),dict(id='price_other'),
                       dict(recurring={'interval':'year','interval_count':1,'usage_type':'licensed'}),
                       dict(recurring={'interval':'month','interval_count':2,'usage_type':'licensed'}),
                       dict(recurring={'interval':'month','interval_count':1,'usage_type':'metered'})]:
            bad = price | change
            client = self.s.StripeClient('sk_test_fixture','test',transport=lambda *args:(200,json.dumps(bad).encode()))
            with self.subTest(change=change), self.assertRaises(self.s.StripeError):
                client.verify_price('price_fixture')
        for url in ['http://checkout.stripe.com/a','https://checkout.stripe.com.evil/a',
                    'https://user@checkout.stripe.com/a','https://checkout.stripe.com:444/a',
                    'https://checkout.stripe.com/a\n']:
            with self.assertRaises(self.s.StripeError):
                self.s.hosted_url(url, 'checkout.stripe.com')

    def test_official_checkout_fragment_is_opaque_preserved_and_host_restrictions_remain(self):
        url='https://checkout.stripe.com/c/pay/cs_test_fixture#fidkdWxOYHwnPyd1blppbHNgWjA0'
        self.assertEqual(url,self.s.hosted_url(url,'checkout.stripe.com'))
        self.assertEqual(url.replace('.com/','.com:443/'),self.s.hosted_url(url.replace('.com/','.com:443/'),'checkout.stripe.com'))
        for bad in ['https://checkout.stripe.com.evil/c#opaque','https://user@checkout.stripe.com/c#opaque',
                'https://checkout.stripe.com:444/c#opaque','https://checkout.stripe.com/c#opaque\n',
                'https://checkout.stripe.com/c#op aque','https://billing.stripe.com/c#opaque']:
            with self.subTest(url=bad),self.assertRaises(self.s.StripeError):
                self.s.hosted_url(bad,'billing.stripe.com' if 'billing.stripe.com' in bad else 'checkout.stripe.com')

    def test_hosted_urls_reject_raw_backslash_and_portal_bare_fragment(self):
        for host,url in [('billing.stripe.com','https://billing.stripe.com/p/session#'),
                ('billing.stripe.com',r'https://billing.stripe.com/p\session'),
                ('checkout.stripe.com',r'https://checkout.stripe.com/c\pay#opaque'),
                ('checkout.stripe.com',r'https://checkout.stripe.com/c/pay?token=a\b'),
                ('checkout.stripe.com',r'https://checkout.stripe.com/c/pay#opaque\suffix')]:
            with self.subTest(url=url):
                with self.assertRaises(self.s.StripeError) as error:self.s.hosted_url(url,host)
                self.assertEqual('invalid_provider_url',error.exception.code)
        for url in ['https://checkout.stripe.com:443/c/pay#opaque','https://checkout.stripe.com/c/pay#']:
            self.assertEqual(url,self.s.hosted_url(url,'checkout.stripe.com'))

    def test_legacy_checkout_call_verifies_base_currency_inside_shared_budget_and_authorization(self):
        calls=[];guards=[]
        price=dict(id='price_fixture',object='price',livemode=False,active=True,unit_amount=1900,
            currency='usd',billing_scheme='per_unit',type='recurring',
            recurring=dict(interval='month',interval_count=1,usage_type='licensed'))
        def transport(method,url,headers,body,timeout,max_bytes):
            calls.append((method,url,body))
            obj=price if method=='GET' else dict(id='cs_fixture',object='checkout.session',livemode=False)
            return 200,json.dumps(obj).encode()
        client=self.s.StripeClient('sk_test_fixture','test',transport=transport,max_requests=1)
        with self.assertRaises(self.s.StripeError) as error:
            client.create_checkout('cus_fixture','price_fixture','persistent_key','attempt','https://coopagents.example')
        self.assertEqual('operation_budget',error.exception.code)
        self.assertEqual(['GET'],[call[0] for call in calls])
        calls.clear();client=self.s.StripeClient('sk_test_fixture','test',transport=transport)
        with client.operation(lambda:guards.append('checked')):
            client.create_checkout('cus_fixture','price_fixture','persistent_key','attempt','https://coopagents.example')
        self.assertEqual(['GET','POST'],[call[0] for call in calls]);self.assertEqual(2,len(guards))
        self.assertIn(b'currency=usd',calls[1][2]);self.assertIn(b'adaptive_pricing%5Benabled%5D=false',calls[1][2])

    def test_pagination_is_bounded_and_validates_modes(self):
        client = self.s.StripeClient('sk_test_fixture','test', max_pages=2,
            transport=lambda *args:(200,json.dumps({'object':'list','data':[{'id':'sub_a','object':'subscription','livemode':False}], 'has_more':True}).encode()))
        with self.assertRaises(self.s.StripeError) as error:
            client.list_subscriptions('cus_a')
        self.assertEqual('pagination_incomplete', error.exception.code)

    def test_https_close_delimited_body_updates_original_socket_deadline(self):
        deadlines=[]
        class Socket:
            def settimeout(self,value):deadlines.append(value)
        socket=Socket()
        class Response:
            status=200
            def __init__(self):self.parts=[b'{}',b'']
            def read1(self,bound):return self.parts.pop(0)
            def close(self):pass
        class Connection:
            def __init__(self,*args,**kwargs):self.sock=socket
            def connect(self):pass
            def request(self,*args,**kwargs):pass
            def getresponse(self):self.sock=None;return Response()
            def close(self):pass
        with patch.object(self.s.http.client,'HTTPSConnection',Connection):
            self.assertEqual((200,b'{}'),self.s.https_transport('GET','https://api.stripe.com/v1/customers',{},None,5,100))
        self.assertGreaterEqual(len(deadlines),3)
        self.assertTrue(all(0<value<=5 for value in deadlines))

    def test_entire_operation_budget_counts_paginated_requests(self):
        client=self.s.StripeClient('sk_test_fixture','test',max_requests=1,
            transport=lambda *args:(200,json.dumps({'object':'list','data':[{'id':'sub_a','object':'subscription','livemode':False}], 'has_more':True}).encode()))
        with client.operation(),self.assertRaises(self.s.StripeError) as error:
            client.list_subscriptions('cus_a')
        self.assertEqual('operation_budget',error.exception.code)

    def test_canonical_lookup_metadata_malformed_is_classified(self):
        client=self.s.StripeClient('sk_test_fixture','test',transport=lambda *args:(200,json.dumps(
            {'object':'list','has_more':False,'data':[{'id':'cus_fixture','object':'customer','livemode':False,'metadata':None}]}).encode()))
        with self.assertRaises(self.s.StripeError):client.find_customer('persisted_key','team_fixture')

    def test_production_caller_deadline_covers_slow_dns_headers_and_bounds_threads(self):
        self.assertTrue(hasattr(self.s,'_https_request'),'Physical I/O helper must exist for deadline seam')
        entered=threading.Event();release=threading.Event();finished=threading.Event();calls=[]
        def physical(*args):
            calls.append(args);entered.set();release.wait(2);finished.set();return 200,b'{}'
        with patch.object(self.s,'_https_request',physical),patch.object(self.s,'_transport_slots',threading.BoundedSemaphore(1)):
            started=time.monotonic()
            with self.assertRaises(self.s.StripeError) as error:
                self.s.https_transport('GET','https://api.stripe.com/v1/customers',{},None,0.03,100)
            self.assertEqual('provider_unavailable',error.exception.code)
            self.assertLess(time.monotonic()-started,0.5);self.assertTrue(entered.is_set())
            with self.assertRaises(self.s.StripeError) as error:
                self.s.https_transport('GET','https://api.stripe.com/v1/customers',{},None,0.03,100)
            self.assertEqual('provider_busy',error.exception.code);self.assertEqual(1,len(calls))
            release.set();self.assertTrue(finished.wait(1))

    def test_response_owned_socket_closed_after_oversize(self):
        closed=[]
        class Socket:
            def settimeout(self,value):pass
        class Response:
            status=200
            def read1(self,bound):return b'x'*101
            def close(self):closed.append('response')
        class Connection:
            def __init__(self,*args,**kwargs):self.sock=Socket()
            def connect(self):pass
            def request(self,*args,**kwargs):pass
            def getresponse(self):self.sock=None;return Response()
            def close(self):closed.append('connection')
        with patch.object(self.s.http.client,'HTTPSConnection',Connection),self.assertRaises(self.s.StripeError):
            self.s.https_transport('GET','https://api.stripe.com/v1/customers',{},None,1,100)
        self.assertEqual(['response','connection'],closed)

    def test_owner_guard_rechecked_after_connection_delay_before_wire_request(self):
        from coopagents.errors import AccessDenied
        stages=[]
        class Connection:
            def __init__(self,*args,**kwargs):self.sock=None
            def connect(self):stages.append('connected')
            def request(self,*args,**kwargs):stages.append('request')
            def close(self):pass
        def authorize():
            if 'connected' in stages:raise AccessDenied('Team owner required for billing')
        client=self.s.StripeClient('sk_test_fixture','test')
        with patch.object(self.s.http.client,'HTTPSConnection',Connection),client.operation(authorize):
            with self.assertRaises(AccessDenied):client.retrieve_customer('cus_fixture')
        self.assertEqual(['connected'],stages)

    def test_malformed_checkout_line_item_is_classified(self):
        client=self.s.StripeClient('sk_test_fixture','test',transport=lambda *args:(200,json.dumps(
            {'object':'list','has_more':False,'data':[None]}).encode()))
        with self.assertRaises(self.s.StripeError):client.checkout_items('cs_fixture')


class BillingConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.billing_config'), 'Configuration module must exist')
        self.c = importlib.import_module('coopagents.billing_config')

    def environment(self):
        return dict(COOPAGENTS_BILLING_MODE='test',COOPAGENTS_STRIPE_SECRET_KEY='sk_test_fixture',
                    COOPAGENTS_STRIPE_WEBHOOK_SECRET='whsec_fixture',COOPAGENTS_TEAM_MONTHLY_PRICE_ID='price_fixture',
                    COOPAGENTS_FREE_MEMBERS='2',COOPAGENTS_FREE_PROJECTS='1',
                    COOPAGENTS_TEAM_MEMBERS='20',COOPAGENTS_TEAM_PROJECTS='10')

    def test_complete_absence_disabled_partial_invalid_and_selfhost_unlimited(self):
        self.assertFalse(self.c.load_billing_config('cloud',{}).enabled)
        self.assertFalse(self.c.load_billing_config('self-hosted',self.environment()).enabled)
        for env in [dict(COOPAGENTS_BILLING_MODE='test'), self.environment() | {'COOPAGENTS_FREE_MEMBERS':'0'},
                    self.environment() | {'COOPAGENTS_STRIPE_SECRET_KEY':'sk_live_wrong'},
                    self.environment() | {'COOPAGENTS_BILLING_MODE':'Test'}]:
            with self.assertRaises(ValueError):
                self.c.load_billing_config('cloud',env)
        config=self.c.load_billing_config('cloud',self.environment())
        self.assertTrue(config.enabled)
        self.assertEqual('price_fixture',config.catalog.team_monthly_price_id)
        self.assertNotIn('sk_test_fixture',repr(config))
        self.assertNotIn('whsec_fixture',repr(config))

    def test_secrets_from_bounded_files_mutually_exclusive(self):
        root=Path('.local/c2-stripe-tests');root.mkdir(parents=True,exist_ok=True)
        path=root/(str(uuid4())+'.secret');path.write_bytes(b'sk_test_fixture\n')
        env=self.environment();env.pop('COOPAGENTS_STRIPE_SECRET_KEY')
        env['COOPAGENTS_STRIPE_SECRET_KEY_FILE']=str(path)
        self.assertTrue(self.c.load_billing_config('cloud',env).enabled)
        env['COOPAGENTS_STRIPE_SECRET_KEY']='sk_test_fixture'
        with self.assertRaises(ValueError):self.c.load_billing_config('cloud',env)
        env.pop('COOPAGENTS_STRIPE_SECRET_KEY');path.write_bytes(b'a'*4097)
        with self.assertRaises(ValueError):self.c.load_billing_config('cloud',env)


if __name__ == '__main__':
    unittest.main()
