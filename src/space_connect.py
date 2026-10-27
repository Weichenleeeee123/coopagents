"""Deterministic native connection: register the stdio bridge with Claude Code or Codex, install the skill, verify."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .spaces import checked_path, read_profile

TOOLS = ('claude', 'codex')
NAME_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
SKILL_NAME = 'coopagents-space'


class ConnectError(RuntimeError):
    """A fixed, secret-free explanation that the CLI may show to the user."""


def _bridge_entry(name, command, args):
    """A registered Coopagents bridge: <python> -m coopagents.space_bridge --profile <path>."""
    args = [str(a) for a in (args or [])]
    if args[:2] != ['-m', 'coopagents.space_bridge'] or '--profile' not in args:
        return None
    index = args.index('--profile')
    if index + 1 >= len(args):
        return None
    return {'server': name, 'python': str(command), 'profile': args[index + 1]}


def registered_spaces(tool, project_dir=None):
    """Read the native configuration (read-only, no processes) for registered Coopagents bridges."""
    entries = []
    if tool == 'codex':
        import tomllib
        path = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'
        if path.is_file():
            servers = tomllib.loads(path.read_text(encoding='utf-8')).get('mcp_servers') or {}
            for name, server in servers.items():
                if isinstance(server, dict):
                    entries.append(_bridge_entry(name, server.get('command'), server.get('args')))
    else:
        home = os.environ.get('CLAUDE_CONFIG_DIR')
        path = Path(home) / '.claude.json' if home else Path.home() / '.claude.json'
        if path.is_file():
            document = json.loads(path.read_text(encoding='utf-8') or '{}')
            groups = [document.get('mcpServers') or {}]
            projects = document.get('projects') or {}
            if project_dir is not None:
                wanted = os.path.normcase(os.path.abspath(project_dir)).replace(os.sep, '/')
                for key, value in projects.items():
                    if os.path.normcase(os.path.abspath(key)).replace(os.sep, '/') == wanted and isinstance(value, dict):
                        groups.append(value.get('mcpServers') or {})
            for servers in groups:
                for name, server in servers.items():
                    if isinstance(server, dict):
                        entries.append(_bridge_entry(name, server.get('command'), server.get('args')))
    unique = {}
    for entry in entries:
        if entry is not None:
            unique.setdefault(entry['profile'], entry)
    return list(unique.values())


def server_name(profile):
    return 'coopagents_' + profile['room_id'].replace('-', '')[:8]


def bridge_command(profile_path):
    return [sys.executable, '-m', 'coopagents.space_bridge', '--profile', str(profile_path)]


def _running_paths(name):
    """Executables of running processes (Windows): an agent runs inside its own tool, so that copy works."""
    if os.name != 'nt':
        return []
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-Command',
                                 'Get-Process -Name %s -ErrorAction SilentlyContinue | '
                                 'Select-Object -ExpandProperty Path' % name],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return list(dict.fromkeys(line.strip() for line in result.stdout.splitlines() if line.strip()))


def cli_candidates(tool, cli=None):
    """Explicit path only, or else every likely location in order; the first that works is used."""
    if cli:
        return [list(cli) if isinstance(cli, (list, tuple)) else [str(cli)]]
    home, appdata = Path.home(), Path(os.environ.get('APPDATA') or Path.home())
    if tool == 'claude':
        paths = [os.environ.get('COOPAGENTS_CLAUDE_CLI'), os.environ.get('CLAUDE_CODE_EXECPATH'), shutil.which('claude'),
                 home / '.local' / 'bin' / ('claude.exe' if os.name == 'nt' else 'claude'), appdata / 'npm' / 'claude.cmd']
    else:
        paths = [os.environ.get('COOPAGENTS_CODEX_CLI'), shutil.which('codex'), *_running_paths('codex'),
                 appdata / 'npm' / 'codex.cmd']
    found = [str(path) for path in paths if path and Path(path).is_file()]
    if not found:
        raise ConnectError('The %s command was not found; pass --cli with its full path' % tool)
    return [[path] for path in dict.fromkeys(found)]


def _run(command, timeout=120):
    try:
        return subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ConnectError('Could not run the native CLI; pass --cli with the full path of a working one') from None


def _registered(tool, cli, name):
    """Return the registered command line for `name`, or None when absent."""
    if tool == 'codex':
        result = _run(cli + ['mcp', 'get', name, '--json'])
        if result.returncode != 0 or not result.stdout.strip():
            if 'No MCP server named' in result.stderr + result.stdout:
                return None
            raise ConnectError('The Codex CLI failed to read its configuration; pass --cli with the path '
                               'of a Codex CLI that can (for example the one bundled with the desktop app)')
        try:
            transport = json.loads(result.stdout)['transport']
            return [transport['command']] + list(transport.get('args') or [])
        except (ValueError, KeyError, TypeError):
            raise ConnectError('Unexpected output from codex mcp get') from None
    result = _run(cli + ['mcp', 'get', name])
    text = result.stdout + result.stderr
    if result.returncode != 0:
        if re.search(r'no mcp server', text, re.I):
            return None
        raise ConnectError('The Claude CLI failed to read its configuration; pass --cli with the path of a working one')
    command = re.search(r'^\s*Command:\s*(.*)$', text, re.M)
    args = re.search(r'^\s*Args:\s*(.*)$', text, re.M)
    if not command:
        raise ConnectError('Unexpected output from claude mcp get')
    return [command.group(1).strip()] + (args.group(1).split() if args else [])


def _matches(registered, expected):
    if not registered:
        return False
    same_python = os.path.normcase(os.path.normpath(registered[0])) == os.path.normcase(os.path.normpath(expected[0]))
    # Claude prints arguments space-joined, so compare the joined argument line.
    return same_python and ' '.join(registered[1:]) == ' '.join(expected[1:])


def _add(tool, cli, name, command):
    if tool == 'codex':
        result = _run(cli + ['mcp', 'add', name, '--'] + command)
    else:
        result = _run(cli + ['mcp', 'add', '--transport', 'stdio', '--scope', 'user', name, '--'] + command)
    if result.returncode != 0:
        raise ConnectError('The native CLI refused to add the MCP server')


def skills_root(tool):
    if tool == 'codex':
        return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'skills'
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'skills'


def _skill_files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts}


def _same_text(left, right):
    # A copy downloaded from GitHub (LF) and one from a Windows-built wheel (CRLF) are the same skill.
    normal = lambda files: {name: data.replace(b'\r\n', b'\n') for name, data in files.items()}
    return normal(left) == normal(right)


def install_skill(tool, root=None):
    """Copy the packaged skill; an existing different copy is kept as a dated backup, never removed."""
    source = Path(__file__).resolve().parent / 'skills' / SKILL_NAME
    files = _skill_files(source)
    if 'SKILL.md' not in files:
        raise ConnectError('The installed package is missing its skill files')
    target = Path(root or skills_root(tool)) / SKILL_NAME
    state, backup = 'installed', None
    if target.exists() or target.is_symlink():
        if target.is_dir() and _same_text(_skill_files(target), files):
            return {'skill': 'present', 'skill_path': str(target)}
        # Outside the skills folder: a backup inside it would load as a second skill.
        backups = target.parent.parent / 'coopagents-backups'
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / (SKILL_NAME + '-' + time.strftime('%Y%m%d%H%M%S'))
        shutil.move(str(target), str(backup))
        state = 'updated'
    for relative, data in files.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    result = {'skill': state, 'skill_path': str(target)}
    if backup is not None:
        result['skill_backup'] = str(backup)
    return result


def connect(tool, profile_path, name=None, cli=None, skills=None, wake=False, project_dir=None):
    if tool not in TOOLS:
        raise ConnectError('Tool must be claude or codex')
    path = checked_path(profile_path).resolve()
    profile = read_profile(path)
    name = name or server_name(profile)
    if not NAME_PATTERN.match(name):
        raise ConnectError('Server names may only contain letters, digits, - and _')
    command = bridge_command(path)
    failure = None
    for cli in cli_candidates(tool, cli):
        try:
            registered = _registered(tool, cli, name)
            break
        except ConnectError as error:
            failure = error
    else:
        raise failure or ConnectError('No usable native CLI was found')
    if registered is None:
        _add(tool, cli, name, command)
        state = 'added'
    elif _matches(registered, command):
        state = 'already_configured'
    else:
        raise ConnectError('An MCP server named %s already exists with a different command; '
                           'pass --name to choose another name' % name)
    if not _matches(_registered(tool, cli, name), command):
        raise ConnectError('The MCP server was not found in the native configuration after adding it')
    result = {'tool': tool, 'cli': cli[-1], 'server': name, 'config': state, 'verified': True, 'profile': str(path),
              'room_id': profile['room_id'], 'member_id': profile['member_id']}
    result.update(install_skill(tool, skills))
    label = 'Claude Code' if tool == 'claude' else 'Codex'
    steps = ['Tell the user to start a new %s session in the repository folder: the current session cannot load '
             'the new tools. There, the agent calls whoami to check the connection.' % label]
    if wake:
        from .space_wake import install as install_wake
        result['wake'] = install_wake(str(path), tool, 'project', project_dir or os.getcwd())
        if tool == 'codex':
            steps.append('Wake-up is installed; in the new Codex session the user must review and trust the '
                         'Coopagents hook in /hooks before it runs.')
        else:
            steps.append('Wake-up is installed and starts with that new session.')
    else:
        steps.append('Wake-up is off. To turn it on later, the user can say "Turn on Coopagents wake-up for this '
                     'repo" in a session of that folder; the agent then calls the install_wake tool.')
    result['next'] = ' '.join(steps)
    return result
