"""Existing-database-only bounded billing maintenance. No schema initialization."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
import sqlite3
import sys
import time
from .account_recovery import ExistingDatabase
from .billing import BillingStore
from .billing_api import billing_catalog
from .billing_config import load_billing_config
from .billing_checkout import CheckoutResolver
from .billing_operations import BillingOperations
from .billing_service import BillingService
from .config import public_origin
from .errors import Conflict
from .stripe_billing import StripeClient, StripeError
from .stripe_snapshot import SnapshotVerifier

# These columns are the C2 ledger contract, not a schema migration recipe.
SCHEMA = {
    'teams': 'id name',
    'billing_catalogs': 'id configuration created_at',
    'billing_teams': 'team_id provider_mode customer_id customer_key created_at generation sync_token sync_until last_sync last_error catalog_id',
    'billing_subscription_bindings': 'provider_mode subscription_id team_id',
    'billing_subscriptions': 'team_id provider_mode customer_id subscription_id price_id status current_invoice_id paid_invoice_id paid_period_end cancel_at_period_end risk_hold synced_at generation',
    'billing_checkouts': 'attempt_id team_id customer_id idempotency_key created_at status lease_token lease_until checkout_id checkout_url expires_at subscription_id',
    'billing_events': 'event_id event_type object_id provider_mode customer_id subscription_id state received_at attempts next_attempt lease_token lease_until last_error processed_at team_id',
    'billing_audit': 'id team_id event_id action result generation created_at',
    'billing_outbound_operations': 'operation_id team_id purpose idempotency_key created_at state provider_id',
}


def open_billing(database, config, origin):
    """Validate known schema/catalog with read-only SQL, then wire existing stores."""
    canonical = public_origin(origin)
    catalog = billing_catalog('cloud', config, canonical)
    if catalog is None:
        raise ValueError('Enabled cloud billing configuration required')
    db = ExistingDatabase(database)
    configuration = json.dumps(asdict(catalog), sort_keys=True, separators=(',', ':'))
    catalog_id = hashlib.sha256(configuration.encode()).hexdigest()
    try:
        with db.connect() as connection:
            for table, names in SCHEMA.items():
                record = connection.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
                actual = {row['name'] for row in connection.execute('PRAGMA table_info(' + table + ')')}
                if record is None or record['type'] != 'table' or not set(names.split()) <= actual:
                    raise ValueError('Existing C2 billing database schema required')
            row = connection.execute('SELECT configuration FROM billing_catalogs WHERE id=?', (catalog_id,)).fetchone()
            if row is None or row['configuration'] != configuration:
                raise ValueError('Configured billing catalog must already exist in the database')
            for table in ('billing_teams', 'billing_events', 'billing_subscriptions', 'billing_subscription_bindings'):
                if connection.execute('SELECT 1 FROM ' + table + ' WHERE provider_mode<>? LIMIT 1', (catalog.provider_mode,)).fetchone():
                    raise ValueError('Existing ledger provider mode does not match configuration')
    except sqlite3.Error:
        raise ValueError('Existing C2 billing database unavailable') from None
    # The maintenance paths need ledger operations, not account authorization.
    # Bypass constructors deliberately: none of their CREATE/migrate SQL runs.
    store = BillingStore.__new__(BillingStore)
    store.db, store.mode, store.catalog = db, 'cloud', catalog
    store.enabled, store.catalog_id = True, catalog_id
    service = BillingService.__new__(BillingService)
    service.store, service.origin = store, canonical
    service.client = StripeClient(config.secret_key, catalog.provider_mode)
    service.webhook_secret = config.webhook_secret
    service.operations = BillingOperations.__new__(BillingOperations)
    service.operations.store = store
    service.verifier = SnapshotVerifier(service.client, catalog)
    service.checkouts = CheckoutResolver(store, service.client, service.verifier, canonical)
    return service


def _bound(value):
    if type(value) is not int or not 1 <= value <= 1000:
        raise ValueError('Maintenance bound must be between 1 and 1000')


def retry(billing, *, max_jobs=25):
    """Attempt at most max_jobs due jobs, without spinning on future retries."""
    _bound(max_jobs)
    result = {'attempted': 0, 'succeeded': 0, 'failed': 0}
    for _ in range(max_jobs):
        # False can mean no due job or a failed attempt. Inventory due work
        # before the service claims it, without exposing provider IDs.
        now = int(time.time())
        with billing.store.db.connect() as connection:
            due = connection.execute('''SELECT event_id FROM billing_events WHERE provider_mode=? AND
                ((state='pending' AND next_attempt<=?) OR (state='processing' AND lease_until<=?))
                ORDER BY received_at,event_id LIMIT 1''',
                (billing.store.catalog.provider_mode, now, now)).fetchone()
        if due is None:
            break
        # The provider/service owns leases and backoff; another worker may win
        # between this inventory read and its atomic claim.
        worked = billing.process_next()
        result['attempted'] += 1
        result['succeeded' if worked else 'failed'] += 1
        if not worked:
            # Backoff schedules this job for later; leave subsequent jobs for a
            # later bounded run when provider service is unavailable.
            break
    return result


def reconcile(billing, *, max_teams=100):
    """Only existing bindings; canonical reads and saved competing-checkout expiry."""
    _bound(max_teams)
    result = {'attempted': 0, 'succeeded': 0, 'failed': 0}
    after = None
    while result['attempted'] < max_teams:
        teams = billing.store.list_bound_teams(limit=min(100, max_teams - result['attempted']), after_team_id=after)
        if not teams:
            break
        for team in teams:
            after = team['team_id']
            result['attempted'] += 1
            try:
                billing.reconcile_team(after)
                result['succeeded'] += 1
            except (StripeError, Conflict):
                result['failed'] += 1
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Existing C2 Crewmesh SQLite database')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('retry').add_argument('--max-jobs', type=int, default=25)
    commands.add_parser('reconcile').add_argument('--max-teams', type=int, default=100)
    args = parser.parse_args(argv)
    try:
        bound = args.max_jobs if args.command == 'retry' else args.max_teams
        _bound(bound)
        config = load_billing_config('cloud')
        billing = open_billing(args.database, config, os.environ.get('CREWMESH_PUBLIC_URL'))
        result = retry(billing, max_jobs=bound) if args.command == 'retry' else reconcile(billing, max_teams=bound)
    except (ValueError, sqlite3.Error, OSError, Conflict):
        print('Billing maintenance unavailable; check existing database and protected configuration', file=sys.stderr)
        return 2
    except Exception:
        print('Billing maintenance failed; durable leases retained for recovery', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
