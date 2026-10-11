"""One owned durable-event worker; leases/backoff live in BillingStore."""
import asyncio
import logging
from .billing_api import await_owned

logger = logging.getLogger(__name__)


class BillingWorker:
    def __init__(self, billing, runtime, *, poll_seconds=.25):
        self.billing, self.runtime = billing, runtime
        self.poll_seconds = poll_seconds
        self.stop = asyncio.Event()
        self.task = None

    def start(self):
        if self.billing.store.enabled:
            self.task = asyncio.create_task(self.run(), name='crewmesh-billing-events')

    async def run(self):
        while not self.stop.is_set():
            try:
                worked = await self.runtime.process(self.billing.process_next)
            except Exception:
                # Preserve the claimed lease for recovery; exception messages may
                # contain provider secrets or payloads and must never be logged.
                logger.error('Billing worker operation failed; durable lease retained')
                worked = False
            delay = .01 if worked else self.poll_seconds
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def close(self):
        self.stop.set()
        if self.task is not None:
            # Provider work is bounded by its own request/page/time budgets. Do
            # not abandon a thread that could write after lifespan shutdown.
            await await_owned(self.task)
