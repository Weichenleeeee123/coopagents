"""Claimed canonical Checkout creation, recovery and competing-session expiry."""
import time
import re

from .stripe_billing import StripeError, hosted_url, reference, validate_object
from .stripe_snapshot import TERMINAL, integer


class CheckoutResolver:
    def __init__(self,store,client,verifier,origin):
        self.store=store;self.client=client;self.verifier=verifier;self.origin=origin

    def _validate(self,attempt,obj):
        validate_object(obj,'checkout.session',self.client.mode,attempt.checkout_id)
        if (reference(obj.get('customer'),'cus')!=attempt.customer_id or obj.get('mode')!='subscription'
            or obj.get('client_reference_id')!=attempt.attempt_id
            or obj.get('success_url')!=self.origin+'/#billing-return' or obj.get('cancel_url')!=self.origin+'/#billing'):
            raise StripeError('provider_relationship')
        base_currency=self.client.retrieve_price(self.store.catalog.team_monthly_price_id).get('currency')
        if (not isinstance(base_currency,str) or not re.fullmatch('[a-z]{3}',base_currency)
            or obj.get('currency')!=base_currency):raise StripeError('provider_relationship')
        item=self.client.checkout_items(obj['id'])[0]
        if type(item.get('quantity')) is not int or item['quantity']!=1 or reference(item.get('price'),'price')!=self.store.catalog.team_monthly_price_id:
            raise StripeError('provider_relationship')
        if isinstance(item.get('price'),dict):
            validate_object(item['price'],'price',self.client.mode,self.store.catalog.team_monthly_price_id)
        status=obj.get('status')
        if status not in ('open','complete','expired'):raise StripeError('invalid_provider_object')
        subscription=reference(obj['subscription'],'sub') if obj.get('subscription') else None
        if status=='complete' and subscription is None:raise StripeError('provider_relationship')
        if subscription:self.verifier.subscription(subscription,attempt.customer_id)
        url=hosted_url(obj.get('url'),'checkout.stripe.com') if status=='open' else None
        return dict(status=status,checkout_id=obj['id'],checkout_url=url,
            expires_at=integer(obj.get('expires_at'),1),subscription_id=subscription)

    def _record(self,attempt,values):
        if not self.store.update_checkout(attempt,**values):raise StripeError('checkout_busy')

    def _retrieve(self,attempt,*,create,currency=None):
        if attempt.checkout_id:return self.client.retrieve_checkout(attempt.checkout_id)
        if not create or int(time.time())-attempt.created_at>=86400:
            matches=[o for o in self.client.list_checkouts(attempt.customer_id)
                if o.get('client_reference_id')==attempt.attempt_id]
            if len(matches)!=1:raise StripeError('uncertain_checkout')
            return self.client.retrieve_checkout(matches[0]['id'])
        return self.client.create_checkout(attempt.customer_id,self.store.catalog.team_monthly_price_id,
            attempt.idempotency_key,attempt.attempt_id,self.origin,currency=currency)

    def resolve_competing(self,team_id,snapshot):
        if snapshot.status in TERMINAL+('none',):return
        attempt=self.store.reserve_checkout(team_id,refresh=True,existing_only=True,lease_seconds=120)
        if attempt is None:return
        if not attempt.claimed:
            # Complete has a domain confirmation cooldown but no active writer
            # lease. Applying the matching snapshot below confirms it atomically.
            if (attempt.status=='complete' and attempt.lease_token is None and
                attempt.subscription_id==snapshot.subscription_id):return
            raise StripeError('checkout_busy')
        obj=self._retrieve(attempt,create=False)
        values=self._validate(attempt,obj)
        if values['status']=='open':
            try:
                expired=self.client.expire_checkout(obj['id'],'expire_'+attempt.idempotency_key)
            except StripeError as error:
                # A timeout or completion race can follow a successful remote
                # mutation. Only a fresh canonical terminal response resolves it.
                if error.code not in ('provider_rejected','provider_unavailable','provider_busy'):raise
                expired=self.client.retrieve_checkout(obj['id'])
                if expired.get('status')=='open':raise error
            if expired['id']!=obj['id']:raise StripeError('provider_relationship')
            values=self._validate(attempt,expired)
            if values['status']=='open':raise StripeError('checkout_expiry_pending')
        if values['status']=='complete' and values['subscription_id']!=snapshot.subscription_id:
            raise StripeError('checkout_reconcile_required')
        self._record(attempt,values)

    def start(self,team_id,*,currency=None):
        attempt=self.store.reserve_checkout(team_id,refresh=True,lease_seconds=120)
        if not attempt.claimed:raise StripeError('checkout_busy')
        values=self._validate(attempt,self._retrieve(attempt,create=True,currency=currency))
        self._record(attempt,values)
        return {'kind':'checkout' if values['status']=='open' else values['status'],'url':values['checkout_url']}
