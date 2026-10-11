"""Transactional billing ledger and quotas. Provider I/O belongs to the adapter.

Only summary/require_owner take account credentials. All remaining billing methods
are trusted server-internal operations, never direct request-body passthroughs.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .errors import AccessDenied, Conflict, ValidationError
from .workspaces import WorkspaceStore


def _identifier(value: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}', value):
        raise ValidationError('Invalid billing identifier')
    return value


def _integer(value: int, minimum: int = 0, maximum: int = 253402300799) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError('Invalid billing integer')
    return value


def _mode(value: str) -> str:
    if value not in ('test', 'live'):
        raise ValidationError('Invalid provider mode')
    return value


@dataclass(frozen=True)
class BillingCatalog:
    free_members: int
    free_projects: int
    team_members: int
    team_projects: int
    team_monthly_price_id: str
    provider_mode: str

    def __post_init__(self):
        for value in (self.free_members, self.free_projects, self.team_members, self.team_projects):
            _integer(value, 1, 1000000000)
        if self.team_members < self.free_members or self.team_projects < self.free_projects:
            raise ValidationError('Team limits must cover Free limits')
        _identifier(self.team_monthly_price_id)
        _mode(self.provider_mode)


@dataclass(frozen=True)
class SubscriptionSnapshot:
    """Canonical provider state, including the invoice actually verified as paid.

    paid_period_end comes from the configured subscription item's billing period.
    A historical paid invoice must never be substituted for current_invoice_id.
    """
    customer_id: str
    subscription_id: str | None
    price_id: str | None
    provider_mode: str
    status: str
    current_invoice_id: str | None
    paid_invoice_id: str | None
    paid_period_end: int | None
    cancel_at_period_end: bool
    risk_hold: bool

    def __post_init__(self):
        _identifier(self.customer_id)
        for value in (self.subscription_id, self.price_id, self.current_invoice_id, self.paid_invoice_id):
            _identifier(value, optional=True)
        _mode(self.provider_mode)
        if self.status not in ('none', 'incomplete', 'incomplete_expired', 'trialing', 'active',
                               'past_due', 'canceled', 'unpaid', 'paused'):
            raise ValidationError('Invalid subscription status')
        if self.paid_period_end is not None:
            _integer(self.paid_period_end)
        if type(self.cancel_at_period_end) is not bool or type(self.risk_hold) is not bool:
            raise ValidationError('Billing flags must be booleans')
        if (self.subscription_id is None) != (self.status == 'none'):
            raise ValidationError('Subscription status and ID do not match')
        if self.subscription_id is None and any(value is not None for value in (
                self.price_id, self.current_invoice_id, self.paid_invoice_id, self.paid_period_end)):
            raise ValidationError('Absent subscription cannot carry paid state')


@dataclass(frozen=True)
class CheckoutReservation:
    attempt_id: str
    team_id: str
    customer_id: str
    idempotency_key: str
    created_at: int
    status: str
    claimed: bool
    lease_token: str | None
    lease_until: int
    checkout_id: str | None
    checkout_url: str | None
    expires_at: int | None
    subscription_id: str | None


@dataclass(frozen=True)
class EventJob:
    event_id: str
    event_type: str
    object_id: str
    provider_mode: str
    customer_id: str | None
    subscription_id: str | None
    attempts: int
    lease_token: str
    lease_until: int


@dataclass(frozen=True)
class SyncClaim:
    team_id: str
    customer_id: str
    provider_mode: str
    generation: int
    lease_token: str
    lease_until: int
    job: EventJob | None = None


class BillingStore:
    def __init__(self, workspaces: WorkspaceStore, mode: str = 'self-hosted',
                 catalog: BillingCatalog | None = None):
        if mode not in ('self-hosted', 'cloud') or (catalog is not None and not isinstance(catalog, BillingCatalog)):
            raise ValidationError('Invalid billing configuration')
        self.workspaces, self.accounts, self.db = workspaces, workspaces.accounts, workspaces.db
        self.mode, self.catalog = mode, catalog
        self.enabled = mode == 'cloud' and catalog is not None
        self.catalog_id = None
        with self.db.connect(write=True) as c:
            for sql in (
                '''CREATE TABLE IF NOT EXISTS billing_catalogs(
                    id TEXT PRIMARY KEY,configuration TEXT NOT NULL,created_at INTEGER NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS billing_teams(
                    team_id TEXT PRIMARY KEY REFERENCES teams(id),provider_mode TEXT NOT NULL,
                    customer_id TEXT,customer_key TEXT NOT NULL UNIQUE,created_at INTEGER NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,sync_token TEXT,sync_until INTEGER NOT NULL DEFAULT 0,
                    last_sync INTEGER,last_error TEXT,catalog_id TEXT REFERENCES billing_catalogs(id),
                    UNIQUE(provider_mode,customer_id))''',
                '''CREATE TABLE IF NOT EXISTS billing_subscription_bindings(
                    provider_mode TEXT NOT NULL,subscription_id TEXT NOT NULL,
                    team_id TEXT NOT NULL REFERENCES teams(id),PRIMARY KEY(provider_mode,subscription_id))''',
                '''CREATE TABLE IF NOT EXISTS billing_subscriptions(
                    team_id TEXT PRIMARY KEY REFERENCES billing_teams(team_id),provider_mode TEXT NOT NULL,
                    customer_id TEXT NOT NULL,subscription_id TEXT,price_id TEXT,status TEXT NOT NULL,
                    current_invoice_id TEXT,paid_invoice_id TEXT,paid_period_end INTEGER,
                    cancel_at_period_end INTEGER NOT NULL,risk_hold INTEGER NOT NULL,
                    synced_at INTEGER NOT NULL,generation INTEGER NOT NULL,
                    UNIQUE(provider_mode,subscription_id))''',
                '''CREATE TABLE IF NOT EXISTS billing_checkouts(
                    attempt_id TEXT PRIMARY KEY,team_id TEXT NOT NULL REFERENCES billing_teams(team_id),
                    customer_id TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,created_at INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','open','complete','expired','confirmed')),
                    lease_token TEXT,lease_until INTEGER NOT NULL,checkout_id TEXT UNIQUE,checkout_url TEXT,
                    expires_at INTEGER,subscription_id TEXT)''',
                '''CREATE UNIQUE INDEX IF NOT EXISTS billing_one_unresolved_checkout ON billing_checkouts(team_id)
                    WHERE status IN ('pending','open','complete')''',
                '''CREATE TABLE IF NOT EXISTS billing_events(
                    event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,object_id TEXT NOT NULL,
                    provider_mode TEXT NOT NULL,customer_id TEXT,subscription_id TEXT,
                    state TEXT NOT NULL CHECK(state IN ('pending','processing','processed','ignored')),
                    received_at INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt INTEGER NOT NULL DEFAULT 0,lease_token TEXT,lease_until INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,processed_at INTEGER,team_id TEXT REFERENCES teams(id))''',
                '''CREATE INDEX IF NOT EXISTS billing_pending_events ON billing_events(state,next_attempt,lease_until)''',
                '''CREATE TABLE IF NOT EXISTS billing_audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,team_id TEXT,event_id TEXT,action TEXT NOT NULL,
                    result TEXT NOT NULL,generation INTEGER,created_at INTEGER NOT NULL)''',
            ):
                c.execute(sql)
            if self.enabled:
                configuration = json.dumps(asdict(catalog), sort_keys=True, separators=(',', ':'))
                self.catalog_id = hashlib.sha256(configuration.encode('utf-8')).hexdigest()
                c.execute('INSERT OR IGNORE INTO billing_catalogs VALUES(?,?,?)', (self.catalog_id, configuration, int(time.time())))
                if c.execute('SELECT 1 FROM billing_teams WHERE provider_mode<>? LIMIT 1', (catalog.provider_mode,)).fetchone():
                    raise ValidationError('Existing billing bindings use a different provider mode')
        # This hook uses the caller's BEGIN IMMEDIATE transaction, never another connection.
        workspaces.capacity_check = self.check_capacity

    def _enabled(self) -> None:
        if not self.enabled:
            raise Conflict('Subscriptions are not enabled')

    def _provider_mode(self, value: str) -> None:
        self._enabled()
        if _mode(value) != self.catalog.provider_mode:
            raise ValidationError('Provider mode does not match billing configuration')

    def _audit(self, c: sqlite3.Connection, action: str, result: str, *, team_id: str | None = None,
               event_id: str | None = None, generation: int | None = None) -> None:
        c.execute('INSERT INTO billing_audit(team_id,event_id,action,result,generation,created_at) VALUES(?,?,?,?,?,?)',
                  (team_id, event_id, action, result, generation, int(time.time())))

    def _ensure_team(self, c: sqlite3.Connection, team_id: str) -> sqlite3.Row:
        self._enabled()
        _identifier(team_id)
        if not c.execute('SELECT 1 FROM teams WHERE id=?', (team_id,)).fetchone():
            raise AccessDenied('Team not available')
        c.execute('''INSERT OR IGNORE INTO billing_teams(team_id,provider_mode,customer_key,created_at,catalog_id)
            VALUES(?,?,?,?,?)''', (team_id, self.catalog.provider_mode, f'customer_{uuid4()}', int(time.time()), self.catalog_id))
        row = c.execute('SELECT * FROM billing_teams WHERE team_id=?', (team_id,)).fetchone()
        self._provider_mode(row['provider_mode'])
        return row

    def require_owner(self, session_token: str, team_id: str) -> dict:
        with self.db.connect() as c:
            account = self.accounts.resolve(c, session_token)
            if self.workspaces._role(c, team_id, account['id']) != 'owner':
                raise AccessDenied('Team owner required for billing')
            return account

    def _entitlement(self, c: sqlite3.Connection, team_id: str) -> tuple[bool, dict, sqlite3.Row | None]:
        if not self.enabled:
            return False, {'members': None, 'projects': None}, None
        row = c.execute('SELECT * FROM billing_subscriptions WHERE team_id=?', (team_id,)).fetchone()
        binding = c.execute('''SELECT t.customer_id,b.subscription_id FROM billing_teams t
            JOIN billing_subscription_bindings b ON b.team_id=t.team_id AND b.provider_mode=t.provider_mode
            WHERE t.team_id=? AND b.subscription_id=? AND t.provider_mode=?''',
            (team_id, row['subscription_id'] if row else None, self.catalog.provider_mode)).fetchone()
        paid = bool(row and row['provider_mode'] == self.catalog.provider_mode
                    and binding and row['customer_id'] == binding['customer_id']
                    and row['price_id'] == self.catalog.team_monthly_price_id and row['status'] == 'active'
                    and row['current_invoice_id'] and row['paid_invoice_id'] == row['current_invoice_id']
                    and row['paid_period_end'] and row['paid_period_end'] > int(time.time()) and not row['risk_hold'])
        limits = {'members': self.catalog.team_members if paid else self.catalog.free_members,
                  'projects': self.catalog.team_projects if paid else self.catalog.free_projects}
        return paid, limits, row

    def _usage(self, c: sqlite3.Connection, team_id: str) -> dict[str, int]:
        return {'members': c.execute('SELECT count(*) FROM team_members WHERE team_id=? AND active=1', (team_id,)).fetchone()[0],
                'projects': c.execute('SELECT count(*) FROM team_projects WHERE team_id=?', (team_id,)).fetchone()[0]}

    def summary(self, session_token: str, team_id: str) -> dict:
        with self.db.connect() as c:
            role = self.workspaces._role(c, team_id, self.accounts.resolve(c, session_token)['id'])
            paid, limits, sub = self._entitlement(c, team_id)
            usage = self._usage(c, team_id)
            binding = c.execute('SELECT * FROM billing_teams WHERE team_id=?', (team_id,)).fetchone() if self.enabled else None
            result = {'team_id': team_id, 'mode': self.mode, 'enabled': self.enabled,
                      'plan': ('team' if paid else 'free') if self.enabled else 'unlimited', 'paid': paid,
                      'limits': limits, 'usage': usage, 'can_manage': role == 'owner',
                      'over_limit': {key: limits[key] is not None and usage[key] > limits[key] for key in limits},
                      'status': sub['status'] if sub else ('unsubscribed' if self.enabled else 'disabled'),
                      'paid_until': sub['paid_period_end'] if paid else None,
                      'cancel_at_period_end': bool(sub and sub['cancel_at_period_end']),
                      'risk_hold': bool(sub and sub['risk_hold']),
                      'last_sync': binding['last_sync'] if binding else None}
            if role == 'owner' and self.enabled:
                result['billing'] = {'customer_id': binding['customer_id'] if binding else None,
                                     'subscription_id': sub['subscription_id'] if sub else None,
                                     'provider_mode': self.catalog.provider_mode,
                                     'last_error': binding['last_error'] if binding else None}
            return result

    def check_capacity(self, c: sqlite3.Connection, team_id: str, resource: str) -> None:
        if resource not in ('members', 'projects'):
            raise ValidationError('Invalid quota resource')
        if not self.enabled:
            return
        _, limits, _ = self._entitlement(c, team_id)
        if self._usage(c, team_id)[resource] >= limits[resource]:
            raise Conflict(f'Team {resource} limit reached')

    def customer_state(self, team_id: str) -> dict:
        with self.db.connect(write=True) as c:
            row = self._ensure_team(c, team_id)
            return {key: row[key] for key in ('team_id', 'provider_mode', 'customer_id', 'customer_key', 'created_at')}

    def bind_customer(self, team_id: str, customer_id: str, *, provider_mode: str) -> dict:
        self._provider_mode(provider_mode)
        _identifier(customer_id)
        with self.db.connect(write=True) as c:
            row = self._ensure_team(c, team_id)
            if row['customer_id'] not in (None, customer_id):
                raise Conflict('Team already has a different billing customer')
            try:
                c.execute('UPDATE billing_teams SET customer_id=? WHERE team_id=?', (customer_id, team_id))
            except sqlite3.IntegrityError:
                raise Conflict('Billing customer is already bound') from None
            self._audit(c, 'bind_customer', 'bound', team_id=team_id)
            return {'team_id': team_id, 'customer_id': customer_id, 'provider_mode': provider_mode}

    def team_for_customer(self, customer_id: str, *, provider_mode: str) -> str | None:
        self._provider_mode(provider_mode)
        _identifier(customer_id)
        with self.db.connect() as c:
            row = c.execute('SELECT team_id FROM billing_teams WHERE provider_mode=? AND customer_id=?',
                            (provider_mode, customer_id)).fetchone()
            return row['team_id'] if row else None

    def current_snapshot(self, team_id: str) -> SubscriptionSnapshot | None:
        """Read the last verified provider state for trusted reconciliation code."""
        self._enabled()
        _identifier(team_id)
        with self.db.connect() as c:
            if not c.execute('SELECT 1 FROM teams WHERE id=?', (team_id,)).fetchone():
                raise AccessDenied('Team not available')
            row = c.execute('SELECT * FROM billing_subscriptions WHERE team_id=?', (team_id,)).fetchone()
            if row is None:
                return None
            return SubscriptionSnapshot(row['customer_id'], row['subscription_id'], row['price_id'],
                                        row['provider_mode'], row['status'], row['current_invoice_id'],
                                        row['paid_invoice_id'], row['paid_period_end'],
                                        bool(row['cancel_at_period_end']), bool(row['risk_hold']))

    def list_bound_teams(self, *, limit: int = 100, after_team_id: str | None = None) -> list[dict]:
        """Bounded keyset inventory for internal maintenance; never an account API."""
        self._enabled()
        _integer(limit, 1, 1000)
        _identifier(after_team_id, optional=True)
        with self.db.connect() as c:
            return [dict(row) for row in c.execute('''SELECT team_id,customer_id,provider_mode,last_sync,last_error
                FROM billing_teams WHERE provider_mode=? AND customer_id IS NOT NULL AND team_id>?
                ORDER BY team_id LIMIT ?''', (self.catalog.provider_mode, after_team_id or '', limit))]

    def _checkout(self, row: sqlite3.Row, claimed: bool) -> CheckoutReservation:
        return CheckoutReservation(**dict(row), claimed=claimed)

    def reserve_checkout(self, team_id: str, *, lease_seconds: int = 60, refresh: bool = False) -> CheckoutReservation:
        _integer(lease_seconds, 1, 3600)
        if type(refresh) is not bool:
            raise ValidationError('Invalid checkout refresh flag')
        with self.db.connect(write=True) as c:
            team = self._ensure_team(c, team_id)
            if not team['customer_id']:
                raise Conflict('Billing customer must be bound first')
            sub = c.execute('SELECT * FROM billing_subscriptions WHERE team_id=?', (team_id,)).fetchone()
            row = c.execute("SELECT * FROM billing_checkouts WHERE team_id=? AND status IN ('pending','open','complete')", (team_id,)).fetchone()
            if sub and sub['status'] not in ('none', 'canceled', 'incomplete_expired') and not (row and refresh):
                raise Conflict('Manage the existing subscription instead')
            now = int(time.time())
            if row:
                if row['lease_until'] > now or (not refresh and row['status'] == 'open' and (row['expires_at'] or 0) > now):
                    return self._checkout(row, False)
                # Retain the attempt/key even after local expiry. The adapter must
                # retrieve/expire the remote session before marking it expired.
                c.execute('UPDATE billing_checkouts SET lease_token=?,lease_until=? WHERE attempt_id=?',
                          (str(uuid4()), now + lease_seconds, row['attempt_id']))
                attempt_id = row['attempt_id']
            else:
                attempt_id = str(uuid4())
                c.execute('''INSERT INTO billing_checkouts(attempt_id,team_id,customer_id,idempotency_key,created_at,status,lease_token,lease_until)
                    VALUES(?,?,?,?,?,'pending',?,?)''', (attempt_id, team_id, team['customer_id'], f'checkout_{uuid4()}', now, str(uuid4()), now + lease_seconds))
            row = c.execute('SELECT * FROM billing_checkouts WHERE attempt_id=?', (attempt_id,)).fetchone()
            self._audit(c, 'reserve_checkout', row['status'], team_id=team_id)
            return self._checkout(row, True)

    def update_checkout(self, reservation: CheckoutReservation, *, status: str, checkout_id: str,
                        checkout_url: str | None = None, expires_at: int | None = None,
                        subscription_id: str | None = None) -> bool:
        self._enabled()
        if not isinstance(reservation, CheckoutReservation) or status not in ('open', 'complete', 'expired'):
            raise ValidationError('Invalid checkout update')
        _identifier(checkout_id)
        _identifier(subscription_id, optional=True)
        if expires_at is not None:
            _integer(expires_at)
        if checkout_url is not None:
            if not isinstance(checkout_url, str) or len(checkout_url) > 4096:
                raise ValidationError('Invalid checkout URL')
            url = urlsplit(checkout_url)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
                raise ValidationError('Invalid checkout URL')
        if status == 'open' and (checkout_url is None or expires_at is None):
            raise ValidationError('Open checkout requires URL and expiry')
        with self.db.connect(write=True) as c:
            row = c.execute('SELECT * FROM billing_checkouts WHERE attempt_id=?', (reservation.attempt_id,)).fetchone()
            now = int(time.time())
            if not row or not reservation.claimed or row['team_id'] != reservation.team_id or not row['lease_token'] or row['lease_token'] != reservation.lease_token or row['lease_until'] <= now:
                return False
            if row['checkout_id'] not in (None, checkout_id) or row['subscription_id'] not in (None, subscription_id):
                raise Conflict('Checkout provider binding cannot change')
            if subscription_id:
                binding = c.execute('SELECT team_id FROM billing_subscription_bindings WHERE provider_mode=? AND subscription_id=?',
                                    (self.catalog.provider_mode, subscription_id)).fetchone()
                if binding and binding['team_id'] != row['team_id']:
                    raise Conflict('Checkout subscription belongs to another team')
            if row['status'] == 'complete' and status != 'complete':
                raise Conflict('Completed checkout cannot return to an earlier state')
            if status == 'complete' and subscription_id:
                current = c.execute('''SELECT 1 FROM billing_subscriptions
                    WHERE team_id=? AND customer_id=? AND provider_mode=? AND subscription_id=?''',
                    (row['team_id'], row['customer_id'], self.catalog.provider_mode, subscription_id)).fetchone()
                if current:
                    status, checkout_url = 'confirmed', None
            try:
                c.execute('''UPDATE billing_checkouts SET status=?,checkout_id=?,checkout_url=?,expires_at=?,
                    subscription_id=?,lease_token=NULL,lease_until=? WHERE attempt_id=?''',
                    (status, checkout_id, checkout_url, expires_at, subscription_id,
                     now + 60 if status == 'complete' else 0, reservation.attempt_id))
            except sqlite3.IntegrityError:
                raise Conflict('Checkout already belongs to another attempt') from None
            self._audit(c, 'update_checkout', status, team_id=row['team_id'])
            return True

    def ingest_event(self, event_id: str, *, event_type: str, object_id: str, provider_mode: str,
                     customer_id: str | None = None, subscription_id: str | None = None) -> bool:
        """Persist only authenticated provider identifiers; True means newly queued."""
        self._provider_mode(provider_mode)
        for value in (event_id, event_type, object_id):
            _identifier(value)
        for value in (customer_id, subscription_id):
            _identifier(value, optional=True)
        values = (event_id, event_type, object_id, provider_mode, customer_id, subscription_id)
        with self.db.connect(write=True) as c:
            existing = c.execute('SELECT event_id,event_type,object_id,provider_mode,customer_id,subscription_id FROM billing_events WHERE event_id=?', (event_id,)).fetchone()
            if existing:
                if tuple(existing) != values:
                    raise Conflict('Event identifier already has different contents')
                return False
            c.execute('''INSERT INTO billing_events(event_id,event_type,object_id,provider_mode,customer_id,subscription_id,state,received_at)
                VALUES(?,?,?,?,?,?,'pending',?)''', (*values, int(time.time())))
            self._audit(c, 'ingest_event', 'pending', event_id=event_id)
            return True

    def claim_job(self, *, lease_seconds: int = 120) -> EventJob | None:
        self._enabled()
        _integer(lease_seconds, 1, 3600)
        with self.db.connect(write=True) as c:
            now = int(time.time())
            row = c.execute('''SELECT * FROM billing_events WHERE provider_mode=? AND
                ((state='pending' AND next_attempt<=?) OR (state='processing' AND lease_until<=?))
                ORDER BY received_at,event_id LIMIT 1''', (self.catalog.provider_mode, now, now)).fetchone()
            if row is None:
                return None
            token = str(uuid4())
            c.execute("UPDATE billing_events SET state='processing',attempts=attempts+1,lease_token=?,lease_until=? WHERE event_id=?",
                      (token, now + lease_seconds, row['event_id']))
            self._audit(c, 'claim_event', 'processing', event_id=row['event_id'])
            return EventJob(row['event_id'], row['event_type'], row['object_id'], row['provider_mode'],
                            row['customer_id'], row['subscription_id'], row['attempts'] + 1, token, now + lease_seconds)

    def _job_current(self, c: sqlite3.Connection, job: EventJob) -> bool:
        if not isinstance(job, EventJob):
            raise ValidationError('Invalid event claim')
        row = c.execute('SELECT * FROM billing_events WHERE event_id=?', (job.event_id,)).fetchone()
        return bool(row and row['state'] == 'processing' and row['lease_token'] == job.lease_token
                    and row['lease_until'] > int(time.time()) and row['attempts'] == job.attempts)

    def retry_job(self, job: EventJob, error_code: str, *, retry_delay: int = 60) -> bool:
        self._enabled()
        _identifier(error_code)
        _integer(retry_delay, 0, 604800)
        with self.db.connect(write=True) as c:
            if not self._job_current(c, job):
                return False
            c.execute("UPDATE billing_events SET state='pending',next_attempt=?,last_error=?,lease_token=NULL,lease_until=0 WHERE event_id=?",
                      (int(time.time()) + retry_delay, error_code, job.event_id))
            self._audit(c, 'retry_event', error_code, event_id=job.event_id)
            return True

    def ignore_job(self, job: EventJob, reason: str) -> bool:
        """For verified unsupported/unbound events; never marks a sync successful."""
        self._enabled()
        _identifier(reason)
        with self.db.connect(write=True) as c:
            if not self._job_current(c, job):
                return False
            c.execute("UPDATE billing_events SET state='ignored',last_error=?,lease_token=NULL,lease_until=0 WHERE event_id=?", (reason, job.event_id))
            self._audit(c, 'ignore_event', reason, event_id=job.event_id)
            return True

    def event_state(self, event_id: str) -> dict | None:
        self._enabled()
        _identifier(event_id)
        with self.db.connect() as c:
            row = c.execute('SELECT event_id,state,attempts,next_attempt,last_error,received_at,processed_at,team_id FROM billing_events WHERE event_id=?', (event_id,)).fetchone()
            return dict(row) if row else None

    def start_sync(self, team_id: str, *, job: EventJob | None = None, lease_seconds: int = 120) -> SyncClaim:
        _integer(lease_seconds, 1, 3600)
        with self.db.connect(write=True) as c:
            row = self._ensure_team(c, team_id)
            if not row['customer_id']:
                raise Conflict('Billing customer must be bound first')
            if job is not None:
                if not self._job_current(c, job):
                    raise Conflict('Event claim expired or superseded')
                if job.provider_mode != row['provider_mode'] or job.customer_id not in (None, row['customer_id']):
                    raise Conflict('Event belongs to a different customer')
                if job.subscription_id:
                    binding = c.execute('SELECT team_id FROM billing_subscription_bindings WHERE provider_mode=? AND subscription_id=?',
                                        (row['provider_mode'], job.subscription_id)).fetchone()
                    if binding and binding['team_id'] != team_id:
                        raise Conflict('Event belongs to a different subscription')
                prior = c.execute('SELECT team_id FROM billing_events WHERE event_id=?', (job.event_id,)).fetchone()
                if prior['team_id'] not in (None, team_id):
                    raise Conflict('Event team binding cannot change')
                c.execute('UPDATE billing_events SET team_id=? WHERE event_id=?', (team_id, job.event_id))
            generation, token, until = row['generation'] + 1, str(uuid4()), int(time.time()) + lease_seconds
            c.execute('UPDATE billing_teams SET generation=?,sync_token=?,sync_until=? WHERE team_id=?', (generation, token, until, team_id))
            self._audit(c, 'start_sync', 'started', team_id=team_id, event_id=job.event_id if job else None, generation=generation)
            return SyncClaim(team_id, row['customer_id'], row['provider_mode'], generation, token, until, job)

    def apply_snapshot(self, claim: SyncClaim, snapshot: SubscriptionSnapshot) -> bool:
        self._enabled()
        if not isinstance(claim, SyncClaim) or not isinstance(snapshot, SubscriptionSnapshot):
            raise ValidationError('Typed sync claim and snapshot required')
        self._provider_mode(snapshot.provider_mode)
        with self.db.connect(write=True) as c:
            row = self._ensure_team(c, claim.team_id)
            now = int(time.time())
            if row['generation'] != claim.generation or row['sync_token'] != claim.lease_token or row['sync_until'] <= now:
                return False
            if claim.job is not None and not self._job_current(c, claim.job):
                return False
            if row['customer_id'] != snapshot.customer_id or claim.customer_id != snapshot.customer_id or claim.provider_mode != snapshot.provider_mode:
                raise Conflict('Snapshot belongs to a different customer')
            old = c.execute('SELECT * FROM billing_subscriptions WHERE team_id=?', (claim.team_id,)).fetchone()
            if old and old['subscription_id'] != snapshot.subscription_id and old['status'] not in ('none', 'canceled', 'incomplete_expired'):
                raise Conflict('Current subscription must be reconciled before replacing it')
            if snapshot.subscription_id:
                binding = c.execute('SELECT team_id FROM billing_subscription_bindings WHERE provider_mode=? AND subscription_id=?',
                                    (snapshot.provider_mode, snapshot.subscription_id)).fetchone()
                if binding and binding['team_id'] != claim.team_id:
                    raise Conflict('Subscription is already bound to another team')
                c.execute('INSERT OR IGNORE INTO billing_subscription_bindings VALUES(?,?,?)',
                          (snapshot.provider_mode, snapshot.subscription_id, claim.team_id))
            c.execute('''INSERT INTO billing_subscriptions(team_id,provider_mode,customer_id,subscription_id,price_id,status,
                current_invoice_id,paid_invoice_id,paid_period_end,cancel_at_period_end,risk_hold,synced_at,generation)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(team_id) DO UPDATE SET
                provider_mode=excluded.provider_mode,customer_id=excluded.customer_id,subscription_id=excluded.subscription_id,
                price_id=excluded.price_id,status=excluded.status,current_invoice_id=excluded.current_invoice_id,
                paid_invoice_id=excluded.paid_invoice_id,paid_period_end=excluded.paid_period_end,
                cancel_at_period_end=excluded.cancel_at_period_end,risk_hold=excluded.risk_hold,synced_at=excluded.synced_at,generation=excluded.generation''',
                (claim.team_id, snapshot.provider_mode, snapshot.customer_id, snapshot.subscription_id, snapshot.price_id,
                 snapshot.status, snapshot.current_invoice_id, snapshot.paid_invoice_id, snapshot.paid_period_end,
                 int(snapshot.cancel_at_period_end), int(snapshot.risk_hold), now, claim.generation))
            c.execute('UPDATE billing_teams SET last_sync=?,last_error=NULL,sync_token=NULL,sync_until=0,catalog_id=? WHERE team_id=?',
                      (now, self.catalog_id, claim.team_id))
            if snapshot.subscription_id:
                c.execute("UPDATE billing_checkouts SET status='confirmed',lease_token=NULL,lease_until=0,checkout_url=NULL WHERE team_id=? AND status='complete' AND subscription_id=?",
                          (claim.team_id, snapshot.subscription_id))
            if claim.job:
                c.execute("UPDATE billing_events SET state='processed',processed_at=?,last_error=NULL,lease_token=NULL,lease_until=0 WHERE event_id=?", (now, claim.job.event_id))
            self._audit(c, 'apply_snapshot', 'risk_hold' if snapshot.risk_hold else snapshot.status,
                        team_id=claim.team_id, event_id=claim.job.event_id if claim.job else None, generation=claim.generation)
            return True

    def fail_sync(self, claim: SyncClaim, error_code: str, *, retry_delay: int = 60) -> bool:
        """Record current sync failure and retry its event without changing entitlement."""
        self._enabled()
        if not isinstance(claim, SyncClaim):
            raise ValidationError('Typed sync claim required')
        _identifier(error_code)
        _integer(retry_delay, 0, 604800)
        with self.db.connect(write=True) as c:
            row = c.execute('SELECT * FROM billing_teams WHERE team_id=?', (claim.team_id,)).fetchone()
            now = int(time.time())
            if not row or row['generation'] != claim.generation or row['sync_token'] != claim.lease_token or row['sync_until'] <= now:
                return False
            if claim.job is not None and not self._job_current(c, claim.job):
                return False
            c.execute('UPDATE billing_teams SET last_error=?,sync_token=NULL,sync_until=0 WHERE team_id=?',
                      (error_code, claim.team_id))
            if claim.job is not None:
                c.execute("UPDATE billing_events SET state='pending',next_attempt=?,last_error=?,lease_token=NULL,lease_until=0 WHERE event_id=?",
                          (now + retry_delay, error_code, claim.job.event_id))
            self._audit(c, 'fail_sync', error_code, team_id=claim.team_id,
                        event_id=claim.job.event_id if claim.job else None, generation=claim.generation)
            return True
