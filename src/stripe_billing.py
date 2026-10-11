"""Bounded Stripe HTTPS adapter and authentication; never stores provider bodies."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
import hashlib
import hmac
import http.client
import json
import re
from queue import Empty, Queue
import threading
import time
from urllib.parse import urlencode, urlsplit

from .errors import AccessDenied

STRIPE_VERSION = '2026-09-30.endive'
MAX_BYTES = 1048576
_budget = ContextVar('stripe_operation_budget', default=None)
_transport_slots = threading.BoundedSemaphore(16)


class StripeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def identifier(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(re.escape(prefix) + r'_[A-Za-z0-9_]{1,200}', value):
        raise StripeError('invalid_provider_object')
    return value


def reference(value, prefix):
    return identifier(value.get('id') if isinstance(value, dict) else value, prefix)


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise StripeError('invalid_provider_json')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(StripeError('invalid_provider_json')))
    except (ValueError, UnicodeError, RecursionError):
        raise StripeError('invalid_provider_json') from None
    if not isinstance(value, dict):
        raise StripeError('invalid_provider_json')
    return value


def validate_object(value, kind, mode, expected=None):
    prefixes = {'customer':'cus','price':'price','subscription':'sub','invoice':'in',
                'checkout.session':'cs','billing_portal.session':'bps','invoice_payment':'inpay',
                'payment_intent':'pi','charge':'ch','refund':'re','dispute':'du','line_item':'il'}
    if not isinstance(value, dict) or value.get('object') != kind:
        raise StripeError('invalid_provider_object')
    actual = identifier(value.get('id'), prefixes[kind])
    if expected is not None and actual != expected:
        raise StripeError('provider_relationship')
    # Refunds have no livemode in the pinned API. The coordinator follows their
    # canonical Charge, which carries mode, customer and PaymentIntent evidence.
    if kind=='refund' and 'livemode' not in value:
        return value
    if type(value.get('livemode')) is not bool or value['livemode'] != (mode == 'live'):
        raise StripeError('provider_mode')
    return value


def hosted_url(value, host):
    if not isinstance(value, str) or len(value)>4096 or any(ord(c)<=32 or ord(c)==127 for c in value):
        raise StripeError('invalid_provider_url')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname != host or parsed.username is not None or
                parsed.password is not None or (parsed.fragment and host!='checkout.stripe.com') or parsed.port not in (None,443) or
                parsed.netloc not in (host,host+':443')):
            raise StripeError('invalid_provider_url')
    except ValueError:
        raise StripeError('invalid_provider_url') from None
    return value


def verify_event(raw: bytes, signature: str, secret: str, mode: str, *, now=None):
    if mode not in ('test','live') or type(raw) is not bytes or len(raw)>MAX_BYTES:
        raise StripeError('invalid_webhook')
    if not isinstance(signature,str) or len(signature)>4096:
        raise StripeError('invalid_signature')
    stamps, signatures = [], []
    for part in signature.split(','):
        key, separator, value = part.strip().partition('=')
        if not separator or not key or not value:
            raise StripeError('invalid_signature')
        if key=='t':
            if not re.fullmatch(r'[1-9][0-9]{0,11}',value):
                raise StripeError('invalid_signature')
            stamps.append(value)
        elif key=='v1':
            if not re.fullmatch(r'[0-9a-f]{64}',value):
                raise StripeError('invalid_signature')
            signatures.append(value)
        elif not re.fullmatch(r'v[0-9]+',key):
            raise StripeError('invalid_signature')
    if len(stamps)!=1 or not signatures or abs((time.time() if now is None else now)-int(stamps[0]))>300:
        raise StripeError('invalid_signature')
    expected=hmac.new(secret.encode('ascii'),stamps[0].encode('ascii')+b'.'+raw,hashlib.sha256).hexdigest()
    valid=False
    for candidate in signatures:
        valid = hmac.compare_digest(expected,candidate) or valid
    if not valid:
        raise StripeError('invalid_signature')
    event=strict_json(raw)
    identifier(event.get('id'),'evt')
    if type(event.get('livemode')) is not bool or event['livemode']!=(mode=='live'):
        raise StripeError('provider_mode')
    kind=event.get('type')
    if not isinstance(kind,str) or not re.fullmatch(r'[a-z][a-z0-9_.]{0,199}',kind):
        raise StripeError('invalid_webhook')
    data=event.get('data'); obj=data.get('object') if isinstance(data,dict) else None
    if not isinstance(obj,dict):
        raise StripeError('invalid_webhook')
    prefix = ('cs' if kind.startswith('checkout.session.') else 'sub' if kind.startswith('customer.subscription.')
              else 'in' if kind.startswith('invoice.') else 'ch' if kind.startswith('charge.refunded')
              else 'du' if kind.startswith('charge.dispute.') else 're' if kind.startswith('refund.') else None)
    object_id=obj.get('id')
    if prefix:
        identifier(object_id,prefix)
    elif not isinstance(object_id,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,200}',object_id):
        raise StripeError('invalid_webhook')
    return dict(event_id=event['id'],event_type=kind,object_id=object_id,provider_mode=mode)


def https_transport(method, url, headers, body, timeout, max_bytes):
    """Bound caller wall time even during DNS/headers; at most 16 physical calls."""
    slots=_transport_slots
    if not slots.acquire(blocking=False):raise StripeError('provider_busy')
    queue=Queue(maxsize=1);context=copy_context();deadline=time.monotonic()+timeout
    def run():
        try:
            result=context.run(_https_request,method,url,headers,body,
                max(0.001,deadline-time.monotonic()),max_bytes)
            queue.put((True,result))
        except Exception as error:
            # Never emit thread exception tracebacks, credentials or provider payloads.
            queue.put((False,error if isinstance(error,(StripeError,AccessDenied)) else StripeError('provider_unavailable')))
        finally:slots.release()
    thread=threading.Thread(target=run,daemon=True,name='crewmesh-stripe')
    try:thread.start()
    except RuntimeError:
        slots.release();raise StripeError('provider_unavailable') from None
    try:
        success,value=queue.get(timeout=max(0,deadline-time.monotonic()))
    except Empty:raise StripeError('provider_unavailable') from None
    if not success:raise value
    return value


def _https_request(method, url, headers, body, timeout, max_bytes):
    """Physical stdlib TLS operation, fixed host, no redirect following."""
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.netloc!='api.stripe.com' or not parsed.path.startswith('/v1/'):
        raise StripeError('invalid_provider_endpoint')
    conn=http.client.HTTPSConnection('api.stripe.com',timeout=timeout)
    deadline=time.monotonic()+timeout
    response=None
    try:
        conn.connect()
        if time.monotonic()>=deadline:raise TimeoutError()
        budget=_budget.get()
        if budget is not None:
            if time.monotonic()>=budget[0]:raise TimeoutError()
            if budget[2] is not None:budget[2]()
        if time.monotonic()>=deadline or budget is not None and time.monotonic()>=budget[0]:raise TimeoutError()
        conn.request(method,parsed.path+('?' + parsed.query if parsed.query else ''),body=body,headers=headers)
        # getresponse() can detach conn.sock for a Connection: close response.
        socket=conn.sock
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError()
        if socket is not None:socket.settimeout(remaining)
        response=conn.getresponse()
        chunks=[];total=0
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise TimeoutError()
            if socket is not None:
                socket.settimeout(remaining)
            chunk=response.read1(min(65536,max_bytes+1-total))
            if not chunk:break
            chunks.append(chunk);total+=len(chunk)
            if total>max_bytes:raise StripeError('provider_response_too_large')
        return response.status,b''.join(chunks)
    finally:
        try:
            if response is not None:response.close()
        finally:conn.close()


class StripeClient:
    def __init__(self, secret_key, mode, *, transport=None, timeout=5, max_pages=4,
                 operation_seconds=45, max_requests=64):
        if mode not in ('test','live') or not isinstance(secret_key,str) or not re.fullmatch('sk_'+mode+r'_[A-Za-z0-9_]{1,250}',secret_key):
            raise StripeError('invalid_configuration')
        if not 0<timeout<=10 or type(max_pages) is not int or not 1<=max_pages<=10 or not 0<operation_seconds<=90 or not 1<=max_requests<=128:
            raise StripeError('invalid_configuration')
        self._secret=secret_key; self.mode=mode; self.transport=transport or https_transport
        self.timeout=timeout;self.max_pages=max_pages
        self.operation_seconds=operation_seconds;self.max_requests=max_requests

    @contextmanager
    def operation(self, authorize=None):
        existing=_budget.get()
        if existing is not None:
            yield
            return
        token=_budget.set([time.monotonic()+self.operation_seconds,0,authorize])
        try:yield
        finally:_budget.reset(token)

    def _request(self, method, path, params=None, key=None):
        budget=_budget.get()
        if budget is None:
            with self.operation():return self._request(method,path,params,key)
        budget[1]+=1
        remaining=budget[0]-time.monotonic()
        if remaining<=0 or budget[1]>self.max_requests:
            raise StripeError('operation_budget')
        if budget[2] is not None:budget[2]()
        remaining=budget[0]-time.monotonic()
        if remaining<=0:raise StripeError('operation_budget')
        if not re.fullmatch(r'/[a-z_]+(?:/[A-Za-z0-9_]+){0,3}',path):
            raise StripeError('invalid_provider_endpoint')
        if method=='POST' and (not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}',key)):
            raise StripeError('invalid_idempotency_key')
        encoded=urlencode(params or {}).encode('ascii')
        url='https://api.stripe.com/v1'+path
        body=encoded if method=='POST' else None
        if method=='GET' and encoded:url+='?'+encoded.decode('ascii')
        headers={'Authorization':'Bearer '+self._secret,'Stripe-Version':STRIPE_VERSION,
                 'Content-Type':'application/x-www-form-urlencoded'}
        if key:headers['Idempotency-Key']=key
        try:
            status,raw=self.transport(method,url,headers,body,min(self.timeout,remaining),MAX_BYTES)
        except AccessDenied:raise
        except StripeError:raise
        except (OSError,TimeoutError,http.client.HTTPException):
            raise StripeError('provider_unavailable') from None
        if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:raise StripeError('provider_response_too_large')
        if 300<=status<400:raise StripeError('provider_redirect')
        if status==429 or status>=500:raise StripeError('provider_unavailable')
        if not 200<=status<300:raise StripeError('provider_rejected')
        if time.monotonic()>budget[0]:raise StripeError('operation_budget')
        return strict_json(raw)

    def _get(self,path,kind,prefix,obj_id):
        identifier(obj_id,prefix)
        return validate_object(self._request('GET',path+'/'+obj_id),kind,self.mode,obj_id)

    def _list(self,path,kind,params):
        result=[];seen=set()
        for _ in range(self.max_pages):
            page=self._request('GET',path,params|{'limit':100})
            if page.get('object')!='list' or type(page.get('has_more')) is not bool or not isinstance(page.get('data'),list) or len(page['data'])>100:
                raise StripeError('invalid_provider_object')
            for obj in page['data']:
                validate_object(obj,kind,self.mode)
                if obj['id'] in seen:raise StripeError('pagination_incomplete')
                seen.add(obj['id']);result.append(obj)
            if not page['has_more']:return result
            if not page['data']:raise StripeError('pagination_incomplete')
            params=params|{'starting_after':page['data'][-1]['id']}
        raise StripeError('pagination_incomplete')

    def create_customer(self,key,team_id):
        obj=self._request('POST','/customers',{'metadata[customer_key]':key,'metadata[team_id]':team_id},key)
        return validate_object(obj,'customer',self.mode)

    def retrieve_customer(self,obj_id):return self._get('/customers','customer','cus',obj_id)
    def find_customer(self,key,team_id):
        customers=self._list('/customers','customer',{})
        matches=[]
        for obj in customers:
            metadata=obj.get('metadata',{})
            if not isinstance(metadata,dict):raise StripeError('invalid_provider_object')
            if metadata.get('customer_key')==key and metadata.get('team_id')==team_id:matches.append(obj)
        if len(matches)!=1:raise StripeError('uncertain_customer')
        return self.retrieve_customer(matches[0]['id'])

    def retrieve_price(self,obj_id):return self._get('/prices','price','price',obj_id)
    def verify_price(self,obj_id):
        obj=self.retrieve_price(obj_id); recurring=obj.get('recurring')
        if (obj.get('active') is not True or obj.get('type')!='recurring' or obj.get('billing_scheme')!='per_unit'
            or obj.get('transform_quantity') is not None
            or type(obj.get('unit_amount')) is not int or obj['unit_amount']<=0
            or not isinstance(obj.get('currency'),str) or not re.fullmatch('[a-z]{3}',obj['currency'])
            or not isinstance(recurring,dict) or recurring.get('interval')!='month'
            or type(recurring.get('interval_count')) is not int or recurring['interval_count']!=1
            or recurring.get('usage_type')!='licensed'):
            raise StripeError('invalid_monthly_price')
        return {'amount':obj['unit_amount'],'currency':obj['currency'],'interval':'month'}

    def create_checkout(self,customer,price,key,attempt_id,origin,*,currency=None):
        identifier(customer,'cus');identifier(price,'price')
        with self.operation():
            # Preserve the legacy call while keeping fallback Price verification
            # and its mutation inside one budget/owner authorization context.
            if currency is None:currency=self.verify_price(price)['currency']
            if not isinstance(currency,str) or not re.fullmatch('[a-z]{3}',currency):
                raise StripeError('invalid_monthly_price')
            obj=self._request('POST','/checkout/sessions',{'mode':'subscription','customer':customer,
                'currency':currency,'adaptive_pricing[enabled]':'false',
                'line_items[0][price]':price,'line_items[0][quantity]':1,'client_reference_id':attempt_id,
                'success_url':origin+'/#billing-return','cancel_url':origin+'/#billing'},key)
        return validate_object(obj,'checkout.session',self.mode)
    def retrieve_checkout(self,obj_id):return self._get('/checkout/sessions','checkout.session','cs',obj_id)
    def list_checkouts(self,customer):
        identifier(customer,'cus');return self._list('/checkout/sessions','checkout.session',{'customer':customer})
    def checkout_items(self,obj_id):
        identifier(obj_id,'cs')
        # Line items have no livemode; verify their canonical nested Price instead.
        page=self._request('GET','/checkout/sessions/'+obj_id+'/line_items',{'limit':2})
        if page.get('object')!='list' or page.get('has_more') is not False or not isinstance(page.get('data'),list) or len(page['data'])!=1 or not isinstance(page['data'][0],dict):
            raise StripeError('provider_relationship')
        return page['data']
    def expire_checkout(self,obj_id,key):
        identifier(obj_id,'cs');return validate_object(self._request('POST','/checkout/sessions/'+obj_id+'/expire',{},key),'checkout.session',self.mode,obj_id)
    def create_portal(self,customer,key,origin):
        identifier(customer,'cus');return validate_object(self._request('POST','/billing_portal/sessions',{'customer':customer,'return_url':origin+'/#billing'},key),'billing_portal.session',self.mode)
    def retrieve_subscription(self,obj_id):return self._get('/subscriptions','subscription','sub',obj_id)
    def list_subscriptions(self,customer):
        identifier(customer,'cus');return self._list('/subscriptions','subscription',{'customer':customer,'status':'all'})
    def retrieve_invoice(self,obj_id):return self._get('/invoices','invoice','in',obj_id)
    def invoice_lines(self,invoice):
        identifier(invoice,'in');return self._list('/invoices/'+invoice+'/lines','line_item',{})
    def invoice_payments(self,invoice):
        identifier(invoice,'in');return self._list('/invoice_payments','invoice_payment',{'invoice':invoice})
    def retrieve_payment_intent(self,obj_id):return self._get('/payment_intents','payment_intent','pi',obj_id)
    def retrieve_charge(self,obj_id):return self._get('/charges','charge','ch',obj_id)
    def retrieve_refund(self,obj_id):return self._get('/refunds','refund','re',obj_id)
    def retrieve_dispute(self,obj_id):return self._get('/disputes','dispute','du',obj_id)
    def list_disputes(self,charge):
        identifier(charge,'ch');return self._list('/disputes','dispute',{'charge':charge})
