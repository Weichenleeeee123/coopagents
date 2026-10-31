"""Secret-free, read-only checks used by the agent-first setup path."""
import importlib.util
from importlib import metadata
import json
import os
from pathlib import Path
import re
import secrets
import site
import sys
from urllib.error import HTTPError, URLError

from . import space_connect
from .p2p import member_link
from .spaces import checked_path, read_profile


STATUSES = frozenset(('pass', 'fail', 'needs_user', 'unknown', 'skipped'))
REQUIRED_CHECKS = frozenset((
    'python_runtime', 'native_tool', 'mcp_configuration', 'skill_installation',
    'project_context', 'runtime_reachability', 'challenge_round_trip',
))
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
    if any(item.get('status') == 'fail' for item in checks):
        overall = 'blocked'
    elif any(item.get('status') == 'needs_user' for item in checks):
        overall = 'needs_user'
    elif {item.get('id') for item in required} != REQUIRED_CHECKS or any(item.get('status') != 'pass' for item in required):
        overall = 'unknown'
    else:
        overall = 'ready'
    next_steps = [item['next'] for state in ('fail', 'needs_user', 'unknown', 'skipped')
                  for item in checks if item.get('status') == state and item.get('next')]
    return {
        'overall': overall,
        'checks': checks,
        'next': next_steps[0] if next_steps else ('No further action is required.' if overall == 'ready'
                                                else 'Complete the missing checks before using this connection.'),
    }


def _check_imports(names):
    missing = []
    for name in names:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def python_runtime_check():
    interpreter = str(Path(sys.executable).resolve())
    try:
        user_site = Path(site.getusersitepackages()).resolve()
        in_user_site = Path(__file__).resolve().is_relative_to(user_site)
    except (OSError, ValueError, TypeError):
        user_site, in_user_site = None, False
    missing = _check_imports(('mcp', 'starlette', 'uvicorn', 'websockets', 'iroh'))
    isolated = sys.prefix != sys.base_prefix
    try:
        package_version = metadata.version('coopagents')
    except metadata.PackageNotFoundError:
        package_version = 'unknown'
    evidence = {
        'version': '%d.%d.%d' % sys.version_info[:3],
        'interpreter': interpreter,
        'user_site_install': in_user_site,
        'isolated': isolated,
        'package_version': package_version,
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
    if not isolated:
        return make_check('python_runtime', 'needs_user', 'This Python interpreter is not in a virtual environment.',
                          'Use a dedicated virtual environment with the pinned Coopagents space extra.', evidence)
    return make_check('python_runtime', 'pass', 'The isolated Python environment is ready.', evidence=evidence)


def _tool_and_cli(tool=None, cli=None):
    try:
        if tool and tool not in space_connect.TOOLS:
            raise space_connect.ConnectError('Unsupported tool')
        selected = space_connect.resolve_tool(tool)
    except space_connect.ConnectError:
        return None, None, 'Run doctor in the intended agent; --tool must match that agent.'
    try:
        candidates = space_connect.cli_candidates(selected, cli)
    except space_connect.ConnectError:
        return selected, None, 'Install the selected native CLI or pass its full path with --cli.'
    return selected, candidates, None


def tool_check(tool=None, project_dir=None, cli=None):
    selected, candidates, error = _tool_and_cli(tool, cli)
    if error and selected is None:
        return make_check('native_tool', 'needs_user', 'The current agent tool could not be identified.', error)
    if error:
        return make_check('native_tool', 'needs_user', 'The selected native tool was not found.', error,
                          {'tool': selected})
    for executable in candidates:
        try:
            result = space_connect._run(executable + ['--version'], timeout=10)
            version = re.search(r'\b(\d+\.\d+(?:\.\d+)?)\b', result.stdout)
            if result.returncode == 0 and version:
                return make_check('native_tool', 'pass', 'The selected native tool is available.',
                                  evidence={'tool': selected, 'cli_found': True, 'version': version.group(1)})
        except space_connect.ConnectError:
            continue
    return make_check('native_tool', 'needs_user', 'The native CLI version could not be verified.',
                      'Select a working CLI with --cli and rerun doctor.', {'tool': selected})


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
        return make_check('mcp_configuration', 'skipped', 'A tool and profile are required.')
    try:
        inspected = space_connect.inspect_configuration(tool, profile_path, cli=cli, name=name)
        config = inspected['config']
        evidence = {'tool': tool, 'server': inspected['server'], 'state': config}
        if config == 'matching':
            return make_check('mcp_configuration', 'pass', 'The native MCP entry matches this profile.',
                              evidence=evidence)
        if config == 'missing':
            return make_check('mcp_configuration', 'needs_user', 'The native MCP entry is missing.',
                              'Run connect for this profile, then run doctor again.', evidence)
        return make_check('mcp_configuration', 'needs_user', 'The native MCP entry conflicts with this profile.',
                          'Choose a different --name; the existing entry was preserved.', evidence)
    except Exception:
        return make_check('mcp_configuration', 'fail', 'The native MCP configuration could not be inspected.',
                          'Check the private profile and choose a working CLI with --cli.')


def local_checks(*, tool=None, profile_path=None, project_dir=None, cli=None, skills=None, name=None):
    native = tool_check(tool, project_dir, cli)
    selected = native['evidence'].get('tool')
    checks = [python_runtime_check(), native]
    connections = []
    if profile_path:
        checks.append(mcp_check(selected, profile_path, cli=cli, name=name))
    elif selected:
        try:
            entries = space_connect.registered_spaces(selected, project_dir or os.getcwd())
            connections = [{k: entry[k] for k in ('server', 'python', 'profile')} for entry in entries]
            checks.append(make_check('mcp_configuration', 'needs_user',
                                     'Existing connections require a target profile.' if entries else 'No Coopagents connection is registered.',
                                     'Select the profile for this repository; do not guess between spaces.' if entries
                                     else 'Provide an invitation or create a P2P space for this repository.',
                                     {'connection_count': len(entries)}))
        except Exception:
            checks.append(make_check('mcp_configuration', 'fail', 'The native configuration could not be read.',
                                     'Inspect the native configuration before creating another space.'))
    else:
        checks.append(make_check('mcp_configuration', 'skipped', 'Select the current agent first.'))
    checks.append(skill_check(selected, skills) if selected else
                  make_check('skill_installation', 'skipped', 'No native tool was selected.'))
    result = aggregate(checks)
    result['connections'] = connections
    return result


def _request_profile(profile, path, *, token=None, data=None):
    # Import lazily to keep the diagnostic core usable without starting a runtime.
    from .space_runtime import request
    from .checkpoint_hook import bounded_call
    return bounded_call(lambda: request(profile['origin'], path, token=token or profile['agent_token'], data=data), 10)


def profile_checks(profile_path, *, tool=None, project_dir=None, cli=None, skills=None):
    """Verify a private profile, its target identity and its diagnostic challenge."""
    try:
        path = checked_path(profile_path).resolve()
        profile = read_profile(path)
    except Exception:
        return aggregate([
            make_check('project_context', 'fail', 'The private Coopagents profile is invalid or unavailable.',
                       'Use the profile path returned by create or join; no profile was changed.'),
            make_check('runtime_reachability', 'skipped', 'The invalid profile was not used for a network request.'),
            make_check('challenge_round_trip', 'skipped', 'The invalid profile could not run a diagnostic challenge.'),
            make_check('transport_path', 'unknown', 'The transport path is unknown.'),
            make_check('session_reload', 'needs_user', 'The current session has not been checked.',
                       'Start a new agent session after the profile is configured.'),
            make_check('wake_up', 'skipped', 'Wake-up is optional and was not changed.'),
        ])

    secrets_to_hide = (profile.get('agent_token'), profile.get('web_token'), profile.get('control_token'))
    checks = [make_check('project_context', 'pass', 'The private profile is valid for one Coopagents space.',
                         evidence={'room_id': profile['room_id'], 'member_id': profile['member_id']},
                         secrets=secrets_to_hide)]
    identity_verified = False
    try:
        with member_link(profile) as link:
            identity = _request_profile(profile, '/api/me')
            me = identity.get('me') if isinstance(identity, dict) else None
            if not isinstance(me, dict) or me.get('room_id') != profile['room_id'] \
                    or me.get('member_id') != profile['member_id'] or me.get('kind') != 'agent':
                raise ValueError('The authenticated identity does not match the private profile')
            identity_verified = True
            checks.append(make_check('runtime_reachability', 'pass', 'The space accepted the personal agent identity.',
                                     evidence={'room_id': me['room_id'], 'member_id': me['member_id'], 'kind': me['kind']},
                                     secrets=secrets_to_hide))
            if link is not None:
                try:
                    path_info = link.path()
                    state = path_info.get('state', 'unknown')
                    path_status = 'pass' if state in ('direct', 'relay') else (
                        'fail' if state == 'disconnected' else 'unknown')
                    checks.append(make_check('transport_path', path_status,
                                             'The P2P transport reported its current path.' if path_status != 'fail'
                                             else 'The P2P transport is disconnected.',
                                             evidence={'state': state, 'rtt_ms': path_info.get('rtt_ms')},
                                             secrets=secrets_to_hide))
                except Exception:
                    checks.append(make_check('transport_path', 'unknown', 'The P2P transport path is not available.'))
            elif profile.get('p2p'):
                checks.append(make_check('transport_path', 'unknown', 'An existing P2P bridge is being reused; its route is not exposed.',
                                         evidence={'state': 'unknown', 'bridge_reused': True}))
            else:
                state = 'https' if profile['origin'].startswith('https://') else 'loopback'
                checks.append(make_check('transport_path', 'pass',
                                         'The profile uses its configured service origin.',
                                         evidence={'state': state}))

            try:
                challenge = secrets.token_urlsafe(24)
                started = _request_profile(profile, '/api/diagnostics/start', data={'challenge': challenge})
                diagnostic_id = started.get('diagnostic_id') if isinstance(started, dict) else None
                if not isinstance(diagnostic_id, str) or not diagnostic_id or len(diagnostic_id) > 128:
                    raise ValueError('Invalid diagnostic id')
                read = _request_profile(profile, '/api/diagnostics/read', data={'diagnostic_id': diagnostic_id})
                if (read.get('diagnostic_id') != diagnostic_id or read.get('challenge') != challenge
                        or not isinstance(read.get('proof'), str) or not 1 <= len(read['proof']) <= 128):
                    raise ValueError('The diagnostic challenge readback did not match')
                completed = _request_profile(
                    profile, '/api/diagnostics/complete',
                    data={'diagnostic_id': diagnostic_id, 'proof': read.get('proof')})
                if completed.get('status') != 'completed' or completed.get('diagnostic_id') != diagnostic_id:
                    raise ValueError('The diagnostic challenge did not complete')
                checks.append(make_check('challenge_round_trip', 'pass', 'The authenticated diagnostic challenge completed.',
                                         evidence={'status': 'completed'},
                                         secrets=secrets_to_hide + (challenge, read.get('proof'))))
            except Exception:
                checks.append(make_check('challenge_round_trip', 'fail', 'The diagnostic challenge did not complete.',
                                         'Retry doctor after the agent identity is reachable; no credential was changed.',
                                         secrets=secrets_to_hide))
    except Exception as error:
        reason = ('credential_rejected' if isinstance(error, HTTPError) and error.code in (401, 403)
                  else 'endpoint_error' if isinstance(error, HTTPError)
                  else 'unreachable' if isinstance(error, (OSError, URLError, TimeoutError))
                  else 'identity_mismatch' if isinstance(error, ValueError) else 'connection_failed')
        if identity_verified:
            checks = [c for c in checks if c['id'] != 'transport_path']
            checks.append(make_check('transport_path', 'fail', 'The diagnostic transport did not close cleanly.',
                                     'Check the host and rerun doctor.', {'reason': reason}))
        else:
            checks.append(make_check('runtime_reachability', 'fail', 'Personal identity verification failed.',
                                     'Obtain a renewed personal credential from the owner.' if reason == 'credential_rejected'
                                     else 'Check that host and member use compatible Coopagents versions.' if reason == 'endpoint_error'
                                     else 'Check the host and network, then rerun doctor.' if reason == 'unreachable'
                                     else 'Verify the trusted project and personal profile; do not change destinations automatically.',
                                     {'reason': reason}))
            checks.append(make_check('transport_path', 'unknown', 'The transport path is unknown.'))
            checks.append(make_check('challenge_round_trip', 'skipped', 'Identity verification must pass before the challenge.'))

    checks.extend([
        make_check('session_reload', 'needs_user', 'The native configuration may require a new agent session.',
                    'Start a new session and call whoami, then read_team to verify the loaded MCP connection.'),
        make_check('wake_up', 'skipped', 'Wake-up is optional and was not changed.'),
    ])
    return aggregate(checks)


def wake_check(tool, profile_path, project_dir=None):
    """Inspect hook files only; never initialize wake state or grant native trust."""
    if tool not in space_connect.TOOLS or not profile_path:
        return make_check('wake_up', 'skipped', 'Wake-up is optional; no profile and tool were selected.')
    from .space_wake import hook_command, settings_path, _ours
    try:
        expected = hook_command(profile_path, tool)
        user_root = Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex') if tool == 'codex' else Path(
            os.environ.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude')
        paths = [settings_path(tool, 'project', project_dir),
                 user_root / ('hooks.json' if tool == 'codex' else 'settings.json')]
        found, matched = False, set()
        for path in dict.fromkeys(paths):
            if not path.exists():
                continue
            path = checked_path(path)
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('Settings too large')
            document = json.loads(path.read_text(encoding='utf-8'))
            for event, groups in document.get('hooks', {}).items():
                for group in groups:
                    found = found or _ours(group)
                    if any(h.get('command') == expected and h.get('type') == 'command'
                           and (tool == 'codex' or h.get('asyncRewake') is True)
                           for h in group.get('hooks', [])):
                        matched.add(event)
        configured = {'Stop'}.issubset(matched) if tool == 'codex' else {'Stop', 'SessionStart'}.issubset(matched)
        if configured:
            return make_check('wake_up', 'needs_user' if tool == 'codex' else 'pass',
                              'Matching wake hooks are configured; execution has not been verified.',
                              'Review the hook in /hooks; doctor cannot observe native trust.' if tool == 'codex'
                              else 'Verify wake-up separately in a real open session.',
                              {'configured': True, 'trusted': 'unknown', 'execution': 'unknown'})
        return make_check('wake_up', 'unknown' if found else 'skipped',
                          'Other or partial Coopagents hooks exist.' if found else 'Wake-up is not configured in the inspected files.',
                          'Ask to enable wake-up only if wanted; existing hooks were not changed.',
                          {'configured': False})
    except Exception:
        return make_check('wake_up', 'unknown', 'Wake hook settings could not be inspected.',
                          'Inspect the native hook settings; doctor did not change them.')


def run(*, profile_path=None, tool=None, project_dir=None, cli=None, skills=None, name=None):
    """Run local checks and, when supplied, profile/network checks."""
    local = local_checks(tool=tool, profile_path=profile_path, project_dir=project_dir,
                         cli=cli, skills=skills, name=name)
    checks = local['checks']
    if project_dir and not Path(project_dir).is_dir():
        checks.append(make_check('project_context', 'fail', 'The repository folder does not exist.',
                                 'Select an existing repository directory.'))
    elif profile_path:
        checks.extend(profile_checks(profile_path, tool=tool, project_dir=project_dir, cli=cli, skills=skills)['checks'])
    else:
        checks.extend([
            make_check('project_context', 'skipped', 'No private profile was provided.',
                       'Provide an invitation or let the agent create a P2P space.'),
            make_check('runtime_reachability', 'skipped', 'No profile was provided for a network check.'),
            make_check('transport_path', 'unknown', 'The transport path is unknown until a space is connected.'),
            make_check('challenge_round_trip', 'skipped', 'No profile was provided for a diagnostic challenge.'),
            make_check('session_reload', 'needs_user', 'No native session has been verified yet.',
                       'Run doctor again after connecting the profile.'),
            make_check('wake_up', 'skipped', 'Wake-up is optional and was not changed.'),
        ])
    result = aggregate(checks)
    if profile_path:
        selected = next(c for c in checks if c['id'] == 'native_tool')['evidence'].get('tool')
        checks = [c for c in checks if c['id'] != 'wake_up']
        checks.append(wake_check(selected, profile_path, project_dir))
        result = aggregate(checks)
    result['connections'] = local['connections']
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
    for connection in result.get('connections', []):
        lines.append('Registered connection: ' + json.dumps(connection, ensure_ascii=True))
    lines.append('Next: ' + result['next'])
    return '\n'.join(lines)
