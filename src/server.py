"""Start the local coordination service."""
import argparse
import os
import ipaddress


def main():
    parser = argparse.ArgumentParser(description='Crewmesh HTTP and MCP service')
    parser.add_argument('--host', default=os.environ.get('CREWMESH_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=os.environ.get('CREWMESH_PORT', '8787'))
    parser.add_argument('--database', default=os.environ.get('CREWMESH_DATABASE', '.local/crewmesh.sqlite3'))
    parser.add_argument('--public-url', default=os.environ.get('CREWMESH_PUBLIC_URL'))
    parser.add_argument('--mode', choices=('self-hosted', 'cloud'), default=os.environ.get('CREWMESH_MODE', 'self-hosted'))
    parser.add_argument('--trusted-proxies', default=os.environ.get('CREWMESH_TRUSTED_PROXIES', ''))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    import uvicorn
    from .api import create_app
    from .billing_config import load_billing_config
    from .config import bootstrap_from_env, trusted_proxies, github_oauth_from_env
    from .github_app import GitHubApp
    from .errors import ValidationError
    try:
        try:
            local_bind = ipaddress.ip_address(args.host).is_loopback
        except ValueError:
            local_bind = args.host.lower() == 'localhost'
        if not local_bind and not args.public_url:
            raise ValueError('Non-loopback binding requires an explicit HTTPS public URL and bootstrap secret')
        proxies = trusted_proxies(args.trusted_proxies)
        account_config = github_oauth_from_env()
        billing_config = load_billing_config(args.mode)
        if billing_config.enabled:
            account_config['billing_config'] = billing_config
        if args.mode != 'self-hosted':
            account_config['mode'] = args.mode
        app = create_app(args.database, public_url=args.public_url, bootstrap_secret=bootstrap_from_env(),
                         github_app=GitHubApp.from_env(args.public_url), **account_config)
    except (ValueError, ValidationError) as error:
        parser.error(str(error))
    uvicorn.run(app, host=args.host, port=args.port, access_log=False,
                proxy_headers=bool(proxies), forwarded_allow_ips=proxies,
                ws_max_size=4096, ws_max_queue=4, ws_ping_interval=15, ws_ping_timeout=15)


if __name__ == '__main__':
    main()
