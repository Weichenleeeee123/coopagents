"""Bounded real-model development-checkout cold start; all evidence stays in .local.

Run with the checkout's isolated Python. No model overrides, permission bypass,
real native settings changes or file removal. This is single-machine evidence;
it cannot certify two people, different NATs, cross-device wake or other OSes.
The retained host is stopped on exit. Wake is deliberately a separate test.
"""
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import time
import tomllib
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]


def toml_value(value):
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(k) + ' = ' + toml_value(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(toml_value(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=True)


def prepare_homes(run, codex_source, claude_settings, environ=None, tool=None):
    """Copy auth and provider/model settings only, never native MCP/hooks/plugins."""
    from coopagents.spaces import private_directory, private_write, protect
    private_directory(run)
    for name in ('home', 'codex-home', 'claude-home', 'coopagents-home', 'tmp'):
        private_directory(run / name)
    source_env = os.environ if environ is None else environ
    # Start with process/runtime essentials, rather than forwarding every
    # credential present in the parent's environment to either native model.
    runtime_keys = set(('PATH PATHEXT SYSTEMROOT WINDIR COMSPEC OS APPDATA LOCALAPPDATA '
        'PROGRAMFILES PROGRAMFILES(X86) PROGRAMW6432 PROCESSOR_ARCHITECTURE NUMBER_OF_PROCESSORS '
        'PSMODULEPATH TERM COLORTERM LANG LC_ALL TZ HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY '
        'SSL_CERT_FILE SSL_CERT_DIR REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS').split())
    env = {k: v for k, v in source_env.items() if k.upper() in runtime_keys}
    env.update(HOME=str(run / 'home'), USERPROFILE=str(run / 'home'),
               CODEX_HOME=str(run / 'codex-home'), CLAUDE_CONFIG_DIR=str(run / 'claude-home'),
               COOPAGENTS_HOME=str(run / 'coopagents-home'), TMP=str(run / 'tmp'),
               TEMP=str(run / 'tmp'), TMPDIR=str(run / 'tmp'), PYTHONUTF8='1')
    auth = codex_source / 'auth.json'
    if tool in (None, 'codex') and auth.is_file():
        target = run / 'codex-home' / 'auth.json'
        with target.open('xb') as stream:
            protect(target)
            stream.write(auth.read_bytes())
    source = codex_source / 'config.toml'
    config = tomllib.loads(source.read_text(encoding='utf-8')) if source.is_file() else {}
    allow = ('model', 'model_provider', 'model_reasoning_effort', 'model_reasoning_summary',
             'preferred_auth_method', 'forced_login_method')
    selected_config = {}
    if tool in (None, 'codex'):
        selected_config = {k: config[k] for k in allow if k in config}
        provider_name = config.get('model_provider', 'openai')
        provider = config.get('model_providers', {}).get(provider_name, {})
        if provider:
            selected_config['model_providers'] = {provider_name: provider}
        provider_env = {provider.get('env_key')}
        provider_env.update(provider.get('env_http_headers', {}).values())
        if provider_name == 'openai' or provider.get('requires_openai_auth'):
            provider_env.update(('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID'))
        for key in provider_env:
            if isinstance(key, str) and key in source_env:
                env[key] = source_env[key]
    native = run / 'codex-home' / 'config.toml'
    native.write_text(''.join(k + ' = ' + toml_value(v) + '\n' for k, v in selected_config.items()), encoding='utf-8')
    protect(native)
    settings = json.loads(claude_settings.read_text(encoding='utf-8')) if claude_settings.is_file() else {}
    claude_env = dict(source_env, **{k: str(v) for k, v in settings.get('env', {}).items()})
    backend_keys = {
        'bedrock': ('AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_REGION AWS_DEFAULT_REGION '
                    'AWS_PROFILE AWS_SHARED_CREDENTIALS_FILE AWS_CONFIG_FILE AWS_BEARER_TOKEN_BEDROCK '
                    'ANTHROPIC_BEDROCK_BASE_URL CLAUDE_CODE_SKIP_BEDROCK_AUTH'),
        'vertex': ('GOOGLE_APPLICATION_CREDENTIALS GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_QUOTA_PROJECT '
                   'CLOUD_ML_REGION ANTHROPIC_VERTEX_PROJECT_ID CLAUDE_CODE_SKIP_VERTEX_AUTH'),
        'foundry': ('ANTHROPIC_FOUNDRY_API_KEY ANTHROPIC_FOUNDRY_RESOURCE ANTHROPIC_FOUNDRY_BASE_URL '
                    'AZURE_CLIENT_ID AZURE_TENANT_ID AZURE_CLIENT_SECRET AZURE_FEDERATED_TOKEN_FILE'),
        'anthropic': ('ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_CUSTOM_HEADERS '
                      'CLAUDE_CODE_OAUTH_TOKEN'),
    }
    selected_backends = [name for name in ('bedrock', 'vertex', 'foundry')
                         if claude_env.get('CLAUDE_CODE_USE_' + name.upper(), '').lower() in ('1', 'true')]
    if tool in (None, 'claude') and len(selected_backends) > 1:
        raise ValueError('Multiple Claude provider backends are enabled')
    backend = selected_backends[0] if selected_backends else 'anthropic'
    if tool in (None, 'claude'):
        keys = set(backend_keys[backend].split())
        keys.update(('ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL '
                     'ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL').split())
        if backend != 'anthropic':
            keys.add('CLAUDE_CODE_USE_' + backend.upper())
        for key in keys:
            if key in claude_env:
                env[key] = claude_env[key]
    claude_native = {k: settings[k] for k in ('model',) if k in settings} if tool in (None, 'claude') else {}
    if tool in (None, 'claude') and backend == 'anthropic' and 'apiKeyHelper' in settings:
        claude_native['apiKeyHelper'] = settings['apiKeyHelper']
    private_write(run / 'claude-home' / 'settings.json',
                  claude_native)
    # An OAuth credential file is an authentication artifact, not personal settings.
    credentials = claude_settings.parent / '.credentials.json'
    if tool in (None, 'claude') and backend == 'anthropic' and credentials.is_file():
        private_write(run / 'claude-home' / '.credentials.json', json.loads(credentials.read_text(encoding='utf-8')))
    return env


def codex_tool_approvals(run, python, require):
    """Invocation-only approvals for the exact isolated bridge and stage tools."""
    if not require:
        return []
    allowed = {'whoami', 'read_team', 'read_inbox', 'send_request', 'reply'}
    if not set(require).issubset(allowed):
        raise ValueError('Unexpected acceptance tool')
    config = tomllib.loads((run / 'codex-home/config.toml').read_text(encoding='utf-8'))
    servers = config.get('mcp_servers', {})
    if len(servers) != 1:
        raise ValueError('Expected exactly one private synthetic server')
    server, entry = next(iter(servers.items()))
    args = entry.get('args', [])
    if (Path(entry.get('command', '')).resolve() != python.resolve() or len(args) != 4
            or args[:3] != ['-m', 'coopagents.space_bridge', '--profile']):
        raise ValueError('Unexpected native bridge command')
    profile = Path(args[3]).resolve()
    if not profile.is_relative_to((run / 'coopagents-home').resolve()):
        raise ValueError('Native bridge profile escaped the private run')
    from coopagents.space_connect import server_name
    if server != server_name(json.loads(profile.read_text(encoding='utf-8'))):
        raise ValueError('Native server does not match the synthetic room')
    prefix = 'mcp_servers.' + server
    settings = ['-c', prefix + '.enabled_tools=' + json.dumps(list(require))]
    for name in require:
        settings.extend(['-c', prefix + '.tools.' + name + '.approval_mode="approve"'])
    return settings


def host_reply_prompt(tool, nonce, answer_file):
    prompt = ('Use native Coopagents MCP tools to read_inbox and read_team. '
              f'Find request with marker {nonce}. ')
    if tool == 'codex':
        quoted = "'" + str(answer_file).replace("'", "''" if os.name == 'nt' else "'\"'\"'") + "'"
        command = ('Get-Content -LiteralPath ' if os.name == 'nt' else 'cat -- ') + quoted
        prompt += f'I explicitly authorize this exact read-only synthetic-file command: {command}. '
        prompt += 'Do not execute any other commands. '
    else:
        prompt += f'Use Read to read only the synthetic file {answer_file}. '
    return prompt + 'Reply with its exact text. Do not change files.'


def model_command(tool, executable, run, python, *, setup=False, require=()):
    if tool == 'codex':
        command = [executable, 'exec', '--sandbox', 'workspace-write' if setup else 'read-only',
                   '--add-dir', str(run)]
        if setup:
            command.extend(['-c', 'sandbox_workspace_write.network_access=true'])
        command.extend(codex_tool_approvals(run, python, require))
        return command + ['--json', '--output-last-message', str(run / 'last-message.txt'), '-']
    # Only the already-installed checkout's runtime helper can execute commands.
    # The model may read the explicitly authorized source Skill and synthetic repo.
    allowed = ['Read', 'mcp__coopagents_*']
    if setup:
        spellings = [str(python)]
        windows = PureWindowsPath(python)
        if windows.is_absolute() and len(windows.drive) == 2 and windows.drive[1] == ':':
            slash = windows.as_posix()
            spellings.extend([slash, '/' + windows.drive[0].lower() + slash[2:]])
        allowed.extend('Bash("' + executable_path + '" -m coopagents.space_runtime:*)'
                       for executable_path in dict.fromkeys(spellings))
    return [executable, '--print', '--verbose', '--output-format', 'stream-json',
            '--permission-prompts', 'none', '--add-dir', str(run),
            '--allowedTools', ','.join(allowed)]


def decoded_objects(value, depth=0):
    """Read native structured content and JSON TextContent, never assistant prose."""
    if depth > 12:
        return
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from decoded_objects(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from decoded_objects(child, depth + 1)


def claude_content(event):
    """System/permission records may have a string message instead of content."""
    message = event.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def native_results(tool, events):
    """Yield successful completed native calls, rejecting nested MCP error envelopes."""
    pending = {}
    for event in events:
        if tool == 'codex' and event.get('type') == 'item.completed':
            item = event.get('item', {})
            if (item.get('type') == 'mcp_tool_call' and item.get('status') == 'completed'
                    and not item.get('error') and item.get('result') is not None):
                result = item['result']
                if not any(v.get('isError') is True or v.get('is_error') is True for v in decoded_objects(result)):
                    yield item.get('tool', '').split('__')[-1], result
        if tool == 'claude':
            for block in claude_content(event):
                if block.get('type') == 'tool_use' and block.get('name', '').startswith('mcp__coopagents_'):
                    pending[block['id']] = block['name'].split('__')[-1]
                if block.get('type') == 'tool_result' and not block.get('is_error') and block.get('tool_use_id') in pending:
                    if not any(v.get('isError') is True or v.get('is_error') is True for v in decoded_objects(block)):
                        yield pending[block['tool_use_id']], block


def successful_tools(tool, events):
    return {name for name, result in native_results(tool, events)}


def native_identity_proven(tool, events, expected):
    """Compare the actual whoami result to the expected saved personal identity."""
    return any(isinstance(value.get('me'), dict) and all(value['me'].get(key) == expected[key]
               for key in ('room_id', 'member_id')) for name, result in native_results(tool, events)
               if name == 'whoami' for value in decoded_objects(result))


def network_proven(requested, host_state, guest_profile=None):
    """Do not certify P2P from a requested flag or a model's network claim."""
    if host_state.get('network') != requested:
        return False
    if requested == 'local':
        return guest_profile is None or not guest_profile.get('p2p')
    if requested != 'p2p':
        return False
    try:
        from coopagents.p2p import endpoint_id, validate_link
        actual_endpoint = endpoint_id(host_state['p2p_secret'])
        return guest_profile is None or validate_link(guest_profile.get('p2p'))['endpoint_id'] == actual_endpoint
    except (ValueError, KeyError, TypeError):
        return False


def exchange_proven(snapshot, guest, host, nonce, answer):
    return any(r.get('sender_member_id') == guest and r.get('receiver_member_id') == host
               and nonce in r.get('body', '') and any(p.get('author_member_id') == host
               and answer in p.get('body', '') for p in r.get('replies', []))
               for r in snapshot.get('requests', []))


def diagnostics_proven(snapshot, members):
    completed = {d.get('member_id') for d in snapshot.get('collaboration', {}).get('diagnostics', [])
                 if d.get('status') == 'completed'}
    return members.issubset(completed)


def assistant_text(tool, events):
    if tool == 'codex':
        return '\n'.join(e.get('item', {}).get('text', '') for e in events
                         if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message')
    return '\n'.join(block.get('text', '') for e in events if e.get('type') == 'assistant'
                     for block in claude_content(e) if block.get('type') == 'text')


def bounded(command, prompt, path, env, cwd, timeout):
    """No pipes retained by grandchildren, no cleanup; timeout terminates children."""
    prompt_path = path.with_suffix('.prompt.txt')
    prompt_path.write_text(prompt, encoding='utf-8')
    from coopagents.spaces import protect
    protect(prompt_path)
    with prompt_path.open('rb') as stdin, path.open('xb') as out:
        protect(path)
        process = subprocess.Popen(command, stdin=stdin, stdout=out, stderr=subprocess.STDOUT,
                                   env=env, cwd=cwd, start_new_session=os.name != 'nt')
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(process.pid)], capture_output=True, timeout=30)
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=30)
            return 'timeout'


def events_from(path):
    events = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
        except ValueError:
            pass
    return events


def registrations(env, tool, project):
    # Read in a child with the isolated environment, never mutate this process's home.
    script = ('import json,sys;from coopagents.space_connect import registered_spaces;'
              'print(json.dumps(registered_spaces(sys.argv[1],sys.argv[2])))')
    result = subprocess.run([sys.executable, '-c', script, tool, str(project)], env=env,
                            capture_output=True, text=True, timeout=30, check=True)
    entries = json.loads(result.stdout)
    if len(entries) != 1:
        raise RuntimeError('Expected one isolated native registration')
    entry = entries[0]
    if not Path(entry['profile']).resolve().is_relative_to(Path(env['COOPAGENTS_HOME']).resolve()):
        raise RuntimeError('Native registration escaped the private run')
    if Path(entry['python']).resolve() != Path(sys.executable).resolve():
        raise RuntimeError('Native registration used a different Python')
    return entry


def snapshot(profile_path):
    from coopagents.space_runtime import request
    from coopagents.spaces import read_profile
    profile = read_profile(profile_path)
    from coopagents.p2p import member_link
    with member_link(profile):
        return request(profile['origin'], '/api/snapshot', token=profile['web_token'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=['claude', 'codex'], default='claude', help='Run again with the other host for both create paths')
    parser.add_argument('--network', choices=['p2p', 'local'], default='p2p')
    parser.add_argument('--timeout', type=int, default=600, help='Seconds per new model session (six sessions maximum)')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare private homes without consuming model quota')
    parser.add_argument('--preflight-only', action='store_true', help='Two bounded default-model replies without tools; not acceptance')
    parser.add_argument('--stop-after-host-verification', action='store_true',
                        help='Only create/connect and verify the host in a new native model session; explicitly partial')
    parser.add_argument('--codex', default=shutil.which('codex'))
    parser.add_argument('--claude', default=shutil.which('claude'))
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 1800:
        parser.error('timeout must be between 1 and 1800 seconds')
    import coopagents
    if sys.prefix == sys.base_prefix or not Path(coopagents.__file__).resolve().is_relative_to(REPO / 'src'):
        parser.error('Use this checkout\'s isolated editable-install Python')
    if not args.codex or not args.claude:
        parser.error('Both native CLI executables are required')
    from coopagents.spaces import private_directory, private_write, read_json, read_profile
    run = private_directory(REPO / '.local' / 'cold-start-acceptance' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]))
    real_home = Path.home()
    host, guest = args.host, 'codex' if args.host == 'claude' else 'claude'
    environments = {tool: prepare_homes(run / tool, Path(os.environ.get('CODEX_HOME') or real_home / '.codex'),
                    Path(os.environ.get('CLAUDE_CONFIG_DIR') or real_home / '.claude') / 'settings.json', tool=tool) for tool in (host, guest)}
    projects = {tool: private_directory(run / tool / 'repo') for tool in (host, guest)}
    answer, nonce = 'answer-' + uuid4().hex, 'request-' + uuid4().hex
    for tool, project in projects.items():
        shutil.copytree(REPO / 'src/skills/coopagents-space', run / tool / 'checkout-skill')
        subprocess.run(['git', 'init', '-q', str(project)], check=True, capture_output=True, timeout=30)
        (project / 'README.md').write_text('# Synthetic acceptance repository\n', encoding='utf-8')
        (project / 'AGENTS.md').write_text('Never delete files. Only operate in this synthetic run.\n', encoding='utf-8')
    (projects[host] / 'acceptance-answer.txt').write_text(answer, encoding='utf-8')
    report = {'status': 'prepared', 'host': host, 'guest': guest, 'requested_network': args.network,
              'scope': 'single machine, wake disabled', 'sessions': [], 'checks': []}
    report['source_commit'] = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                             capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    report['source_dirty'] = bool(subprocess.run(['git', 'status', '--porcelain', '--', 'src', 'pyproject.toml'],
                                  cwd=REPO, capture_output=True, text=True, timeout=30, check=True).stdout.strip())
    private_write(run / 'summary.json', report)
    print('Private evidence: ' + str(run), flush=True)
    if args.prepare_only:
        return 0
    if args.preflight_only:
        for tool in (host, guest):
            command = ([args.codex, 'exec', '--sandbox', 'read-only', '--json', '-'] if tool == 'codex' else
                       [args.claude, '--print', '--output-format', 'stream-json', '--verbose', '--tools', ''])
            path = run / ('preflight-' + tool + '.jsonl')
            code = bounded(command, 'Reply with exactly COOPAGENTS_PREFLIGHT_OK. Do not use any tools.', path,
                           environments[tool], projects[tool], min(args.timeout, 120))
            ok = code == 0 and 'COOPAGENTS_PREFLIGHT_OK' in assistant_text(tool, events_from(path))
            report['checks'].append({'check': tool + ' default-model authentication preflight', 'ok': ok, 'exit': code})
            print(tool + ' preflight: ' + ('PASS' if ok else 'FAIL'), flush=True)
        report['status'] = 'preflight_passed' if all(c['ok'] for c in report['checks']) else 'preflight_failed'
        private_write(run / 'summary.json', report, update=True)
        return 0 if report['status'] == 'preflight_passed' else 1
    owner = None

    def turn(tool, stage, prompt, *, setup=False, require=(), expected_identity=None, verify_setup=False):
        env = environments[tool]
        path = run / (stage + '.jsonl')
        code = bounded(model_command(tool, getattr(args, tool), run / tool, Path(sys.executable), setup=setup, require=require),
                       prompt, path, env, projects[tool], args.timeout)
        events = events_from(path)
        tools = successful_tools(tool, events)
        ok = code == 0 and set(require).issubset(tools)
        entry = None
        if verify_setup:
            try:
                entry = registrations(env, tool, projects[tool])
                profile = read_profile(entry['profile'])
                setup_ok = diagnostics_proven(snapshot(entry['profile']), {profile['member_id']})
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
                setup_ok = False
            report['checks'].append({'check': stage + ' native registration and completed doctor challenge', 'ok': setup_ok})
            ok = ok and setup_ok
        if expected_identity is not None:
            identity_ok = native_identity_proven(tool, events, expected_identity)
            report['checks'].append({'check': stage + ' native whoami matches saved room/member', 'ok': identity_ok})
            ok = ok and identity_ok
        report['sessions'].append({'stage': stage, 'tool': tool, 'exit': code, 'native_tools': sorted(tools), 'ok': ok})
        if not ok and any(e.get('item', {}).get('status') == 'declined' and
                          'blocked by policy' in e.get('item', {}).get('aggregated_output', '').lower() for e in events):
            report['failure_reason'] = 'native_execution_blocked_by_policy'
        private_write(run / 'summary.json', report, update=True)
        print(stage + ': ' + ('PASS' if ok else 'FAIL'), flush=True)
        if not ok:
            raise RuntimeError('Native model session failed; inspect private evidence')
        return entry

    def cold_prompt(tool):
        return (f'Read the development checkout Skill at {(run / tool / "checkout-skill/SKILL.md").as_posix()}. '
                f'I explicitly authorize this unreleased development checkout. The isolated Python {sys.executable} '
                f'is already installed editable from that checkout with [space]; reuse it and use it explicitly. '
                f'You are {tool}. All settings and state directories are isolated in {run / tool}. '
                'Never delete files, change real native configuration or enable wake-up. '
                'Do not print credentials or environment variables. ')

    try:
        owner = turn(host, '01-create', cold_prompt(host) + f'Help me configure Coopagents here. Create a new {args.network} space '
             f'for this repository with owner {host}, connect this agent, then run doctor. Use the current configured model.',
             setup=True, verify_setup=True)
        host_profile = read_profile(owner['profile'])
        host_state = read_json(Path(owner['profile']).with_name('host.json'))
        report['observed_host_network'] = host_state.get('network')
        host_network_ok = network_proven(args.network, host_state)
        report['checks'].append({'check': 'persisted host network matches requested mode', 'ok': host_network_ok})
        if not host_network_ok:
            raise RuntimeError('Persisted host network did not match requested acceptance mode')
        invite_result = run / host / 'invitation-result.json'
        verification_prompt = (f'Using only the native Coopagents MCP tools, call whoami and compare '
             f'room_id={host_profile["room_id"]} and member_id={host_profile["member_id"]}, then read_team. '
             'Do not enable wake. ')
        invitation_prompt = (
             f'I authorize creating one invitation for my other agent: run "{sys.executable}" -m coopagents.space_runtime '
             f'invite --profile "{owner["profile"]}" --message en and redirect the complete JSON to "{invite_result}". '
             'Keep the invitation private. Do not enable wake.')
        turn(host, '02-host-new-session', verification_prompt + (
             'Do not create an invitation. This run stops after host verification.' if args.stop_after_host_verification
             else invitation_prompt), setup=not args.stop_after_host_verification, require=('whoami', 'read_team'),
             expected_identity=host_profile)
        if args.stop_after_host_verification:
            state = snapshot(owner['profile'])
            private_write(run / 'host-backend-snapshot.json', state)
            diagnostic = diagnostics_proven(state, {host_profile['member_id']})
            report['checks'].append({'check': 'host completed doctor challenge', 'ok': diagnostic})
            if not diagnostic:
                raise RuntimeError('Host diagnostic evidence incomplete')
            report['status'] = 'host_verified_partial'
        else:
            invitation = json.loads(invite_result.read_text(encoding='utf-8'))
            # Preserve the actual invitation message as supplied to the joiner; no README parsing/version invention.
            invitation_message = run / guest / 'invitation-message.txt'
            invitation_message.write_text(invitation['message'], encoding='utf-8')
            turn(guest, '03-join', cold_prompt(guest) + f'Read my private invitation message at {invitation_message}. '
                 f'I authorize joining that space as {guest}; use join --invitation-file with that path and --connect {guest}. '
                 'The invitation names published package metadata, but for this acceptance I explicitly authorize reusing the '
                 'same already-installed development checkout rather than installing a release. Run doctor.', setup=True, verify_setup=True)
            member = registrations(environments[guest], guest, projects[guest])
            guest_profile = read_profile(member['profile'])
            if guest_profile['room_id'] != host_profile['room_id'] or guest_profile['member_id'] == host_profile['member_id']:
                raise RuntimeError('Joined identity does not match the expected separate member')
            report['observed_join_network'] = 'p2p' if guest_profile.get('p2p') else 'local'
            peer_network_ok = network_proven(args.network, host_state, guest_profile)
            report['checks'].append({'check': 'joined network matches host and requested mode, including P2P endpoint', 'ok': peer_network_ok})
            if not peer_network_ok:
                raise RuntimeError('Joining member did not use the expected host network endpoint')
            turn(guest, '04-guest-new-session', f'Use only native Coopagents MCP tools. Call whoami and verify '
                 f'room_id={guest_profile["room_id"]}, member_id={guest_profile["member_id"]}; then read_team. '
                 f'Send a request to member {host_profile["member_id"]} asking for the exact text in its '
                 f'acceptance-answer.txt file. Include marker {nonce} in the body.', require=('whoami', 'read_team', 'send_request'),
                 expected_identity=guest_profile)
            turn(host, '05-host-reply', host_reply_prompt(host, nonce, projects[host] / 'acceptance-answer.txt'),
                 require=('read_inbox', 'read_team', 'reply'))
            turn(guest, '06-guest-read-reply', f'Use native Coopagents MCP read_team to find the reply to the request '
                 f'with marker {nonce}. Report its answer. Do not send a second request.', require=('read_team',))
            state = snapshot(owner['profile'])
            guest_state = snapshot(member['profile'])
            state.setdefault('collaboration', {}).setdefault('diagnostics', []).extend(
                guest_state.get('collaboration', {}).get('diagnostics', []))
            private_write(run / 'backend-snapshot.json', state)
            proven = exchange_proven(state, guest_profile['member_id'], host_profile['member_id'], nonce, answer)
            report['checks'].append({'check': 'backend request and real file-derived reply', 'ok': proven})
            diagnostics = diagnostics_proven(state, {guest_profile['member_id'], host_profile['member_id']})
            report['checks'].append({'check': 'both members completed doctor challenge', 'ok': diagnostics})
            consumed = answer in assistant_text(guest, events_from(run / '06-guest-read-reply.jsonl'))
            report['checks'].append({'check': 'guest model consumed the file-derived reply', 'ok': consumed})
            if not all((proven, diagnostics, consumed)):
                raise RuntimeError('Backend or model evidence incomplete')
            report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        # Never expose exception text: native errors can contain private response bodies.
        report['failure_type'] = type(error).__name__
    finally:
        # A model may create the host but fail before native registration. Stop
        # only retained host profiles beneath this run, even in that failure case.
        owned = list((run / host).rglob('profile.json'))
        report['collaboration_status'] = report['status']
        report['host_stopped'] = True
        for retained_profile in owned:
            try:
                if 'control_token' not in read_profile(retained_profile):
                    continue
                result = subprocess.run([sys.executable, '-m', 'coopagents.space_runtime', 'stop', '--profile', str(retained_profile)],
                                        env=environments[host], capture_output=True, timeout=60)
                report['host_stopped'] = report['host_stopped'] and result.returncode == 0
            except (OSError, ValueError, subprocess.TimeoutExpired):
                report['host_stopped'] = False
        if not report['host_stopped']:
            report['status'] = 'shutdown_failed'
        private_write(run / 'summary.json', report, update=True)
    print('Result: ' + report['status'] + ' (single machine; no wake/cross-device certification)')
    return 0 if report['status'] in ('passed', 'host_verified_partial') else 1


if __name__ == '__main__':
    raise SystemExit(main())
