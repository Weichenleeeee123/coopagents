"""Start the local coordination service."""
import argparse


def main():
    parser = argparse.ArgumentParser(description='Local Crewmesh HTTP and MCP service')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--database', default='.local/crewmesh.sqlite3')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    import uvicorn
    from .api import create_app
    uvicorn.run(create_app(args.database), host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
