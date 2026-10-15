"""Strict account billing routes and isolated, bounded blocking work."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
import re
import threading
from starlette.responses import JSONResponse
from starlette.routing import Route
from .account_api import cookie_token
from .billing import BillingCatalog
from .billing_config import BillingConfig
from .errors import AccessDenied, ValidationError
from .stripe_billing import StripeError


class BillingBusy(Exception):
    pass


def billing_catalog(mode, config, origin):
    """Validate explicit configuration before creating a database or provider client."""
    if mode == 'self-hosted':
        return None
    if config is None:
        return None
    if not isinstance(config, BillingConfig) or type(config.enabled) is not bool:
        raise ValueError('Invalid billing configuration')
    if not config.enabled:
        return None
    if (not origin or not origin.startswith('https://') or not isinstance(config.catalog, BillingCatalog)
            or not re.fullmatch(r'price_[A-Za-z0-9_]{1,200}', config.catalog.team_monthly_price_id)
            or not isinstance(config.secret_key, str)
            or not re.fullmatch('sk_' + config.catalog.provider_mode + r'_[A-Za-z0-9_]{1,250}', config.secret_key)
            or not isinstance(config.webhook_secret, str)
            or not re.fullmatch(r'whsec_[A-Za-z0-9_]{1,250}', config.webhook_secret)):
        raise ValueError('Enabled billing requires valid provider configuration and an HTTPS public origin')
    return config.catalog


class BillingRuntime:
    """Separate provider, webhook, and worker pools; never queue unbounded HTTP work."""
    def __init__(self):
        self.providers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='coopagents-billing-http')
        self.ingestion = ThreadPoolExecutor(max_workers=2, thread_name_prefix='coopagents-billing-ingest')
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='coopagents-billing-worker')
        self.provider_slots = threading.BoundedSemaphore(2)
        self.ingestion_slots = threading.BoundedSemaphore(2)
        self.closed = False

    async def execute(self, method, *args, ingestion=False):
        slots = self.ingestion_slots if ingestion else self.provider_slots
        if self.closed or not slots.acquire(blocking=False):
            raise BillingBusy()
        try:
            return await self._run(self.ingestion if ingestion else self.providers, method, *args)
        finally:
            slots.release()

    async def process(self, method):
        return await self._run(self.worker, method)

    @staticmethod
    async def _run(pool, method, *args):
        future = asyncio.wrap_future(pool.submit(copy_context().run, method, *args))
        return await await_owned(future)

    async def close(self):
        self.closed = True
        cancelled = False
        for pool in (self.providers, self.ingestion, self.worker):
            try:
                await await_owned(asyncio.create_task(asyncio.to_thread(pool.shutdown, wait=True)))
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError()


async def await_owned(future):
    """Repeated cancellation cannot release capacity while physical work runs."""
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError:
            # A future cancelled by its owner is already finished. This helper
            # itself never cancels the underlying work.
            if future.cancelled():
                raise
            cancelled = True
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError() from None
            raise
    if cancelled:
        raise asyncio.CancelledError()
    return result


def billing_routes(service, runtime, *, origin):
    from .api import error_payload, validate
    billing = service.billing

    async def handle(request):
        try:
            token = cookie_token(request)
            if request.method == 'POST':
                expected = origin or str(request.base_url).rstrip('/')
                if request.headers.getlist('origin') != [expected]:
                    return JSONResponse({'error': 'AccessDenied', 'message': 'Origin not accepted'}, status_code=403)
                csrf = request.headers.getlist('x-coopagents-csrf')
                if len(csrf) != 1:
                    raise AccessDenied('CSRF credential required')
                if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    raise ValidationError('Content type must be application/json')
                try:
                    data = json.loads(await request.body())
                except (ValueError, UnicodeError):
                    raise ValidationError('Malformed JSON') from None
                validate(data, {})
                def operation():
                    service.accounts.authenticate(token, csrf[0])
                    billing.store.require_owner(token, request.path_params['team_id'])
                    return getattr(billing, request.scope['billing_operation'])(token, request.path_params['team_id'])
            else:
                def operation():
                    return billing.summary(token, request.path_params['team_id'])
            return JSONResponse(await runtime.execute(operation))
        except BillingBusy:
            return JSONResponse({'error': 'Busy', 'message': 'Billing busy; try again later'}, status_code=503)
        except StripeError:
            return JSONResponse({'error': 'BillingUnavailable', 'message': 'Billing provider unavailable; try again later'}, status_code=503)
        except Exception as error:
            # Authorization errors never expire a still-valid account session.
            payload, status = error_payload(error)
            return JSONResponse(payload, status_code=status)

    prefix = '/account/teams/{team_id}/billing'
    result = [Route(prefix, handle, methods=['GET'])]
    for name in ('checkout', 'portal', 'sync'):
        async def endpoint(request, name=name):
            request.scope['billing_operation'] = name
            return await handle(request)
        result.append(Route(prefix + '/' + name, endpoint, methods=['POST']))

    if billing.store.enabled:
        async def webhook(request):
            try:
                signatures = request.headers.getlist('stripe-signature')
                if len(signatures) != 1:
                    raise StripeError('invalid_signature')
                raw = await request.body()
                await runtime.execute(billing.ingest_webhook, raw, signatures[0], ingestion=True)
                return JSONResponse({'received': True})
            except BillingBusy:
                return JSONResponse({'error': 'Busy', 'message': 'Billing busy; try again later'}, status_code=503)
            except StripeError as error:
                # These stable codes contain no provider payload, IDs, or secrets.
                code = error.code if error.code in ('invalid_signature', 'invalid_provider_json', 'invalid_webhook',
                    'invalid_provider_object', 'provider_mode', 'invalid_provider_identifier') else 'invalid_webhook'
                return JSONResponse({'error': 'InvalidWebhook', 'message': 'Webhook not accepted', 'code': code}, status_code=400)
            except Exception as error:
                payload, status = error_payload(error)
                return JSONResponse(payload, status_code=status)
        result.append(Route('/billing/stripe/webhook', webhook, methods=['POST']))
    return result
