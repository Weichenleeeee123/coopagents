"""Stand-in for `claude` / `codex` mcp subcommands, mirroring their real output formats."""
import json
import os
import sys
from pathlib import Path

tool, state = os.environ['FAKE_TOOL'], Path(os.environ['FAKE_MCP_STATE'])
servers = json.loads(state.read_text()) if state.exists() else {}
args = sys.argv[1:]
if args == ['--version']:
    print('Codex CLI 2.0.0')
    sys.exit(0)
if os.environ.get('FAKE_BROKEN') or args[:1] == ['--broken']:
    print('Error: failed to load configuration', file=sys.stderr)
    sys.exit(1)
if args[:2] == ['mcp', 'get']:
    name = args[2]
    if name not in servers:
        if tool == 'codex':
            print("Error: No MCP server named '%s' found." % name, file=sys.stderr)
        else:
            print('No MCP server named "%s". Configured servers: other' % name)
        sys.exit(1)
    entry = servers[name]
    if tool == 'codex':
        print(json.dumps({'name': name, 'enabled': not bool(os.environ.get('FAKE_DISABLED')),
                          'transport': {'type': 'stdio', 'command': entry[0], 'args': entry[1:], 'env': {}}}, indent=2))
    else:
        print('%s:\n  Scope: User config (available in all your projects)\n  Status: x Failed to connect\n'
              '  Type: stdio\n  Command: %s\n  Args: %s\n  Environment:\n' % (name, entry[0], ' '.join(entry[1:])))
    sys.exit(0)
if args[:2] == ['mcp', 'add']:
    split = args.index('--')
    if tool == 'claude':
        assert args[2:6] == ['--transport', 'stdio', '--scope', 'user'], args
    if os.environ.get('FAKE_IGNORE_ADD'):
        sys.exit(0)
    servers[args[split - 1]] = args[split + 1:]
    state.write_text(json.dumps(servers))
    if tool == 'codex':
        import tomllib
        root = Path(os.environ['CODEX_HOME']).resolve()
        assert root.is_relative_to(Path(__file__).resolve().parents[1] / '.local'), 'Use an isolated native home'
        root.mkdir(parents=True, exist_ok=True)
        config = root / 'config.toml'
        document = tomllib.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
        entries = document.get('mcp_servers', {})
        entries[args[split - 1]] = {'command': args[split + 1], 'args': args[split + 2:]}
        config.write_text(''.join('[mcp_servers.' + name + ']\n' + ''.join(
            key + ' = ' + json.dumps(value) + '\n' for key, value in entry.items())
            for name, entry in entries.items()), encoding='utf-8')
    sys.exit(0)
sys.exit(2)
