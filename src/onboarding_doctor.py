"""Secret-free, read-only checks used by the agent-first setup path."""
import importlib.util
import json
import os
from pathlib import Path
import re
import site
import sys

from . import space_connect
from .spaces import checked_path


STATUSES = frozenset(('pass', 'fail', 'needs_user', 'unknown', 'skipped'))
REQUIRED_CHECKS = frozenset((
    'python_runtime', 'native_tool', 'mcp_configuration', 'skill_installation',
    'project_context', 'runtime_reachability', 'challenge_round_trip',
))
OPTIONAL_CHECKS = frozenset(('session_reload', 'wake_up', 'transport_path'))
_SECRET_KEY = re.compile(r'(?:token|secret|password|credential|profile)', re.I)
_SECRET_JSON = re.compile(
    r'("(?:agent_token|web_token|control_token|invite_token|password|secret)"\s*:\s*)"[^"]*"', re.I)
_BEARER = re.compile(r'(Bearer\s+)[^\s,;]+', re.I)


def _redact(value, secrets=(), key=None):
    if key and _SECRET_KEY.search(str(key)):
        return '[redacted]'
    if isinstance(value, dict):
        return {str(k): _redact(v, secrets, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), '[redacted]')
    text = _SECRET_JSON.sub(r'\1"[redacted]"', text)
    return _BEARER.sub(r'\1[redacted]', text)


def sanitize(value, secrets=()):
    """Return JSON-safe evidence with known credential-shaped values removed."""
    return _redact(value, tuple(str(secret) for secret in secrets if secret))


def make_check(identifier, status, summary, next_step='', evidence=None, *, secrets=()):
    if status not in STATUSES:
        raise ValueError('Unsupported diagnostic status')
    if not isinstance(identifier, str) or not identifier:
        raise ValueError('Diagnostic id is required')
    return {
        'id': identifier,
        'status': status,
        'summary': sanitize(summary, secrets),
        'next': sanitize(next_step, secrets),
        'evidence': sanitize(evidence or {}, secrets),
    }


def aggregate(checks):
    checks = [dict(item) for item in checks]
    required = [item for item in checks if item.get('id') in REQUIRED_CHECKS]
    if any(item.get('status') == 'fail' for item in required):
        overall = 'blocked'
    elif any(item.get('status') == 'needs_user' for item in required):
        overall = 'needs_user'
    elif any(item.get('status') == 'unknown' for item in required):
        overall = 'unknown'
    elif all(item.get('status') in ('pass', 'skipped', 'unknown') for item in required):
        overall = 'ready'
    else:
        overall = 'needs_user'
    next_steps = [item.get('next') for item in checks
                  if item.get('status') in ('fail', 'needs_user') and item.get('next')]
    return {
        'overall': overall,
        'checks': checks,
        'next': next_steps[0] if next_steps else 'No further action is required.',
    }


def _check_imports(names):
    return [name for name in names if importlib.util.find_spec(name) is None]


def python_runtime_check():
    interpreter = str(Path(sys.executable).resolve())
    try:
        user_site = Path(site.getusersitepackages()).resolve()
        in_user_site = Path(__file__).resolve().is_relative_to(user_site)
    except (OSError, ValueError, TypeError):
        user_site, in_user_site = None, False
    missing = _check_imports(('mcp', 'starlette', 'uvicorn', 'websockets', 'iroh'))
    evidence = {
        'version': '%d.%d.%d' % sys.version_info[:3],
        'interpreter': interpreter,
        'user_site_install': in_user_site,
        'space_dependencies': 'ready' if not missing else 'missing',
    }
    if in_user_site:
        return make_check(
            'python_runtime', 'fail',
            'Coopagents is installed in the user site instead of an isolated environment.',
            'Create a dedicated virtual environment and install the pinned Coopagents space extra.',
            evidence)
    if missing:
        return make_check(
            'python_runtime', 'fail',
            'The Coopagents space dependencies are not available.',
            'Install the pinned Coopagents release with its space extra in the isolated environment.',
            evidence | {'missing_dependencies': missing})
    return make_check('python_runtime', 'pass', 'The isolated Python environment is ready.', evidence=evidence)


def _tool_and_cli(tool=None, cli=None):
    if tool:
        if tool not in space_connect.TOOLS:
            return None, None, 'Choose Claude Code or Codex.'
        selected = tool
    else:
        try:
            selected = space_connect.resolve_tool(None)
        except space_connect.ConnectError:
            return None, None, 'Run doctor inside Claude Code or Codex, or pass --tool claude|codex.'
    try:
        candidates = space_connect.cli_candidates(selected, cli)
    except space_connect.ConnectError:
        return selected, None, 'Install the selected native CLI or pass its full path with --cli.'
    return selected, candidates[0] if candidates else None, None


def tool_check(tool=None, project_dir=None, cli=None):
    selected, executable, error = _tool_and_cli(tool, cli)
    if error and selected is None:
        return make_check('native_tool', 'needs_user', 'The current agent tool could not be identified.', error)
    if error:
        return make_check('native_tool', 'needs_user', 'The selected native tool was not found.', error,
                          {'tool': selected})
    return make_check('native_tool', 'pass', 'The selected native tool is available.',
                      evidence={'tool': selected, 'cli_found': bool(executable)})


def skill_root(tool, root=None):
    return Path(root) if root is not None else space_connect.skills_root(tool)


def _skill_files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob('*')) if path.is_file() and '__pycache__' not in path.parts}


def skill_check(tool, root=None):
    target = skill_root(tool, root) / space_connect.SKILL_NAME
    source = Path(space_connect.__file__).resolve().parent / 'skills' / space_connect.SKILL_NAME
    if not target.is_dir():
        return make_check('skill_installation', 'needs_user', 'The Coopagents Skill is not installed for this tool.',
                          'Run the Coopagents connect helper, then run doctor again.',
                          {'tool': tool, 'installed': False})
    try:
        same = space_connect._same_text(_skill_files(target), _skill_files(source))
    except (OSError, ValueError):
        same = False
    if not same:
        return make_check('skill_installation', 'needs_user', 'A different Coopagents Skill is installed for this tool.',
                          'Review the Skill version and run the connect helper; the existing copy will be retained.',
                          {'tool': tool, 'installed': True, 'matches_package': False})
    return make_check('skill_installation', 'pass', 'The Coopagents Skill matches this package.',
                      evidence={'tool': tool, 'installed': True, 'matches_package': True})


def mcp_check(tool, profile_path, *, cli=None, name=None):
    if not tool or not profile_path:
        return make_check('mcp_configuration', 'skipped', 'MCP configuration needs a tool and profile.',
                          'Provide a profile and run doctor inside the target agent.')
    try:
        path = checked_path(profile_path).resolve()
        profile = json.loads(path.read_text(encoding='utf-8'))
        server = name or space_connect.server_name(profile)
        expected = space_connect.bridge_command(path)
        selected, executable, error = _tool_and_cli(tool, cli)
        if error:
            return make_check('mcp_configuration', 'needs_user', 'The native CLI could not be read.', error,
                              {'tool': selected, 'server': server})
        registered = space_connect._registered(selected, executable, server)
        if registered is None:
            return make_check('mcp_configuration', 'needs_user', 'The Coopagents MCP server is not registered.',
                              'Run the connect helper for this profile, then run doctor again.',
                              {'tool': selected, 'server': server, 'registered': False})
        if not space_connect._matches(registered, expected):
            return make_check('mcp_configuration', 'needs_user', 'The Coopagents server name is already used by another command.',
                              'Choose a new server name with --name; the existing entry was not changed.',
                              {'tool': selected, 'server': server, 'registered': True, 'matches_profile': False})
        return make_check('mcp_configuration', 'pass', 'The native MCP entry matches this profile.',
                          evidence={'tool': selected, 'server': server, 'registered': True, 'matches_profile': True})
    except Exception:
        return make_check('mcp_configuration', 'fail', 'The native MCP configuration could not be inspected.',
                          'Check the private profile and native tool configuration, then run doctor again.')


def local_checks(*, tool=None, profile_path=None, project_dir=None, cli=None, skills=None):
    selected, _, _ = _tool_and_cli(tool, cli)
    checks = [python_runtime_check(), tool_check(tool, project_dir, cli)]
    checks.append(mcp_check(selected, profile_path, cli=cli) if profile_path else
                  make_check('mcp_configuration', 'skipped', 'No private profile was provided.',
                             'Provide an existing profile or let the agent create a P2P space.'))
    checks.append(skill_check(selected, skills) if selected else
                  make_check('skill_installation', 'skipped', 'No native tool was selected.',
                             'Run doctor inside Claude Code or Codex.'))
    result = aggregate(checks)
    if not profile_path and result['overall'] == 'ready':
        result['overall'] = 'needs_user'
        result['next'] = 'Provide an invitation or let the agent create a P2P space in the current repository.'
    return result


def render_text(result):
    lines = ['Overall: ' + str(result.get('overall', 'unknown'))]
    for item in result.get('checks', []):
        lines.append('%s: %s — %s' % (item['id'], item['status'], item['summary']))
        if item.get('next') and item['status'] in ('fail', 'needs_user'):
            lines.append('Next: ' + item['next'])
    return '\n'.join(lines)
