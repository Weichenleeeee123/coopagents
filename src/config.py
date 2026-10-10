"""Fail-closed public origin, bootstrap credential and proxy configuration."""
import ipaddress
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def public_origin(value):
    """Return a canonical HTTPS origin without accepting URL lookalikes."""
    if not isinstance(value, str) or any(c.isspace() for c in value) or any(c in value for c in '\\?#'):
        raise ValueError('Public URL must be an HTTPS origin without credentials, path, query or fragment')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
                or parsed.netloc.endswith(':') or port is not None and not 1 <= port <= 65535):
            raise ValueError()
        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address(host)
            host = '[' + host + ']' if address.version == 6 else host
        except ValueError:
            if len(host) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
                raise ValueError()
        return 'https://' + host + (':' + str(port) if port is not None and port != 443 else '')
    except ValueError:
        raise ValueError('Public URL must be an HTTPS origin without credentials, path, query or fragment') from None


def validate_bootstrap_secret(value):
    # Operators must generate this using secrets.token_urlsafe(32) or stronger.
    # Minimum length/character checks reject common mistakes; randomness cannot
    # be proven by inspecting an operator-provided value.
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', value) or len(set(value)) < 16:
        raise ValueError('Public mode requires a random bootstrap secret generated with secrets.token_urlsafe(32)')
    return value


def bootstrap_from_env(environ=None):
    environ = os.environ if environ is None else environ
    secret = environ.get('CREWMESH_BOOTSTRAP_SECRET')
    filename = environ.get('CREWMESH_BOOTSTRAP_SECRET_FILE')
    if secret and filename:
        raise ValueError('Set only one bootstrap secret source')
    if filename:
        try:
            with Path(filename).open('r', encoding='ascii') as source:
                secret = source.read(130).rstrip('\r\n')
        except (OSError, UnicodeError):
            raise ValueError('Bootstrap secret file could not be read') from None
    return secret


def trusted_proxies(value):
    if not value:
        return []
    result = []
    try:
        for item in value.split(','):
            item = item.strip()
            network = ipaddress.ip_network(item, strict=True)
            if network.prefixlen == 0:
                raise ValueError()
            result.append(item)
    except ValueError:
        raise ValueError('Trusted proxies must be explicit IP addresses or CIDRs; wildcard trust is forbidden') from None
    return result
