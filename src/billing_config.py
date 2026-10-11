"""Explicit cloud billing configuration. No provider I/O at startup."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re

from .billing import BillingCatalog


@dataclass(frozen=True)
class BillingConfig:
    enabled: bool = False
    catalog: BillingCatalog | None = None
    secret_key: str | None = field(default=None, repr=False)
    webhook_secret: str | None = field(default=None, repr=False)


def _secret(env, name, prefix):
    direct, path = env.get(name), env.get(name + '_FILE')
    if (direct is not None) == (path is not None):
        raise ValueError('Billing secret requires exactly one source')
    try:
        if path is not None:
            with Path(path).open('rb') as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError('Billing secret file is too large')
            direct = raw.decode('ascii').rstrip('\r\n')
        if not isinstance(direct, str) or not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9_]{1,250}', direct):
            raise ValueError('Invalid billing secret')
    except (OSError, UnicodeError):
        raise ValueError('Billing secret file unavailable') from None
    return direct


def load_billing_config(deployment_mode: str, env=None) -> BillingConfig:
    if deployment_mode not in ('cloud', 'self-hosted'):
        raise ValueError('Invalid deployment mode')
    if deployment_mode == 'self-hosted':
        return BillingConfig()
    env = os.environ if env is None else env
    names = ('CREWMESH_BILLING_MODE', 'CREWMESH_STRIPE_SECRET_KEY', 'CREWMESH_STRIPE_SECRET_KEY_FILE',
             'CREWMESH_STRIPE_WEBHOOK_SECRET', 'CREWMESH_STRIPE_WEBHOOK_SECRET_FILE',
             'CREWMESH_TEAM_MONTHLY_PRICE_ID', 'CREWMESH_FREE_MEMBERS', 'CREWMESH_FREE_PROJECTS',
             'CREWMESH_TEAM_MEMBERS', 'CREWMESH_TEAM_PROJECTS')
    if not any(name in env for name in names):
        return BillingConfig()
    mode = env.get('CREWMESH_BILLING_MODE')
    if mode not in ('test', 'live'):
        raise ValueError('Explicit billing mode required')
    caps = []
    for name in names[6:]:
        raw = env.get(name)
        if not isinstance(raw, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', raw):
            raise ValueError('Explicit positive billing limits required')
        caps.append(int(raw))
    price = env.get('CREWMESH_TEAM_MONTHLY_PRICE_ID')
    if not isinstance(price, str) or not re.fullmatch(r'price_[A-Za-z0-9]{1,200}', price):
        # Fixture IDs and real IDs share Stripe's prefix; underscore suffixes are allowed below.
        if not isinstance(price, str) or not re.fullmatch(r'price_[A-Za-z0-9_]{1,200}', price):
            raise ValueError('Explicit monthly price required')
    return BillingConfig(True, BillingCatalog(*caps, price, mode),
                         _secret(env, 'CREWMESH_STRIPE_SECRET_KEY', 'sk_' + mode + '_'),
                         _secret(env, 'CREWMESH_STRIPE_WEBHOOK_SECRET', 'whsec_'))
