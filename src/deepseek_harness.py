"""DeepSeek Harness (`dsh`) integration: MCP-client patch rows and config checks.

DeepSeek Harness is DeepSeek's first-party agent runtime (developer preview,
breaking changes expected; https://github.com/deepseek-ai/deepseek-harness).
It is not a JSON-config harness: MCP servers are Cordis plugin rows in a
YAML patch layer (``$DSH_HOME/profiles/<profile>/cordis.patch.yml`` or
``$DSH_HOME/cordis.patch.yml``, default home ``~/.dsh``), one
``@deepseek-ai/dsh-mcp-client`` entry per server, documented at
https://deepseek-harness.github.io/deepseek-harness/en/guide/mcp-memory
(checked 2026-11-12). There is no project-level MCP config file, no
shell-hook config (hooks are in-process Cordis plugins or experimental
bridges), no external wake API, and no checkpoint-hook vocabulary —
"checkpoint" in DSH docs means session-log durability.

This module generates the MCP-client patch row for the Coopagents server
(Streamable HTTP only; no local stdio runner is bundled) and inspects patch
layers for its presence. It never writes a patch file — YAML merging without
a parser would risk corrupting user config — and it never emits, reads, or
reports a credential value: no documented env expansion exists for MCP
client headers, so the row carries no Authorization header and the user
adds auth per their DSH setup.

Live acceptance against a real `dsh` process is unverified: no `dsh`
binary runs on this VM, and driving a session needs a DeepSeek API key.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

MCP_CLIENT_PLUGIN = '@deepseek-ai/dsh-mcp-client'
SERVER_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_ROW_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


def _service_url(url):
    if not isinstance(url, str) or not url.strip() or len(url) > 2048 or any(char.isspace() for char in url):
        raise ValueError('MCP URL must be HTTPS or loopback HTTP')
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or '').lower()
    loopback = host in ('127.0.0.1', 'localhost', '::1')
    if not host or not (parsed.scheme == 'https' or (parsed.scheme == 'http' and loopback)):
        raise ValueError('MCP URL must be HTTPS or loopback HTTP')
    if parsed.username or parsed.password or parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('MCP URL is invalid')
    return url.strip()


def _server_name(value):
    if not isinstance(value, str) or not SERVER_NAME.match(value):
        raise ValueError('Server name must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
    return value


def _yaml_string(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t') + '"'


def mcp_client_row(service_url, server_name='coopagents'):
    """The Cordis patch row that connects one MCP server, as YAML text.

    Fixed template with escaped values; merge it into a patch layer by hand
    (see patch_layers). No header is emitted: no documented env expansion
    exists for MCP client headers, and a literal placeholder would reach
    the server as the token.
    """
    url = _service_url(service_url)
    name = _server_name(server_name)
    row_id = '%s-mcp-client' % name
    return '\n'.join((
        '# Coopagents MCP server (managed; merge into a cordis.patch.yml layer, do not edit the row).',
        '# Auth: add an Authorization header here by hand if your DSH setup needs one;',
        '# no documented env expansion exists for these headers, so no placeholder is emitted.',
        '- insert:',
        '  - id: %s' % _yaml_string(row_id),
        "    name: '%s'" % MCP_CLIENT_PLUGIN,
        '    config:',
        '      serverName: %s' % _yaml_string(name),
        '      transport: "streamable-http"',
        '      url: %s' % _yaml_string(url),
    )) + '\n'


def dsh_home():
    """The Harness home: $DSH_HOME, or ~/.dsh when unset."""
    override = os.environ.get('DSH_HOME')
    if override:
        return Path(override)
    return Path.home() / '.dsh'


def patch_layers(profile=None, home=None):
    """Candidate patch-layer files, most specific first.

    Profile layers precede the home layer, matching the documented layer
    order (profile bundles, profile patch, home patch, --patch overlays;
    --patch overlays cannot be discovered from the filesystem).
    """
    root = Path(home) if home is not None else dsh_home()
    layers = []
    if profile:
        layers.append(root / 'profiles' / profile / 'cordis.patch.yml')
    layers.append(root / 'cordis.patch.yml')
    return layers


def row_present(patch_text, server_name='coopagents'):
    """Whether patch text contains a dsh-mcp-client row for this server.

    Presence only: the row id/name pair must both appear. The text is never
    returned or logged; callers report booleans, never file contents.
    """
    name = _server_name(server_name)
    if MCP_CLIENT_PLUGIN not in patch_text:
        return False
    pattern = re.compile(r'^\s*serverName:\s*["\']?%s["\']?\s*(#.*)?$' % re.escape(name), re.M)
    return pattern.search(patch_text) is not None


def plan(service_url, server_name='coopagents', profile=None, home=None):
    """A merge plan: the row text plus where it goes. Nothing is written."""
    return {
        'harness': 'deepseek',
        'profile': profile or 'web',
        'home': str(Path(home) if home is not None else dsh_home()),
        'patch_layers': [str(path) for path in patch_layers(profile, home)],
        'row': mcp_client_row(service_url, server_name),
        'server_name': _server_name(server_name),
        'transport': 'streamable-http',
        'notes': ('DeepSeek Harness is in developer preview and iterates with breaking changes. '
                  'Merge the row into one patch layer and restart dsh. No project-level MCP config '
                  'exists; hooks are Cordis plugins, and there is no external wake API. '
                  'Live dsh acceptance is unverified.'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Plan a Coopagents MCP row for DeepSeek Harness patch layers')
    parser.add_argument('--service-url', required=True, help='HTTPS or loopback HTTP MCP endpoint')
    parser.add_argument('--name', default='coopagents', help='MCP server name (default coopagents)')
    parser.add_argument('--profile', help='DSH profile whose patch layer receives the row (default: home layer)')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(plan(args.service_url, args.name, args.profile), indent=2))
        return 0
    except ValueError as error:
        print('Coopagents DeepSeek Harness plan failed: %s' % error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
