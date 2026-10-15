"""Real SQLite coordinator plus canonical pinned Stripe transport fixtures."""
import importlib
import copy
import json
import hashlib
import hmac
import time
import threading
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from coopagents.accounts import AccountStore
from coopagents.billing import BillingCatalog, BillingStore
from coopagents.errors import AccessDenied, Conflict
from coopagents.identity import IdentityStore
from coopagents.workspaces import WorkspaceStore
from coopagents.stripe_billing import StripeClient, StripeError


class FixtureTransport:
    """Fixture-only transport. Nothing from this class enters production source."""
    def __init__(self):
        self.calls=[];self.objects={};self.lists={};self.keys={};self.fail=None;self.callback=None
        self.price=dict(id='price_fixture',object='price',livemode=False,active=True,unit_amount=1900,
            currency='usd',billing_scheme='per_unit',type='recurring',
            recurring=dict(interval='month',interval_count=1,usage_type='licensed'))
        self.objects['/prices/price_fixture']=self.price

    def __call__(self,method,url,headers,body,timeout,max_bytes):
        parsed=urlsplit(url);path=parsed.path.removeprefix('/v1')
        params={k:v[0] for k,v in parse_qs((body or b'').decode() if method=='POST' else parsed.query).items()}
        self.calls.append((method,path,headers.get('Idempotency-Key'),params))
        if self.callback:self.callback(method,path)
        if self.fail and self.fail(method,path):raise TimeoutError('fixture timeout')
        if method=='POST':
            key=headers['Idempotency-Key']
            if key not in self.keys:
                if path=='/customers':
                    obj=dict(id='cus_fixture',object='customer',livemode=False,
                        metadata={'customer_key':params['metadata[customer_key]'],'team_id':params['metadata[team_id]']})
                    self.objects['/customers/cus_fixture']=obj
                elif path=='/checkout/sessions':
                    obj=dict(id='cs_fixture',object='checkout.session',livemode=False,customer=params['customer'],
                        currency=params.get('currency','eur' if 'eur' in self.price.get('currency_options',{}) else self.price['currency']),
                        mode='subscription',client_reference_id=params['client_reference_id'],status='open',
                        url='https://checkout.stripe.com/c/pay_fixture',expires_at=int(time.time())+3600,
                        subscription=None,success_url=params['success_url'],cancel_url=params['cancel_url'])
                    self.objects['/checkout/sessions/cs_fixture']=obj
                    self.lists['/checkout/sessions']=[obj]
                elif path.startswith('/checkout/sessions/') and path.endswith('/expire'):
                    session_id=path.split('/')[3]
                    obj=self.objects['/checkout/sessions/'+session_id]
                    if obj['status']!='open':return 400,b'{}'
                    obj['status']='expired';obj['url']=None
                elif path=='/billing_portal/sessions':
                    obj=dict(id='bps_fixture',object='billing_portal.session',livemode=False,
                        customer=params['customer'],return_url=params['return_url'],url='https://billing.stripe.com/p/session_fixture')
                else:raise AssertionError(path)
                self.keys[key]=obj
            obj=self.keys[key]
        elif path.endswith('/line_items'):
            obj=dict(object='list',has_more=False,data=[dict(object='item',quantity=1,price=self.price)])
        elif path in self.lists or path in ('/subscriptions','/customers','/checkout/sessions','/invoice_payments','/disputes'):
            values=self.lists.get(path, [o for p,o in self.objects.items() if p.startswith('/customers/')] if path=='/customers' else [])
            if params.get('customer'):values=[o for o in values if o.get('customer')==params['customer']]
            if params.get('invoice'):values=[o for o in values if o.get('invoice')==params['invoice']]
            if params.get('charge'):values=[o for o in values if o.get('charge')==params['charge']]
            obj=dict(object='list',has_more=False,data=values)
        else:
            obj=self.objects[path]
        return 200,json.dumps(obj).encode()

    def paid(self, *, sub='sub_fixture', invoice='in_fixture', charge='ch_fixture', amount=1900,currency='usd'):
        start=int(time.time())-29*86400;end=int(time.time())+3600
        subscription=dict(id=sub,object='subscription',livemode=False,customer='cus_fixture',status='active',
            latest_invoice=invoice,cancel_at_period_end=False,pause_collection=None,
            items=dict(object='list',has_more=False,data=[dict(id='si_fixture',object='subscription_item',
                quantity=1,price=self.price,current_period_start=start,current_period_end=end)]))
        self.objects['/subscriptions/'+sub]=subscription;self.lists['/subscriptions']=[subscription]
        self.objects['/invoices/'+invoice]=dict(id=invoice,object='invoice',livemode=False,customer='cus_fixture',
            status='paid',amount_paid=amount,currency=currency,
            parent={'type':'subscription_details','subscription_details':{'subscription':sub}})
        self.lists['/invoices/'+invoice+'/lines']=[dict(id='il_'+invoice,object='line_item',livemode=False,
            invoice=invoice,currency=currency,amount=self.price['unit_amount'],quantity=1,quantity_decimal='1',
            pricing={'type':'price_details','price_details':{'price':self.price['id']},'unit_amount_decimal':str(self.price['unit_amount'])},
            parent={'type':'subscription_item_details','subscription_item_details':{
                'subscription':sub,'subscription_item':'si_fixture','proration':False}},
            period={'start':start,'end':end})]
        payment=dict(id='inpay_'+charge,object='invoice_payment',livemode=False,invoice=invoice,
            status='paid',amount_paid=amount,currency=currency,payment={'type':'payment_intent','payment_intent':'pi_'+charge})
        self.lists['/invoice_payments']=[payment]
        self.objects['/payment_intents/pi_'+charge]=dict(id='pi_'+charge,object='payment_intent',livemode=False,
            customer='cus_fixture',status='succeeded',latest_charge=charge,currency=currency,amount_received=amount)
        self.objects['/charges/'+charge]=dict(id=charge,object='charge',livemode=False,customer='cus_fixture',
            payment_intent='pi_'+charge,amount_captured=amount,amount_refunded=0,currency=currency,
            captured=True,paid=True,disputed=False,status='succeeded',refunded=False)
        return subscription


class BillingServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.billing_service'),'Billing coordinator must exist')
        self.module=importlib.import_module('coopagents.billing_service')
        root=Path('.local/c2-stripe-tests');root.mkdir(parents=True,exist_ok=True)
        self.identity=IdentityStore(root/(str(uuid4())+'.sqlite'));self.accounts=AccountStore(self.identity)
        self.accounts.bootstrap('owner','long password 123');self.owner=self.accounts.login('owner','long password 123')['session_token']
        self.workspaces=WorkspaceStore(self.accounts);self.team=self.workspaces.create_team(self.owner,'Team')['team_id']
        self.catalog=BillingCatalog(2,1,20,10,'price_fixture','test')
        self.store=BillingStore(self.workspaces,'cloud',self.catalog);self.transport=FixtureTransport()
        self.client=StripeClient('sk_test_fixture','test',transport=self.transport)
        self.service=self.module.BillingService(self.store,self.client,'whsec_fixture','https://coopagents.example')

    def bind(self):
        self.store.bind_customer(self.team,'cus_fixture',provider_mode='test')
        self.transport.objects['/customers/cus_fixture']=dict(id='cus_fixture',object='customer',livemode=False,metadata={})

    def webhook(self,event_id='evt_fixture',kind='invoice.paid',object_id='in_fixture'):
        raw=json.dumps(dict(id=event_id,type=kind,livemode=False,data={'object':{'id':object_id,'metadata':{'team_id':'evil'}}})).encode()
        stamp=str(int(time.time()));mac=hmac.new(b'whsec_fixture',stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return self.service.ingest_webhook(raw,'t='+stamp+',v1='+mac)

    def release_checkout(self):
        with self.store.db.connect(write=True) as c:c.execute('UPDATE billing_checkouts SET lease_until=0')

    def test_summary_actual_price_and_outage_preserves_paid_snapshot(self):
        self.bind();self.transport.paid();self.service.sync(self.owner,self.team)
        summary=self.service.summary(self.owner,self.team)
        self.assertEqual('team',summary['plan']);self.assertEqual(1900,summary['price']['amount'])
        self.transport.fail=lambda method,path:path.startswith('/prices/')
        summary=self.service.summary(self.owner,self.team)
        self.assertEqual('team',summary['plan']);self.assertFalse(summary['checkout_available'])
        self.assertIsNone(summary['price']);self.assertEqual('provider_unavailable',summary['price_error'])

    def test_checkout_stable_keys_restart_and_single_outbound_winner(self):
        first=self.service.checkout(self.owner,self.team)
        self.assertEqual('checkout',first['kind']);self.assertTrue(first['url'].startswith('https://checkout.stripe.com/'))
        restarted=self.module.BillingService(BillingStore(self.workspaces,'cloud',self.catalog),self.client,'whsec_fixture','https://coopagents.example')
        second=restarted.checkout(self.owner,self.team)
        self.assertEqual(first,second)
        creates=[call for call in self.transport.calls if call[0]=='POST' and call[1]=='/checkout/sessions']
        self.assertEqual(1,len(creates))
        self.assertEqual('price_fixture',creates[0][3]['line_items[0][price]']);self.assertEqual('1',creates[0][3]['line_items[0][quantity]'])
        self.assertEqual('https://coopagents.example/#billing-return',creates[0][3]['success_url'])
        self.assertNotIn('customer_email',creates[0][3])

    def test_multicurrency_price_pins_verified_base_currency_and_paid_checkout_reconciles(self):
        self.transport.price['currency_options']={'eur':{'unit_amount':1750}}
        summary=self.service.summary(self.owner,self.team)
        self.assertTrue(summary['checkout_available']);self.assertEqual('usd',summary['price']['currency'])
        self.assertEqual('checkout',self.service.checkout(self.owner,self.team)['kind'])
        params=next(c[3] for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions')
        self.assertEqual('usd',params.get('currency'))
        self.assertEqual('false',params.get('adaptive_pricing[enabled]'))
        checkout=self.transport.objects['/checkout/sessions/cs_fixture']
        self.assertEqual('usd',checkout['currency'])
        checkout.update(status='complete',url=None,subscription='sub_fixture')
        self.transport.paid(currency=checkout['currency']);self.service.sync(self.owner,self.team)
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        self.assertEqual(1900,self.service.summary(self.owner,self.team)['price']['amount'])

    def test_portal_invalid_raw_urls_never_return_redirect_or_complete_operation(self):
        self.bind();original=self.transport.__call__;bad_url=[]
        def invalid_url(method,url,headers,body,timeout,max_bytes):
            status,raw=original(method,url,headers,body,timeout,max_bytes)
            if method=='POST' and urlsplit(url).path=='/v1/billing_portal/sessions':
                obj=json.loads(raw);obj['url']=bad_url[0];raw=json.dumps(obj).encode()
            return status,raw
        self.client.transport=invalid_url
        for url in ['https://billing.stripe.com/p/session#',r'https://billing.stripe.com/p\session']:
            bad_url[:]=[url]
            with self.subTest(url=url):
                with self.assertRaises(StripeError) as error:self.service.portal(self.owner,self.team)
                self.assertEqual('invalid_provider_url',error.exception.code)
                with self.store.db.connect() as c:
                    self.assertEqual('pending',c.execute("SELECT state FROM billing_outbound_operations WHERE purpose='portal'").fetchone()[0])

    def test_wrong_checkout_currency_is_rejected_before_owner_receives_url(self):
        original=self.transport.__call__
        def wrong_currency(method,url,headers,body,timeout,max_bytes):
            status,raw=original(method,url,headers,body,timeout,max_bytes)
            if method=='POST' and urlsplit(url).path=='/v1/checkout/sessions':
                obj=json.loads(raw);obj['currency']='eur';raw=json.dumps(obj).encode()
            return status,raw
        self.client.transport=wrong_currency
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        with self.store.db.connect() as c:
            self.assertIsNone(c.execute('SELECT checkout_url FROM billing_checkouts').fetchone()[0])

    def test_real_checkout_fragment_returns_and_survives_persistent_retry(self):
        url='https://checkout.stripe.com/c/pay/cs_test_fixture#fidkdWxOYHwnPyd1blppbHNgWjA0'
        original=self.transport.__call__
        def fragment(method,endpoint,headers,body,timeout,max_bytes):
            status,raw=original(method,endpoint,headers,body,timeout,max_bytes)
            if method=='POST' and urlsplit(endpoint).path=='/v1/checkout/sessions':
                obj=self.transport.objects['/checkout/sessions/cs_fixture'];obj['url']=url
                raw=json.dumps(obj).encode()
            return status,raw
        self.client.transport=fragment
        self.assertEqual(url,self.service.checkout(self.owner,self.team)['url'])
        restarted=self.module.BillingService(BillingStore(self.workspaces,'cloud',self.catalog),self.client,'whsec_fixture','https://coopagents.example')
        self.assertEqual(url,restarted.checkout(self.owner,self.team)['url'])

    def test_uncertain_checkout_reuses_key_then_recovers_after_retention_window(self):
        self.bind();failed=[]
        self.transport.fail=lambda method,path: method=='POST' and path=='/checkout/sessions'
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        attempt=self.store.reserve_checkout(self.team)
        self.transport.fail=None;self.release_checkout()
        recovered=self.service.checkout(self.owner,self.team)
        keys=[c[2] for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']
        self.assertEqual([attempt.idempotency_key]*2,keys)
        # Unknown creation beyond provider retention may only recover a canonical session.
        with self.store.db.connect(write=True) as c:
            c.execute("UPDATE billing_checkouts SET status='pending',checkout_id=NULL,checkout_url=NULL,created_at=?,lease_until=0",(int(time.time())-86401,))
        recovered_again=self.service.checkout(self.owner,self.team)
        self.assertEqual(recovered,recovered_again)
        self.assertEqual(2,len([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']))
        with self.store.db.connect(write=True) as c:c.execute("UPDATE billing_checkouts SET status='pending',checkout_id=NULL,checkout_url=NULL,lease_until=0")
        self.transport.lists['/checkout/sessions']=[]
        with self.assertRaises(StripeError) as error:self.service.checkout(self.owner,self.team)
        self.assertEqual('uncertain_checkout',error.exception.code)

    def test_uncertain_customer_after_retention_uses_server_random_key(self):
        self.transport.fail=lambda method,path:method=='POST' and path=='/customers'
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        self.transport.fail=None
        with self.store.db.connect(write=True) as c:c.execute('UPDATE billing_outbound_operations SET created_at=?',(int(time.time())-86401,))
        with self.assertRaises(StripeError) as error:self.service.checkout(self.owner,self.team)
        self.assertEqual('uncertain_customer',error.exception.code)
        state=self.store.customer_state(self.team)
        self.transport.objects['/customers/cus_fixture']=dict(id='cus_fixture',object='customer',livemode=False,
            metadata={'customer_key':state['customer_key'],'team_id':self.team})
        self.assertEqual('checkout',self.service.checkout(self.owner,self.team)['kind'])
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/customers']))

    def test_existing_subscription_returns_portal_with_durable_key(self):
        self.bind();self.transport.paid();result=self.service.checkout(self.owner,self.team)
        self.assertEqual('portal',result['kind'])
        self.assertFalse(any(c[0]=='POST' and c[1]=='/checkout/sessions' for c in self.transport.calls))
        with self.store.db.connect() as c:
            row=c.execute("SELECT * FROM billing_outbound_operations WHERE purpose='portal'").fetchone()
            self.assertIsNotNone(row);self.assertEqual('complete',row['state'])

    def test_owner_demotion_during_price_or_customer_io_stops_next_mutation_and_url(self):
        invite=self.workspaces.create_invite(self.owner,self.team,'owner')
        self.workspaces.accept_invite(invite['invite_token'],username='next',password='long password 123')
        successor=self.accounts.login('next','long password 123')['session_token'];account=self.accounts.authenticate(self.owner)['id']
        def callback(method,path):
            if path=='/prices/price_fixture':
                self.workspaces.change_role(successor,self.team,account,'member')
        self.transport.callback=callback
        with self.assertRaises(AccessDenied):self.service.checkout(self.owner,self.team)
        self.assertFalse(any(c[0]=='POST' for c in self.transport.calls))
        with self.assertRaises(AccessDenied):self.service.portal(self.owner,self.team)

    def test_webhook_minimal_dedup_queue_and_current_canonical_state(self):
        self.bind();self.transport.paid()
        self.assertTrue(self.webhook());self.assertFalse(self.webhook())
        self.assertTrue(self.service.process_next())
        self.assertEqual('processed',self.store.event_state('evt_fixture')['state'])
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        with self.store.db.connect() as c:
            row=c.execute('SELECT * FROM billing_events').fetchone()
            self.assertIsNone(row['customer_id']);self.assertIsNone(row['subscription_id'])
        self.transport.objects['/subscriptions/sub_fixture']['status']='past_due'
        self.webhook('evt_late','invoice.paid')
        self.assertTrue(self.service.process_next());self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_partial_full_historical_refunds_and_dispute_reopen_close(self):
        self.bind();self.transport.paid();self.service.sync(self.owner,self.team)
        charge=self.transport.objects['/charges/ch_fixture']
        charge['amount_refunded']=100;self.service.sync(self.owner,self.team)
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        charge['amount_refunded']=1900;charge['refunded']=True;self.service.sync(self.owner,self.team)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])
        self.transport.paid(invoice='in_next',charge='ch_next');self.service.sync(self.owner,self.team)
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        current=self.transport.objects['/charges/ch_next'];current['disputed']=True
        dispute=dict(id='du_fixture',object='dispute',livemode=False,charge='ch_next',payment_intent='pi_ch_next',status='needs_response')
        self.transport.lists['/disputes']=[dispute]
        self.service.sync(self.owner,self.team);self.assertTrue(self.store.summary(self.owner,self.team)['risk_hold'])
        for status,hold in [('won',False),('warning_closed',False),('under_review',True),('lost',True),('won',False)]:
            dispute['status']=status;self.service.sync(self.owner,self.team)
            self.assertEqual(hold,self.store.summary(self.owner,self.team)['risk_hold'])

    def test_nested_shapes_period_end_pause_and_foreign_invoice_fail_closed(self):
        self.bind();sub=self.transport.paid();sub['current_period_end']=1
        self.service.sync(self.owner,self.team);self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        sub['pause_collection']={'behavior':'void'};self.service.sync(self.owner,self.team)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])
        sub['pause_collection']=None;invoice=self.transport.objects['/invoices/in_fixture'];invoice['customer']='cus_other'
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_current_price_cannot_grant_from_foreign_or_cheap_invoice_line_price(self):
        self.bind();self.transport.paid()
        line=self.transport.lists['/invoices/in_fixture/lines'][0]
        line['pricing']['price_details']['price']='price_cheap';line['amount']=1
        line['pricing']['unit_amount_decimal']='1'
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_paid_invoice_old_period_cannot_extend_current_item_period(self):
        self.bind();subscription=self.transport.paid()
        line=self.transport.lists['/invoices/in_fixture/lines'][0]
        subscription['items']['data'][0]['current_period_start']+=3600
        subscription['items']['data'][0]['current_period_end']+=3600
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_invoice_lines_verify_parent_item_mode_currency_decimal_quantity_and_proration(self):
        self.bind();self.transport.paid()
        original=copy.deepcopy(self.transport.lists['/invoices/in_fixture/lines'][0])
        changes=[{'invoice':'in_foreign'}, {'livemode':True}, {'livemode':0}, {'currency':'eur'},
            {'quantity':True}, {'quantity':2}, {'quantity_decimal':'1.5'}, {'quantity_decimal':None},
            {'quantity_decimal':1.0}, {'period':{'start':1,'end':2}},
            {'parent':{'type':'invoice_item_details','invoice_item_details':{'subscription':'sub_fixture'}}},
            {'parent':{'type':'subscription_item_details','subscription_item_details':{
                'subscription':'sub_foreign','subscription_item':'si_fixture','proration':False}}},
            {'parent':{'type':'subscription_item_details','subscription_item_details':{
                'subscription':'sub_fixture','subscription_item':'si_foreign','proration':False}}},
            {'parent':{'type':'subscription_item_details','subscription_item_details':{
                'subscription':'sub_fixture','subscription_item':'si_fixture','proration':True}}}]
        for change in changes:
            with self.subTest(change=change):
                self.transport.lists['/invoices/in_fixture/lines']=[copy.deepcopy(original)|change]
                with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
                self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])
        self.transport.lists['/invoices/in_fixture/lines']=[original]
        self.service.sync(self.owner,self.team)
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])

    def test_invoice_line_pagination_incomplete_or_extra_lines_never_grants(self):
        self.bind();self.transport.paid()
        line=self.transport.lists['/invoices/in_fixture/lines'][0]
        original=self.client.transport
        def incomplete(method,url,headers,body,timeout,max_bytes):
            if urlsplit(url).path=='/v1/invoices/in_fixture/lines':
                return 200,json.dumps({'object':'list','has_more':True,'data':[line]}).encode()
            return original(method,url,headers,body,timeout,max_bytes)
        self.client.transport=incomplete;self.client.max_pages=1
        with self.assertRaises(StripeError) as error:self.service.sync(self.owner,self.team)
        self.assertEqual('pagination_incomplete',error.exception.code)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])
        self.client.transport=original
        self.transport.lists['/invoices/in_fixture/lines'].append(line|{'id':'il_extra'})
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_worker_transient_retry_restart_and_unbound_events(self):
        self.bind();self.transport.paid();self.webhook()
        self.transport.fail=lambda method,path:path=='/subscriptions/sub_fixture'
        self.assertFalse(self.service.process_next());self.assertEqual('pending',self.store.event_state('evt_fixture')['state'])
        self.transport.fail=None
        with self.store.db.connect(write=True) as c:c.execute('UPDATE billing_events SET next_attempt=0')
        restarted=self.module.BillingService(BillingStore(self.workspaces,'cloud',self.catalog),self.client,'whsec_fixture','https://coopagents.example')
        self.assertTrue(restarted.process_next());self.assertEqual(2,self.store.event_state('evt_fixture')['attempts'])

    def test_selfhost_never_calls_provider(self):
        self.store=BillingStore(self.workspaces,'self-hosted',self.catalog)
        service=self.module.BillingService(self.store,None,None,'https://coopagents.example')
        self.assertEqual('unlimited',service.summary(self.owner,self.team)['plan'])
        self.assertFalse(service.process_next())
        with self.assertRaises(Conflict):service.checkout(self.owner,self.team)
        self.assertEqual([],self.transport.calls)

    def test_disabled_service_needs_no_origin_and_custom_https_port_is_canonical(self):
        disabled=BillingStore(self.workspaces,'self-hosted')
        service=self.module.BillingService(disabled,None,None,None)
        self.assertEqual('unlimited',service.summary(self.owner,self.team)['plan'])
        service=self.module.BillingService(self.store,self.client,'whsec_fixture','https://coopagents.example:8443')
        result=service.checkout(self.owner,self.team)
        self.assertEqual('checkout',result['kind'])
        self.assertEqual('https://coopagents.example:8443/#billing-return',self.transport.objects['/checkout/sessions/cs_fixture']['success_url'])

    def test_prior_subscription_lookup_failure_records_error_preserves_verified_state(self):
        self.bind();self.transport.paid();self.service.sync(self.owner,self.team)
        self.transport.fail=lambda method,path:path=='/subscriptions/sub_fixture'
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        summary=self.store.summary(self.owner,self.team)
        self.assertEqual('team',summary['plan']);self.assertEqual('provider_unavailable',summary['billing']['last_error'])

    def test_invalid_actual_price_blocks_all_checkout_mutations(self):
        self.transport.price['recurring']['usage_type']='metered'
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        self.assertFalse(any(c[0]=='POST' for c in self.transport.calls))

    def test_transformed_price_disables_summary_and_blocks_checkout_mutations(self):
        for transform in [{'divide_by':100,'round':'down'}, {'divide_by':5,'round':'up'}, {}, False]:
            with self.subTest(transform=transform):
                self.transport.price['transform_quantity']=transform
                summary=self.service.summary(self.owner,self.team)
                self.assertFalse(summary['checkout_available'])
                self.assertIsNone(summary['price'])
                self.assertEqual('invalid_monthly_price',summary['price_error'])
                with self.assertRaises(StripeError) as error:self.service.checkout(self.owner,self.team)
                self.assertEqual('invalid_monthly_price',error.exception.code)
                self.assertFalse(any(c[0]=='POST' for c in self.transport.calls))

    def test_signed_unrelated_null_customer_charge_refund_dispute_ignore_without_entitlement_change(self):
        self.bind();self.transport.paid();self.service.sync(self.owner,self.team)
        snapshot=self.store.current_snapshot(self.team)
        self.transport.objects['/charges/ch_unrelated']=dict(id='ch_unrelated',object='charge',livemode=False,
            customer=None,payment_intent=None,metadata={'team_id':self.team})
        self.transport.objects['/refunds/re_unrelated']=dict(id='re_unrelated',object='refund',charge='ch_unrelated',payment_intent=None)
        self.transport.objects['/disputes/du_unrelated']=dict(id='du_unrelated',object='dispute',livemode=False,
            charge='ch_unrelated',payment_intent=None,status='lost')
        for index,(kind,obj_id) in enumerate([('charge.refunded','ch_unrelated'),
                ('refund.updated','re_unrelated'),('charge.dispute.closed','du_unrelated')]):
            with self.subTest(kind=kind):
                event_id='evt_null'+str(index)
                self.webhook(event_id,kind,obj_id)
                self.assertTrue(self.service.process_next())
                self.assertEqual('ignored',self.store.event_state(event_id)['state'])
                self.assertEqual(snapshot,self.store.current_snapshot(self.team))
                self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])

    def test_null_subscription_invoice_checkout_and_malformed_charge_customers_still_retry(self):
        self.transport.objects['/subscriptions/sub_null']=dict(id='sub_null',object='subscription',livemode=False,customer=None)
        self.transport.objects['/invoices/in_null']=dict(id='in_null',object='invoice',livemode=False,customer=None)
        self.transport.objects['/checkout/sessions/cs_null']=dict(id='cs_null',object='checkout.session',livemode=False,customer=None)
        for index,(kind,obj_id) in enumerate([('customer.subscription.updated','sub_null'),
                ('invoice.paid','in_null'),('checkout.session.completed','cs_null')]):
            with self.subTest(kind=kind):
                event_id='evt_strict'+str(index);self.webhook(event_id,kind,obj_id)
                self.assertFalse(self.service.process_next())
                self.assertEqual('pending',self.store.event_state(event_id)['state'])
        for index,customer in enumerate([0,False,[],{'id':'evil'},'evil','']):
            with self.subTest(customer=customer):
                self.transport.objects['/charges/ch_bad']=dict(id='ch_bad',object='charge',livemode=False,customer=customer)
                event_id='evt_malformed'+str(index);self.webhook(event_id,'charge.refunded','ch_bad')
                self.assertFalse(self.service.process_next())
                self.assertEqual('pending',self.store.event_state(event_id)['state'])
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_snapshot_first_and_checkout_first_converge_to_confirmed(self):
        self.service.checkout(self.owner,self.team)
        obj=self.transport.objects['/checkout/sessions/cs_fixture'];obj['status']='complete';obj['url']=None;obj['subscription']='sub_fixture'
        self.transport.paid();self.service.sync(self.owner,self.team)
        self.assertEqual('portal',self.service.checkout(self.owner,self.team)['kind'])
        with self.store.db.connect() as c:self.assertEqual('confirmed',c.execute('SELECT status FROM billing_checkouts').fetchone()[0])
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']))

    def test_active_subscription_after_uncertain_checkout_cannot_create_second_session(self):
        self.bind();attempt=self.store.reserve_checkout(self.team)
        self.release_checkout();self.transport.paid()
        with self.assertRaises(StripeError) as error:self.service.checkout(self.owner,self.team)
        self.assertEqual('uncertain_checkout',error.exception.code)
        self.assertFalse(any(c[0]=='POST' and c[1]=='/checkout/sessions' for c in self.transport.calls))

    def test_old_subscription_terminal_reconciled_before_replacement(self):
        self.bind();old=self.transport.paid();self.service.sync(self.owner,self.team)
        old['status']='canceled'
        self.transport.paid(sub='sub_next',invoice='in_next',charge='ch_next')
        self.service.sync(self.owner,self.team)
        current=self.store.current_snapshot(self.team)
        self.assertEqual('sub_next',current.subscription_id);self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])

    def test_payment_records_foreign_intents_duplicates_and_incomplete_assessment_fail(self):
        self.bind();self.transport.paid()
        payment=self.transport.lists['/invoice_payments'][0]
        payment['payment']={'type':'payment_record','payment_record':'pr_fixture'}
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])
        self.transport.paid();payment=self.transport.lists['/invoice_payments'][0]
        self.transport.lists['/invoice_payments'].append(payment|{'id':'inpay_duplicate'})
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        self.transport.paid();self.transport.objects['/payment_intents/pi_ch_fixture']['customer']='cus_other'
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)
        self.transport.paid();self.transport.lists['/invoice_payments']=[]
        with self.assertRaises(StripeError):self.service.sync(self.owner,self.team)

    def test_multiple_payments_full_invoice_refund_only_and_direct_charge(self):
        self.bind();self.transport.paid(amount=1000)
        first=self.transport.lists['/invoice_payments'][0]
        firstcharge=self.transport.objects['/charges/ch_fixture']
        self.transport.paid(charge='ch_second',amount=900)
        second=self.transport.lists['/invoice_payments'][0]
        second['payment']={'type':'charge','charge':'ch_second'}
        self.transport.lists['/invoice_payments']=[first,second]
        self.transport.objects['/invoices/in_fixture']['amount_paid']=1900
        firstcharge['amount_refunded']=1000;firstcharge['refunded']=True
        self.service.sync(self.owner,self.team);self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        self.transport.objects['/charges/ch_second']['amount_refunded']=900
        self.transport.objects['/charges/ch_second']['refunded']=True
        self.service.sync(self.owner,self.team);self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_unbound_server_customer_event_retries_then_binding_allows_processing(self):
        state=self.store.customer_state(self.team)
        self.service.operations.reserve(self.team,'customer',key=state['customer_key'])
        self.transport.objects['/customers/cus_fixture']=dict(id='cus_fixture',object='customer',livemode=False,
            metadata={'customer_key':state['customer_key'],'team_id':self.team})
        self.transport.paid();self.webhook()
        self.transport.fail=lambda method,path:path=='/customers'
        self.assertFalse(self.service.process_next())
        self.assertEqual('pending',self.store.event_state('evt_fixture')['state'])
        self.transport.fail=None
        with self.store.db.connect(write=True) as c:c.execute('UPDATE billing_events SET next_attempt=0')
        self.assertTrue(self.service.process_next());self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])

    def test_admin_reconcile_team_fetches_only_server_bound_canonical_ids(self):
        self.bind();self.transport.paid()
        self.assertTrue(self.service.reconcile_team(self.team))
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        self.assertTrue(all(c[0]=='GET' for c in self.transport.calls))
        another=self.workspaces.create_team(self.owner,'unbound')['team_id']
        before=len(self.transport.calls)
        with self.assertRaises(Conflict):self.service.reconcile_team(another)
        self.assertEqual(before,len(self.transport.calls))

    def test_unknown_signed_event_and_unrelated_customer_ignore_safely(self):
        self.webhook('evt_unknown','customer.created','cus_other')
        self.assertTrue(self.service.process_next());self.assertEqual('ignored',self.store.event_state('evt_unknown')['state'])
        self.transport.paid();self.transport.objects['/customers/cus_fixture']=dict(id='cus_fixture',object='customer',livemode=False,metadata={'team_id':self.team})
        self.webhook('evt_foreign')
        self.assertTrue(self.service.process_next());self.assertEqual('ignored',self.store.event_state('evt_foreign')['state'])
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_stale_fetch_cannot_overwrite_newer_process_snapshot(self):
        self.bind();self.transport.paid();self.service.sync(self.owner,self.team)
        pause=threading.Event();resume=threading.Event();thread_id=[];failures=[]
        original=self.transport.__call__
        def delayed(method,url,headers,body,timeout,max_bytes):
            result=original(method,url,headers,body,timeout,max_bytes)
            if thread_id and threading.get_ident()==thread_id[0] and urlsplit(url).path=='/v1/invoice_payments':
                pause.set();resume.wait(5)
            return result
        stale=self.module.BillingService(BillingStore(self.workspaces,'cloud',self.catalog),
            StripeClient('sk_test_fixture','test',transport=delayed),'whsec_fixture','https://coopagents.example')
        def slow_sync():
            thread_id.append(threading.get_ident())
            try:stale.sync(self.owner,self.team)
            except StripeError as error:failures.append(error.code)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(slow_sync);self.assertTrue(pause.wait(5))
            self.transport.objects['/subscriptions/sub_fixture']['status']='past_due'
            self.service.sync(self.owner,self.team);resume.set();future.result(5)
        self.assertEqual(['sync_superseded'],failures)
        self.assertEqual('past_due',self.store.current_snapshot(self.team).status)
        self.assertIsNone(self.store.summary(self.owner,self.team)['billing']['last_error'])

    def test_concurrent_customer_creates_share_persistent_key_after_binding_race(self):
        barrier=threading.Barrier(2)
        def callback(method,path):
            if method=='POST' and path=='/customers':barrier.wait(5)
        self.transport.callback=callback
        outcomes=[]
        def create():
            try:
                with self.client.operation():return self.service._customer(self.team)
            except Exception as error:return type(error).__name__
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(lambda _:create(),range(2)))
        self.assertEqual(['cus_fixture','cus_fixture'],outcomes)
        keys=[c[2] for c in self.transport.calls if c[0]=='POST']
        self.assertEqual(2,len(keys));self.assertEqual(keys[0],keys[1])

    def test_completed_customer_ledger_reused_after_unbound_read_binding_race(self):
        state=self.store.customer_state(self.team)
        operation=self.service.operations.reserve(self.team,'customer',key=state['customer_key'])
        self.store.bind_customer(self.team,'cus_fixture',provider_mode='test')
        self.service.operations.complete(operation,'cus_fixture')
        reused=self.service.operations.reserve(self.team,'customer',key=state['customer_key'])
        self.assertEqual(operation['operation_id'],reused['operation_id'])
        self.assertEqual('complete',reused['state'])

    def test_refund_without_legacy_livemode_uses_verified_canonical_charge(self):
        self.bind();self.transport.paid()
        self.transport.objects['/refunds/re_fixture']=dict(id='re_fixture',object='refund',charge='ch_fixture',
            payment_intent='pi_ch_fixture',amount=1900,currency='usd',status='succeeded')
        self.transport.objects['/charges/ch_fixture']['amount_refunded']=1900
        self.transport.objects['/charges/ch_fixture']['refunded']=True
        self.webhook('evt_refund','refund.updated','re_fixture')
        self.assertTrue(self.service.process_next());self.assertTrue(self.store.summary(self.owner,self.team)['risk_hold'])

    def test_current_dispute_event_recomputes_risk_from_current_invoice(self):
        self.bind();self.transport.paid();charge=self.transport.objects['/charges/ch_fixture'];charge['disputed']=True
        dispute=dict(id='du_fixture',object='dispute',livemode=False,charge='ch_fixture',payment_intent='pi_ch_fixture',status='lost')
        self.transport.objects['/disputes/du_fixture']=dispute;self.transport.lists['/disputes']=[dispute]
        self.webhook('evt_dispute','charge.dispute.closed','du_fixture');self.assertTrue(self.service.process_next())
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])
        self.transport.paid(invoice='in_new',charge='ch_new')
        self.webhook('evt_obsolete','charge.dispute.updated','du_fixture');self.assertTrue(self.service.process_next())
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])

    def test_owner_demotion_after_checkout_creation_suppresses_redirect(self):
        invite=self.workspaces.create_invite(self.owner,self.team,'owner')
        self.workspaces.accept_invite(invite['invite_token'],username='next',password='long password 123')
        successor=self.accounts.login('next','long password 123')['session_token'];account=self.accounts.authenticate(self.owner)['id']
        def callback(method,path):
            if method=='POST' and path=='/checkout/sessions':
                self.workspaces.change_role(successor,self.team,account,'member')
        self.transport.callback=callback
        with self.assertRaises(AccessDenied):self.service.checkout(self.owner,self.team)
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']))
        self.assertFalse(any(c[1].endswith('/line_items') for c in self.transport.calls))

    def test_summary_removal_during_price_io_denies_stale_team_data(self):
        invite=self.workspaces.create_invite(self.owner,self.team,'owner')
        self.workspaces.accept_invite(invite['invite_token'],username='next',password='long password 123')
        successor=self.accounts.login('next','long password 123')['session_token'];account=self.accounts.authenticate(self.owner)['id']
        def callback(method,path):
            if path=='/prices/price_fixture':self.workspaces.remove_member(successor,self.team,account)
        self.transport.callback=callback
        with self.assertRaises(AccessDenied):self.service.summary(self.owner,self.team)

    def test_uncertain_portal_reuses_key_restart_and_after_retention_fails_closed(self):
        self.bind();self.transport.fail=lambda method,path:path=='/billing_portal/sessions'
        with self.assertRaises(StripeError):self.service.portal(self.owner,self.team)
        self.transport.fail=None
        self.assertEqual('portal',self.service.portal(self.owner,self.team)['kind'])
        keys=[c[2] for c in self.transport.calls if c[0]=='POST']
        self.assertEqual(keys[0],keys[1])
        self.transport.fail=lambda method,path:path=='/billing_portal/sessions'
        with self.assertRaises(StripeError):self.service.portal(self.owner,self.team)
        with self.store.db.connect(write=True) as c:c.execute("UPDATE billing_outbound_operations SET created_at=? WHERE state='pending'",(int(time.time())-86401,))
        self.transport.fail=None
        with self.assertRaises(StripeError) as error:self.service.portal(self.owner,self.team)
        self.assertEqual('uncertain_portal',error.exception.code)

    def test_fresh_process_retries_same_checkout_key_from_real_sqlite(self):
        self.bind();attempt=self.store.reserve_checkout(self.team);self.release_checkout()
        script='''import json,sys
sys.path.insert(0,'tests')
from test_billing_service import FixtureTransport
from coopagents.accounts import AccountStore
from coopagents.identity import IdentityStore
from coopagents.workspaces import WorkspaceStore
from coopagents.billing import BillingCatalog,BillingStore
from coopagents.billing_service import BillingService
from coopagents.stripe_billing import StripeClient
transport=FixtureTransport()
transport.objects['/customers/cus_fixture']={'id':'cus_fixture','object':'customer','livemode':False,'metadata':{}}
store=BillingStore(WorkspaceStore(AccountStore(IdentityStore(sys.argv[1]))),'cloud',BillingCatalog(2,1,20,10,'price_fixture','test'))
service=BillingService(store,StripeClient('sk_test_fixture','test',transport=transport),'whsec_fixture','https://coopagents.example')
service.checkout(sys.argv[2],sys.argv[3])
print(json.dumps([c[2] for c in transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']))
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.identity.db.path),self.owner,self.team],capture_output=True,text=True,check=True)
        self.assertEqual([attempt.idempotency_key],json.loads(result.stdout))

    def test_fresh_process_worker_recovers_created_customer_before_local_binding(self):
        state=self.store.customer_state(self.team)
        self.service.operations.reserve(self.team,'customer',key=state['customer_key'])
        self.webhook()
        script='''import json,sys
sys.path.insert(0,'tests')
from test_billing_service import FixtureTransport
from coopagents.accounts import AccountStore
from coopagents.identity import IdentityStore
from coopagents.workspaces import WorkspaceStore
from coopagents.billing import BillingCatalog,BillingStore
from coopagents.billing_service import BillingService
from coopagents.stripe_billing import StripeClient
store=BillingStore(WorkspaceStore(AccountStore(IdentityStore(sys.argv[1]))),'cloud',BillingCatalog(2,1,20,10,'price_fixture','test'))
state=store.customer_state(sys.argv[2])
transport=FixtureTransport();transport.paid()
transport.objects['/customers/cus_fixture']={'id':'cus_fixture','object':'customer','livemode':False,'metadata':{'customer_key':state['customer_key'],'team_id':sys.argv[2]}}
service=BillingService(store,StripeClient('sk_test_fixture','test',transport=transport),'whsec_fixture','https://coopagents.example')
print(json.dumps({'processed':service.process_next(),'customer':store.customer_state(sys.argv[2])['customer_id']}))
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.identity.db.path),self.team],capture_output=True,text=True,check=True)
        self.assertEqual({'processed':True,'customer':'cus_fixture'},json.loads(result.stdout))
        self.assertEqual('processed',self.store.event_state('evt_fixture')['state'])
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])

    def test_payment_pagination_fetches_all_pages_and_exhaustion_never_grants(self):
        self.bind();self.transport.paid(amount=1000);first=self.transport.lists['/invoice_payments'][0]
        self.transport.paid(charge='ch_second',amount=900);second=self.transport.lists['/invoice_payments'][0]
        self.transport.objects['/invoices/in_fixture']['amount_paid']=1900
        def pages(method,url,headers,body,timeout,max_bytes):
            parsed=urlsplit(url)
            if parsed.path=='/v1/invoice_payments':
                params=parse_qs(parsed.query);next_page='starting_after' in params
                return 200,json.dumps({'object':'list','has_more':not next_page,'data':[second if next_page else first]}).encode()
            return self.transport(method,url,headers,body,timeout,max_bytes)
        self.client.transport=pages
        self.service.sync(self.owner,self.team);self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])
        self.client.max_pages=1
        with self.assertRaises(StripeError) as error:self.service.sync(self.owner,self.team)
        self.assertEqual('pagination_incomplete',error.exception.code)
        # Existing paid evidence is preserved; an empty fresh database could not receive Team.
        self.assertEqual('team',self.store.summary(self.owner,self.team)['plan'])

    def test_nonterminal_open_session_uses_portal_and_does_not_offer_second_subscription(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        result=self.service.checkout(self.owner,self.team)
        self.assertEqual('portal',result['kind'])
        self.assertEqual('expired',self.transport.objects['/checkout/sessions/cs_fixture']['status'])
        expires=[c for c in self.transport.calls if c[0]=='POST' and c[1].endswith('/expire')]
        with self.store.db.connect() as c:key=c.execute('SELECT idempotency_key FROM billing_checkouts').fetchone()[0]
        self.assertEqual(['expire_'+key],[c[2] for c in expires])
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']))

    def test_nonterminal_subscription_with_competing_checkout_lease_never_returns_open_url(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        held=self.store.reserve_checkout(self.team,refresh=True)
        self.assertTrue(held.claimed)
        with self.assertRaises(StripeError) as error:self.service.checkout(self.owner,self.team)
        self.assertEqual('checkout_busy',error.exception.code)
        self.assertFalse(any(c[0]=='POST' and c[1]=='/billing_portal/sessions' for c in self.transport.calls))
        self.release_checkout()
        self.assertEqual('portal',self.service.checkout(self.owner,self.team)['kind'])
        self.assertEqual('expired',self.transport.objects['/checkout/sessions/cs_fixture']['status'])

    def test_expiry_failure_retries_same_key_after_restart_before_portal(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        self.transport.fail=lambda method,path:method=='POST' and path.endswith('/expire')
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        self.assertEqual('open',self.transport.objects['/checkout/sessions/cs_fixture']['status'])
        self.assertFalse(any(c[1]=='/billing_portal/sessions' for c in self.transport.calls))
        self.release_checkout();self.transport.fail=None
        restarted=self.module.BillingService(BillingStore(self.workspaces,'cloud',self.catalog),self.client,'whsec_fixture','https://coopagents.example')
        self.assertEqual('portal',restarted.checkout(self.owner,self.team)['kind'])
        keys=[c[2] for c in self.transport.calls if c[0]=='POST' and c[1].endswith('/expire')]
        self.assertEqual(2,len(keys));self.assertEqual(keys[0],keys[1])
        self.assertEqual('expired',self.transport.objects['/checkout/sessions/cs_fixture']['status'])

    def test_expiry_completed_race_retrieves_and_confirms_matching_subscription(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        def complete(method,path):
            if method=='POST' and path.endswith('/expire'):
                obj=self.transport.objects['/checkout/sessions/cs_fixture']
                obj.update(status='complete',url=None,subscription='sub_fixture')
        self.transport.callback=complete
        self.assertEqual('portal',self.service.checkout(self.owner,self.team)['kind'])
        self.assertTrue(any(c[0]=='POST' and c[1].endswith('/expire') for c in self.transport.calls))
        with self.store.db.connect() as c:self.assertEqual('confirmed',c.execute('SELECT status FROM billing_checkouts').fetchone()[0])

    def test_expiry_completed_race_with_other_subscription_fails_before_portal(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        alternate=copy.deepcopy(self.transport.objects['/subscriptions/sub_fixture']);alternate['id']='sub_other'
        self.transport.objects['/subscriptions/sub_other']=alternate
        def complete(method,path):
            if method=='POST' and path.endswith('/expire'):
                self.transport.objects['/checkout/sessions/cs_fixture'].update(status='complete',url=None,subscription='sub_other')
        self.transport.callback=complete
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        self.assertFalse(any(c[1]=='/billing_portal/sessions' for c in self.transport.calls))
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_worker_expiry_failure_remains_pending_then_restart_retries_same_key(self):
        self.service.checkout(self.owner,self.team);self.transport.paid();self.webhook()
        self.transport.fail=lambda method,path:method=='POST' and path.endswith('/expire')
        self.assertFalse(self.service.process_next())
        self.assertEqual('pending',self.store.event_state('evt_fixture')['state'])
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])
        self.release_checkout();self.transport.fail=None
        with self.store.db.connect(write=True) as c:c.execute('UPDATE billing_events SET next_attempt=0')
        restarted=self.module.BillingService(BillingStore(self.workspaces,'cloud',self.catalog),self.client,'whsec_fixture','https://coopagents.example')
        self.assertTrue(restarted.process_next())
        self.assertEqual('processed',self.store.event_state('evt_fixture')['state'])
        self.assertEqual('expired',self.transport.objects['/checkout/sessions/cs_fixture']['status'])
        keys=[c[2] for c in self.transport.calls if c[0]=='POST' and c[1].endswith('/expire')]
        self.assertEqual(2,len(keys));self.assertEqual(keys[0],keys[1])

    def test_expiry_uncertain_remote_success_recovers_canonical_expired_without_new_create(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        original=self.transport.__call__
        def timeout_after_expire(method,url,headers,body,timeout,max_bytes):
            result=original(method,url,headers,body,timeout,max_bytes)
            if method=='POST' and urlsplit(url).path.endswith('/expire'):raise TimeoutError('lost response')
            return result
        self.client.transport=timeout_after_expire
        self.assertEqual('portal',self.service.checkout(self.owner,self.team)['kind'])
        self.assertEqual('expired',self.transport.objects['/checkout/sessions/cs_fixture']['status'])
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']))
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1].endswith('/expire')]))

    def test_foreign_canonical_session_never_expires_and_expiry_response_must_match(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        obj=self.transport.objects['/checkout/sessions/cs_fixture'];original=copy.deepcopy(obj)
        for change in [{'customer':'cus_other'},{'livemode':True},{'mode':'payment'},
                {'id':'cs_other'},{'client_reference_id':'other'}, {'success_url':'https://other.example/'}]:
            with self.subTest(change=change):
                obj.clear();obj.update(copy.deepcopy(original));obj.update(change);self.release_checkout()
                with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
                self.assertFalse(any(c[0]=='POST' and c[1].endswith('/expire') for c in self.transport.calls))
        obj.clear();obj.update(original);self.release_checkout()
        transport=self.transport.__call__
        def foreign_response(method,url,headers,body,timeout,max_bytes):
            status,raw=transport(method,url,headers,body,timeout,max_bytes)
            if method=='POST' and urlsplit(url).path.endswith('/expire'):
                value=json.loads(raw);value['customer']='cus_other';raw=json.dumps(value).encode()
            return status,raw
        self.client.transport=foreign_response
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        self.assertFalse(any(c[1]=='/billing_portal/sessions' for c in self.transport.calls))
        self.assertEqual('free',self.store.summary(self.owner,self.team)['plan'])

    def test_portal_reconciliation_expires_existing_competing_session(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        self.assertEqual('portal',self.service.portal(self.owner,self.team)['kind'])
        self.assertEqual('expired',self.transport.objects['/checkout/sessions/cs_fixture']['status'])

    def test_admin_reconciliation_expires_existing_competing_session_without_creation(self):
        self.service.checkout(self.owner,self.team);self.transport.paid()
        # Administrator reconciliation has the same resolver and cannot create
        # a customer or Checkout while closing an already server-bound attempt.
        self.assertTrue(self.service.reconcile_team(self.team))
        self.assertEqual('expired',self.transport.objects['/checkout/sessions/cs_fixture']['status'])
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1].endswith('/expire')]))
        self.assertEqual(1,len([c for c in self.transport.calls if c[0]=='POST' and c[1]=='/checkout/sessions']))

    def test_completed_checkout_foreign_subscription_customer_cannot_bind(self):
        self.service.checkout(self.owner,self.team)
        checkout=self.transport.objects['/checkout/sessions/cs_fixture']
        checkout['status']='complete';checkout['subscription']='sub_foreign';checkout['url']=None
        foreign=self.transport.paid(sub='sub_foreign');foreign['customer']='cus_other'
        with self.assertRaises(StripeError):self.service.checkout(self.owner,self.team)
        with self.store.db.connect() as c:self.assertEqual('open',c.execute('SELECT status FROM billing_checkouts').fetchone()[0])

    def test_remote_expiry_allows_new_attempt_only_after_authoritative_refresh(self):
        self.service.checkout(self.owner,self.team)
        with self.store.db.connect() as c:old=c.execute('SELECT attempt_id,idempotency_key FROM billing_checkouts').fetchone()
        self.transport.objects['/checkout/sessions/cs_fixture']['status']='expired'
        self.transport.objects['/checkout/sessions/cs_fixture']['url']=None
        self.assertEqual('expired',self.service.checkout(self.owner,self.team)['kind'])
        # Inspect a newly reserved domain attempt without making a fixture reuse its fixed cs ID.
        new=self.store.reserve_checkout(self.team)
        self.assertNotEqual(old['attempt_id'],new.attempt_id);self.assertNotEqual(old['idempotency_key'],new.idempotency_key)


if __name__=='__main__':unittest.main()
