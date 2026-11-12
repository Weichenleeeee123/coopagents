"""Distributable ZCode plugin bundle for Coopagents.

ZCode plugins are declarative bundles, not in-process code: a folder with a
``.zcode-plugin/plugin.json`` manifest plus component files, documented at
https://zcode.z.ai/en/docs/plugin (checked 2026-11-12). Hooks in a plugin
are subprocess hooks — ZCode writes one JSON line to stdin and reads the
reply from the exit code and stdout JSON; hooks never receive internal
objects. There is no documented in-process extension API, so this generator
ships no code that runs inside the ZCode process.

The bundle carries the checkpoint hooks (which read the trusted connection
from the process environment) and an MCP server declaration. It does not
carry wake hooks: those embed a profile path, which is user-specific, so
wake-up stays a user-config install via ``coopagents.space_wake``. The MCP
entry carries no Authorization header — ZCode config files do not expand
templates, so the bearer token belongs in user-scope config, as the
bundled README explains.

Live plugin loading is unverified: no ZCode binary runs on this VM, and
the desktop docs and the CLI repo guide disagree about project-level hooks
(desktop: ignored; CLI guide: trust-gated). The plugin route is the one
both sources agree on; runtime verification on a real ZCode build still
needs a user machine.
"""
import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import sys

from .checkpoint_hook import hook_argv
from .harness_adapters import adapter_for

MANIFEST_NAME = re.compile(r'^[a-z0-9][a-z0-9._-]{0,127}$')
DOCUMENTED_EVENTS = frozenset(('SessionStart', 'UserPromptSubmit', 'PreToolUse',
                               'PermissionRequest', 'PostToolUse', 'PostToolUseFailure', 'Stop'))
CHECKPOINT_EVENTS = ('SessionStart', 'PostToolUse', 'UserPromptSubmit')
MCP_ENTRY_KEYS = frozenset(('type', 'url', 'headers', 'enabled', 'timeoutMs'))
PLUGIN_NAME = 'coopagents'


def _string(value, name, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('%s must be a nonempty string of at most %d characters' % (name, limit))
    return value.strip()


def _package_version():
    try:
        return metadata.version('coopagents')
    except metadata.PackageNotFoundError:
        return '0.0.0'


def _mcp_entry(service_url, server_name):
    # Reuse the canonical ZCode remote entry: validated URL, no header.
    document = adapter_for('zcode').merge_remote({}, server_name, service_url)
    return document['mcp']['servers'][server_name]


def _checkpoint_hooks():
    argv = hook_argv('zcode')
    process = {'type': 'process', 'command': argv[0], 'args': argv[1:]}
    events = {}
    for event in CHECKPOINT_EVENTS:
        group = {'hooks': [dict(process)]}
        if event == 'SessionStart':
            # Match only startup, so a compact never records a duplicate baseline.
            group['matcher'] = 'startup'
        events[event] = [group]
    return {'hooks': events}


def _manifest():
    return {
        'name': PLUGIN_NAME,
        'version': _package_version(),
        'description': 'Coopagents team collaboration: MCP tools plus checkpoint hooks.',
        'license': 'MIT',
    }


def _readme(service_url, server_name):
    return (
        '# Coopagents plugin for ZCode\n'
        '\n'
        'Install with the ZCode CLI (`zcode plugins install`, or point the\n'
        '`plugins.dirs` setting at this folder), then restart ZCode. The\n'
        'plugin contributes checkpoint hooks and an MCP server entry named\n'
        '`%s` pointing at `%s`.\n'
        '\n'
        '## Authentication\n'
        '\n'
        'ZCode config files do not expand templates, so this bundle carries\n'
        'no credential. Add the bearer token in user-scope\n'
        '`~/.zcode/cli/config.json` under `mcp.servers` with the same server\n'
        'name, carrying your token in the `Authorization` header; the user\n'
        'entry overrides this plugin entry. Never commit that file.\n'
        '\n'
        '## Wake-up\n'
        '\n'
        'Wake hooks are not part of this bundle: they embed a profile path.\n'
        'Install them separately with `coopagents.space_wake install\n'
        '--tool zcode --scope user --profile <path>`.\n'
        '\n'
        'This bundle is generated; do not edit it by hand. Regenerate with:\n'
        '  python -m coopagents.zcode_plugin --service-url <url> --export <dir>\n'
        % (server_name, service_url)
    )


def plugin_files(service_url, server_name='coopagents'):
    """{relative path: file text} for the whole bundle. Nothing is written."""
    server_name = _string(server_name, 'MCP server name')
    files = {
        '.zcode-plugin/plugin.json': json.dumps(_manifest(), indent=2) + '\n',
        'hooks/hooks.json': json.dumps(_checkpoint_hooks(), indent=2) + '\n',
        '.mcp.json': json.dumps({'mcpServers': {server_name: _mcp_entry(service_url, server_name)}},
                                indent=2) + '\n',
        'README.md': _readme(service_url, server_name),
    }
    return files


def validate_plugin(directory):
    """Structural problems in a plugin directory, [] when it looks valid.

    Checks only documented constraints: manifest presence/shape, hook
    events within the documented seven, process-hook argv shape, and MCP
    entry keys within the strict ZCode entry schema. It cannot prove ZCode
    loads the bundle; that needs a real ZCode build.
    """
    root = Path(directory)
    problems = []
    manifest_path = root / '.zcode-plugin' / 'plugin.json'
    if not manifest_path.is_file():
        problems.append('missing .zcode-plugin/plugin.json')
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            problems.append('.zcode-plugin/plugin.json is not valid JSON: %s' % error)
            manifest = None
        if isinstance(manifest, dict):
            name = manifest.get('name')
            if not isinstance(name, str) or not MANIFEST_NAME.match(name):
                problems.append('manifest name must match ^[a-z0-9][a-z0-9._-]{0,127}$')
        elif manifest is not None:
            problems.append('manifest must be a JSON object')
    hooks_path = root / 'hooks' / 'hooks.json'
    if hooks_path.exists():
        try:
            hooks_document = json.loads(hooks_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            problems.append('hooks/hooks.json is not valid JSON: %s' % error)
            hooks_document = None
        if isinstance(hooks_document, dict):
            events = hooks_document.get('hooks')
            if not isinstance(events, dict):
                problems.append('hooks/hooks.json must carry a hooks object')
            else:
                for event, groups in events.items():
                    if event not in DOCUMENTED_EVENTS:
                        problems.append('undocumented hook event: %s' % event)
                    if not isinstance(groups, list):
                        problems.append('hook event %s must be a list' % event)
                        continue
                    for group in groups:
                        if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                            problems.append('hook event %s has a malformed group' % event)
                            continue
                        for hook in group['hooks']:
                            if not isinstance(hook, dict) or not hook.get('command'):
                                problems.append('hook event %s has a hook without a command' % event)
        elif hooks_document is not None:
            problems.append('hooks/hooks.json must be a JSON object')
    mcp_path = root / '.mcp.json'
    if mcp_path.exists():
        try:
            mcp_document = json.loads(mcp_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            problems.append('.mcp.json is not valid JSON: %s' % error)
            mcp_document = None
        if isinstance(mcp_document, dict):
            servers = mcp_document.get('mcpServers')
            if not isinstance(servers, dict):
                problems.append('.mcp.json must carry an mcpServers object')
            else:
                for name, entry in servers.items():
                    if not isinstance(entry, dict):
                        problems.append('MCP server %s must be an object' % name)
                    elif not entry.get('type') or not entry.get('url'):
                        problems.append('MCP server %s needs type and url' % name)
                    elif set(entry) - MCP_ENTRY_KEYS:
                        problems.append('MCP server %s carries keys outside the ZCode entry schema' % name)
        elif mcp_document is not None:
            problems.append('.mcp.json must be a JSON object')
    return problems


def write_plugin(directory, service_url, server_name='coopagents'):
    """Write a fresh bundle directory. Refuses non-empty directories and symlinks."""
    root = Path(directory)
    if root.is_symlink():
        raise ValueError('Plugin path must not be a symlink: %s' % root)
    if root.exists() and any(root.iterdir()):
        raise ValueError('Refusing to write into non-empty directory %s; use a fresh directory' % root)
    files = plugin_files(service_url, server_name)
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    problems = validate_plugin(root)
    if problems:
        raise ValueError('Generated plugin failed validation: %s' % '; '.join(problems))
    return {'status': 'exported', 'path': str(root), 'files': sorted(files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate or validate a Coopagents plugin bundle for ZCode')
    parser.add_argument('--service-url', help='HTTPS or loopback HTTP MCP endpoint (required for --export)')
    parser.add_argument('--name', default='coopagents', help='MCP server name (default coopagents)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--export', metavar='DIR', help='Write the bundle to a fresh directory')
    mode.add_argument('--validate', metavar='DIR', help='Validate an existing plugin directory')
    args = parser.parse_args(argv)
    try:
        if args.export:
            if not args.service_url:
                parser.error('--service-url is required for --export')
            result = write_plugin(args.export, args.service_url, args.name)
        else:
            problems = validate_plugin(args.validate)
            result = {'status': 'valid' if not problems else 'invalid', 'path': str(args.validate),
                      'problems': problems}
            print(json.dumps(result, indent=2))
            return 0 if not problems else 1
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print('Coopagents ZCode plugin generation failed: %s' % error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
