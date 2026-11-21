"""HTTP application factory for the collaboration service and optional workbench."""
from urllib.parse import urlsplit

from .config import public_origin, validate_bootstrap_secret
from .http_boundary import LocalBoundary, bearer, error_payload
from .protocol import fields, validate


def create_app(database_path='.local/coopagents.sqlite3', *, base_url=None, public_url=None,
               bootstrap_secret=None, mode='self-hosted', **settings):
    if mode in ('workflow', 'cloud'):
        from .workflow_api import create_app as workflow_app
        return workflow_app(database_path, base_url=base_url, public_url=public_url,
                            bootstrap_secret=bootstrap_secret, mode='cloud' if mode == 'cloud' else 'self-hosted',
                            **settings)
    if mode != 'self-hosted' or settings:
        raise ValueError('Account and Git settings require workflow or cloud mode')
    if base_url and public_url:
        raise ValueError('Set only one service origin')
    if base_url and urlsplit(base_url).hostname not in ('127.0.0.1', 'localhost'):
        raise ValueError('Base URL must be a local HTTP origin')
    origin = public_origin(public_url) if public_url is not None else None
    if origin or bootstrap_secret is not None:
        validate_bootstrap_secret(bootstrap_secret)
    from .collaboration_core import CollaborationService
    from .space_server import create_space_app
    return create_space_app(CollaborationService(database_path), room_id=None,
                            origin=origin or base_url, bootstrap_secret=bootstrap_secret)


def __getattr__(name):
    if name == 'Service':
        from .workflow_api import Service
        return Service
    raise AttributeError(name)
