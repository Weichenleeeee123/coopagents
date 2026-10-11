"""Canonical Stripe relationship and current invoice risk verification."""
import re

from .billing import SubscriptionSnapshot
from .stripe_billing import StripeError, reference, validate_object

TERMINAL=('canceled','incomplete_expired')
STATUSES=('incomplete','incomplete_expired','trialing','active','past_due','canceled','unpaid','paused')


def integer(value,minimum=0):
    if type(value) is not int or not minimum<=value<=253402300799:
        raise StripeError('invalid_provider_object')
    return value


class SnapshotVerifier:
    def __init__(self,client,catalog):
        self.client=client;self.catalog=catalog

    def customer(self,obj,expected):
        if reference(obj.get('customer'),'cus')!=expected:raise StripeError('provider_relationship')

    def subscription(self,subscription_id,customer):
        obj=self.client.retrieve_subscription(subscription_id)
        self.customer(obj,customer)
        if obj.get('status') not in STATUSES:raise StripeError('invalid_provider_object')
        return obj

    def current(self,customer,previous=None):
        self.client.retrieve_customer(customer)
        values=self.client.list_subscriptions(customer)
        for value in values:self.customer(value,customer)
        current=[o for o in values if o.get('status') not in TERMINAL]
        if len(current)>1:raise StripeError('ambiguous_subscription')
        if current:
            return self.subscription(current[0]['id'],customer)
        if previous and previous.subscription_id:
            return self.subscription(previous.subscription_id,customer)
        if values:
            # Persist only the canonical most recent terminal object. Ordering is verified.
            for value in values:integer(value.get('created'))
            values.sort(key=lambda obj:(obj['created'],obj['id']),reverse=True)
            return self.subscription(values[0]['id'],customer)
        return None

    def snapshot(self,customer,subscription):
        if subscription is None:
            return SubscriptionSnapshot(customer,None,None,self.catalog.provider_mode,'none',None,None,None,False,False)
        validate_object(subscription,'subscription',self.catalog.provider_mode)
        self.customer(subscription,customer)
        status=subscription.get('status')
        if status not in STATUSES or type(subscription.get('cancel_at_period_end')) is not bool:
            raise StripeError('invalid_provider_object')
        items=subscription.get('items')
        if not isinstance(items,dict) or items.get('has_more') is not False or not isinstance(items.get('data'),list) or len(items['data'])!=1:
            raise StripeError('provider_relationship')
        item=items['data'][0]
        if not isinstance(item,dict) or type(item.get('quantity')) is not int or item['quantity']!=1:
            raise StripeError('provider_relationship')
        item_id=reference(item.get('id'),'si')
        price_id=reference(item.get('price'),'price');period_end=integer(item.get('current_period_end'),1)
        period_start=integer(item.get('current_period_start'),1)
        if period_start>=period_end:raise StripeError('provider_relationship')
        if isinstance(item.get('price'),dict):validate_object(item['price'],'price',self.catalog.provider_mode,price_id)
        pause=subscription.get('pause_collection')
        if pause is not None:
            if not isinstance(pause,dict) or pause.get('behavior') not in ('keep_as_draft','mark_uncollectible','void'):
                raise StripeError('invalid_provider_object')
            status='paused'
        invoice_id=reference(subscription['latest_invoice'],'in') if subscription.get('latest_invoice') is not None else None
        paid_id=None;paid_end=None;risk=False
        if invoice_id:
            invoice=self.client.retrieve_invoice(invoice_id);self.customer(invoice,customer)
            parent=invoice.get('parent')
            details=parent.get('subscription_details') if isinstance(parent,dict) else None
            if not isinstance(details,dict) or parent.get('type')!='subscription_details' or reference(details.get('subscription'),'sub')!=subscription['id']:
                raise StripeError('provider_relationship')
            if invoice.get('status') not in ('draft','open','paid','uncollectible','void'):
                raise StripeError('invalid_provider_object')
            if invoice['status']=='paid' and status=='active' and price_id==self.catalog.team_monthly_price_id:
                verified=self.client.verify_price(price_id)
                if invoice.get('currency')!=verified['currency']:raise StripeError('provider_relationship')
                self.verify_invoice_lines(invoice,subscription['id'],item_id,period_start,period_end,verified)
                risk=self.invoice_risk(invoice,customer)
                paid_id=invoice_id;paid_end=period_end
        return SubscriptionSnapshot(customer,subscription['id'],price_id,self.catalog.provider_mode,status,
            invoice_id,paid_id,paid_end,subscription['cancel_at_period_end'],risk)

    def verify_invoice_lines(self,invoice,subscription_id,item_id,period_start,period_end,price):
        """First fixed monthly scope: one full-period non-prorated subscription line."""
        lines=self.client.invoice_lines(invoice['id'])
        if len(lines)!=1:raise StripeError('unsupported_invoice_lines')
        line=lines[0];parent=line.get('parent');pricing=line.get('pricing');period=line.get('period')
        details=parent.get('subscription_item_details') if isinstance(parent,dict) else None
        price_details=pricing.get('price_details') if isinstance(pricing,dict) else None
        if (reference(line.get('invoice'),'in')!=invoice['id'] or line.get('currency')!=price['currency']
            or type(line.get('quantity')) is not int or line['quantity']!=1
            or not isinstance(parent,dict) or parent.get('type')!='subscription_item_details'
            or not isinstance(details,dict) or details.get('proration') is not False
            or reference(details.get('subscription'),'sub')!=subscription_id
            or reference(details.get('subscription_item'),'si')!=item_id
            or not isinstance(pricing,dict) or pricing.get('type')!='price_details'
            or not isinstance(price_details,dict)
            or reference(price_details.get('price'),'price')!=self.catalog.team_monthly_price_id
            or not isinstance(period,dict) or integer(period.get('start'),1)!=period_start
            or integer(period.get('end'),1)!=period_end):
            raise StripeError('provider_relationship')
        if 'quantity_decimal' in line:
            quantity=line['quantity_decimal']
            if not isinstance(quantity,str) or not re.fullmatch(r'1(?:\.0{1,12})?',quantity):
                raise StripeError('provider_relationship')
        integer(line.get('amount'),1)

    def invoice_risk(self,invoice,customer):
        """Require complete, unique paid allocations; external/shared payments fail closed."""
        amount=integer(invoice.get('amount_paid'),1)
        payments=self.client.invoice_payments(invoice['id'])
        paid=0;refunded=0;risk=False;seen=set()
        for payment in payments:
            if reference(payment.get('invoice'),'in')!=invoice['id']:raise StripeError('provider_relationship')
            if payment.get('status') not in ('open','paid','canceled'):raise StripeError('invalid_provider_object')
            if payment['status']!='paid':continue
            allocation=integer(payment.get('amount_paid'),1)
            if payment.get('currency')!=invoice['currency']:raise StripeError('provider_relationship')
            details=payment.get('payment')
            if not isinstance(details,dict):raise StripeError('invalid_provider_object')
            intent_id=None
            if details.get('type')=='payment_intent':
                intent_id=reference(details.get('payment_intent'),'pi')
                intent=self.client.retrieve_payment_intent(intent_id);self.customer(intent,customer)
                if intent.get('status')!='succeeded' or intent.get('currency')!=invoice['currency'] or integer(intent.get('amount_received'),1)!=allocation:
                    raise StripeError('unsupported_payment_allocation')
                charge_id=reference(intent.get('latest_charge'),'ch')
            elif details.get('type')=='charge':charge_id=reference(details.get('charge'),'ch')
            else:raise StripeError('unsupported_payment_record')
            if charge_id in seen:raise StripeError('provider_relationship')
            seen.add(charge_id)
            charge=self.client.retrieve_charge(charge_id);self.customer(charge,customer)
            if (charge.get('currency')!=invoice['currency'] or integer(charge.get('amount_captured'),1)!=allocation
                or charge.get('captured') is not True or charge.get('paid') is not True or charge.get('status')!='succeeded'
                or type(charge.get('refunded')) is not bool or type(charge.get('disputed')) is not bool):
                raise StripeError('unsupported_payment_allocation')
            if intent_id:
                if reference(charge.get('payment_intent'),'pi')!=intent_id:raise StripeError('provider_relationship')
            elif charge.get('payment_intent') is not None:
                intent_id=reference(charge['payment_intent'],'pi')
                intent=self.client.retrieve_payment_intent(intent_id);self.customer(intent,customer)
                if reference(intent.get('latest_charge'),'ch')!=charge_id or intent.get('status')!='succeeded' or intent.get('currency')!=invoice['currency'] or integer(intent.get('amount_received'),1)!=allocation:
                    raise StripeError('provider_relationship')
            refund=integer(charge.get('amount_refunded'))
            if refund>allocation or charge['refunded']!=(refund==allocation):raise StripeError('provider_relationship')
            paid+=allocation;refunded+=refund
            # Always query current disputes, including after prior disputed flag has cleared.
            disputes=self.client.list_disputes(charge_id)
            if charge['disputed'] and not disputes:raise StripeError('risk_assessment_incomplete')
            for dispute in disputes:
                if reference(dispute.get('charge'),'ch')!=charge_id:raise StripeError('provider_relationship')
                if dispute.get('payment_intent') is not None and reference(dispute['payment_intent'],'pi')!=intent_id:
                    raise StripeError('provider_relationship')
                state=dispute.get('status')
                if state not in ('warning_needs_response','warning_under_review','warning_closed','needs_response','under_review','won','lost'):
                    raise StripeError('risk_assessment_incomplete')
                risk=risk or state not in ('won','warning_closed')
        if paid!=amount or not seen:raise StripeError('risk_assessment_incomplete')
        return risk or refunded==amount
