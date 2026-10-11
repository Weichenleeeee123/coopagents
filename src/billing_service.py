"""Account-authorized billing orchestration and durable canonical event worker."""
import re
import time

from .billing_operations import BillingOperations
from .billing_checkout import CheckoutResolver
from .config import public_origin
from .errors import Conflict
from .stripe_billing import StripeError, hosted_url, reference, verify_event
from .stripe_snapshot import SnapshotVerifier, TERMINAL


class BillingService:
    def __init__(self,store,client,webhook_secret,canonical_origin):
        self.store=store;self.client=client;self.webhook_secret=webhook_secret
        self.origin=None
        if store.enabled:
            self.origin=public_origin(canonical_origin)
            if client is None or client.mode!=store.catalog.provider_mode or not isinstance(webhook_secret,str) or not re.fullmatch(r'whsec_[A-Za-z0-9_]{1,250}',webhook_secret):
                raise ValueError('Enabled billing needs matching provider configuration')
            self.operations=BillingOperations(store)
            self.verifier=SnapshotVerifier(client,store.catalog)
            self.checkouts=CheckoutResolver(store,client,self.verifier,self.origin)

    def _enabled(self):
        if not self.store.enabled:raise Conflict('Subscriptions are not enabled')

    def summary(self,session_token,team_id):
        summary=self.store.summary(session_token,team_id)
        if not self.store.enabled:return summary
        price=None;error=None
        try:
            # Membership may change while the provider responds; resolve again below.
            with self.client.operation(lambda:self.store.summary(session_token,team_id)):
                price=self.client.verify_price(self.store.catalog.team_monthly_price_id)
        except StripeError as failure:error=failure.code
        summary=self.store.summary(session_token,team_id)
        return summary|dict(price=price,price_error=error,checkout_available=price is not None and summary['can_manage'])

    def _customer(self,team_id):
        state=self.store.customer_state(team_id)
        if state['customer_id']:
            self.client.retrieve_customer(state['customer_id'])
            return state['customer_id']
        operation=self.operations.reserve(team_id,'customer',key=state['customer_key'])
        latest=self.store.customer_state(team_id)
        if latest['customer_id']:
            customer=self.client.retrieve_customer(latest['customer_id'])
            self.operations.complete(operation,customer['id'])
            return customer['id']
        if int(time.time())-operation['created_at']>=86400:
            customer=self.client.find_customer(state['customer_key'],team_id)
        else:customer=self.client.create_customer(state['customer_key'],team_id)
        metadata=customer.get('metadata')
        if not isinstance(metadata,dict) or metadata.get('customer_key')!=state['customer_key'] or metadata.get('team_id')!=team_id:
            raise StripeError('provider_relationship')
        self.store.bind_customer(team_id,customer['id'],provider_mode=self.client.mode)
        self.operations.complete(operation,customer['id'])
        return customer['id']

    def _sync(self,team_id,job=None):
        previous=self.store.current_snapshot(team_id)
        # The old binding must become canonically terminal before the domain permits replacement.
        if previous and previous.subscription_id and previous.status not in TERMINAL+('none',):
            preclaim=self.store.start_sync(team_id)
            try:
                old=self.verifier.subscription(previous.subscription_id,preclaim.customer_id)
                if old['status'] in TERMINAL:
                    snapshot=self.verifier.snapshot(preclaim.customer_id,old)
                    if not self.store.apply_snapshot(preclaim,snapshot):raise StripeError('sync_superseded')
                    previous=snapshot
            except StripeError as error:
                self.store.fail_sync(preclaim,error.code,retry_delay=self._retry(job))
                raise
        claim=self.store.start_sync(team_id,job=job)
        try:
            current=self.verifier.current(claim.customer_id,previous)
            snapshot=self.verifier.snapshot(claim.customer_id,current)
            self.checkouts.resolve_competing(team_id,snapshot)
            if not self.store.apply_snapshot(claim,snapshot):raise StripeError('sync_superseded')
            return snapshot
        except StripeError as error:
            self.store.fail_sync(claim,error.code,retry_delay=self._retry(job))
            raise
        except Conflict:
            self.store.fail_sync(claim,'provider_relationship',retry_delay=self._retry(job))
            raise

    @staticmethod
    def _retry(job):return min(3600,30*(2**min((job.attempts-1) if job else 0,7)))

    def sync(self,session_token,team_id):
        self._enabled();self.store.require_owner(session_token,team_id)
        with self.client.operation(lambda:self.store.require_owner(session_token,team_id)):
            self._customer(team_id);self._sync(team_id)
        self.store.require_owner(session_token,team_id)
        return self.store.summary(session_token,team_id)

    def reconcile_team(self,team_id):
        """Trusted worker/admin operation; team must already have a server binding."""
        self._enabled()
        state=self.store.customer_state(team_id)
        if not state['customer_id']:raise Conflict('Billing customer must be bound first')
        with self.client.operation():self._sync(team_id)
        return True

    def _portal(self,team_id,customer):
        operation=self.operations.reserve(team_id,'portal')
        # Portal has no canonical retrieval API. An uncertain old create requires admin recovery.
        if int(time.time())-operation['created_at']>=86400:raise StripeError('uncertain_portal')
        obj=self.client.create_portal(customer,operation['idempotency_key'],self.origin)
        if reference(obj.get('customer'),'cus')!=customer or obj.get('return_url')!=self.origin+'/#billing':
            raise StripeError('provider_relationship')
        url=hosted_url(obj.get('url'),'billing.stripe.com')
        self.operations.complete(operation,obj['id'])
        return {'kind':'portal','url':url}

    def portal(self,session_token,team_id):
        self._enabled();self.store.require_owner(session_token,team_id)
        with self.client.operation(lambda:self.store.require_owner(session_token,team_id)):
            customer=self._customer(team_id)
            self._sync(team_id)
            result=self._portal(team_id,customer)
        self.store.require_owner(session_token,team_id)
        return result

    def checkout(self,session_token,team_id):
        self._enabled();authorize=lambda:self.store.require_owner(session_token,team_id)
        authorize()
        with self.client.operation(authorize):
            price=self.client.verify_price(self.store.catalog.team_monthly_price_id)
            customer=self._customer(team_id)
            current=self._sync(team_id)
            if current.status not in TERMINAL+('none',):
                result=self._portal(team_id,customer)
            else:
                result=self.checkouts.start(team_id,currency=price['currency'])
                if result['kind']=='complete':
                    current=self._sync(team_id)
                    if current.subscription_id is None:raise StripeError('checkout_reconcile_required')
                    result=self._portal(team_id,customer)
        authorize()
        return result

    def ingest_webhook(self,raw,signature):
        self._enabled()
        event=verify_event(raw,signature,self.webhook_secret,self.client.mode)
        return self.store.ingest_event(event.pop('event_id'),**event)

    @staticmethod
    def _supported(kind):
        return (kind.startswith('customer.subscription.') or kind.startswith('invoice.') or
            kind.startswith('checkout.session.') or kind=='charge.refunded' or kind.startswith('refund.') or
            kind.startswith('charge.dispute.'))

    def _event_customer(self,job):
        kind=job.event_type
        if kind.startswith('customer.subscription.'):obj=self.client.retrieve_subscription(job.object_id)
        elif kind.startswith('invoice.'):obj=self.client.retrieve_invoice(job.object_id)
        elif kind.startswith('checkout.session.'):obj=self.client.retrieve_checkout(job.object_id)
        elif kind=='charge.refunded':obj=self.client.retrieve_charge(job.object_id)
        elif kind.startswith('refund.'):
            refund=self.client.retrieve_refund(job.object_id)
            obj=self.client.retrieve_charge(reference(refund.get('charge'),'ch'))
            if refund.get('payment_intent') is not None and reference(refund['payment_intent'],'pi')!=reference(obj.get('payment_intent'),'pi'):
                raise StripeError('provider_relationship')
        else:
            dispute=self.client.retrieve_dispute(job.object_id)
            obj=self.client.retrieve_charge(reference(dispute.get('charge'),'ch'))
            if dispute.get('payment_intent') is not None and reference(dispute['payment_intent'],'pi')!=reference(obj.get('payment_intent'),'pi'):
                raise StripeError('provider_relationship')
        # Standalone canonical Charges may have no Customer. Such charges (also
        # reached through Refund/Dispute) cannot belong to a team customer binding.
        # Keep required-customer subscription/invoice/Checkout objects strict, and
        # distinguish an explicit nullable field from malformed/missing evidence.
        if (obj.get('object')=='charge' and 'customer' in obj and obj['customer'] is None and
            (kind=='charge.refunded' or kind.startswith('refund.') or kind.startswith('charge.dispute.'))):
            return None
        customer=reference(obj.get('customer'),'cus')
        canonical=self.client.retrieve_customer(customer)
        team=self.store.team_for_customer(customer,provider_mode=self.client.mode)
        if team is None:
            metadata=canonical.get('metadata')
            key=metadata.get('customer_key') if isinstance(metadata,dict) else None
            pending=self.operations.pending_customer_team(key)
            if pending is not None:
                if metadata.get('team_id')!=pending:raise StripeError('provider_relationship')
                operation=self.operations.customer_operation(pending)
                if operation is None or operation['idempotency_key']!=key:
                    raise StripeError('customer_binding_pending')
                # A unique canonical lookup recovers a remote create whose process
                # crashed before local binding, without another create or owner action.
                recovered=self.client.find_customer(key,pending)
                if recovered['id']!=customer or recovered.get('metadata')!=metadata:
                    raise StripeError('provider_relationship')
                self.store.bind_customer(pending,customer,provider_mode=self.client.mode)
                self.operations.complete(operation,customer)
                team=pending
            else:
                # A concurrent owner/worker can bind between the two local reads.
                team=self.store.team_for_customer(customer,provider_mode=self.client.mode)
        return team

    def process_next(self):
        if not self.store.enabled:return False
        job=self.store.claim_job(lease_seconds=120)
        if job is None:return False
        if not self._supported(job.event_type):
            self.store.ignore_job(job,'unsupported_event');return True
        try:
            with self.client.operation():
                team=self._event_customer(job)
                if team is None:
                    self.store.ignore_job(job,'unrelated_customer');return True
                self._sync(team,job)
            return True
        except StripeError as error:
            # retry_job writes only this event. _sync has already guarded any team failure.
            self.store.retry_job(job,error.code,retry_delay=self._retry(job))
            return False
        except Conflict:
            self.store.retry_job(job,'provider_relationship',retry_delay=self._retry(job))
            return False
