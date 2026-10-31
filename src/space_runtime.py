"""Agent-managed personal space CLI and an owned hidden supervisor."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

from .coordination import CoordinationService
from .p2p import member_link, validate_link
from .spaces import (checked_path, default_state_dir, explain, private_directory, private_write, read_json,
                     read_profile, safe_profile, validate_origin)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Credential requests must not redirect')


def request(origin, path, *, token=None, data=None):
    validate_origin(origin)
    headers = {'Accept': 'application/json', 'Origin': origin}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = None
    if data is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(data).encode()
    req = urllib.request.Request(origin + path, data=body, headers=headers)
    # Do not route loopback control through an environment configured proxy.
    proxy = urllib.request.ProxyHandler({}) if urlsplit(origin).hostname in ('127.0.0.1', 'localhost') else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(NoRedirect(), proxy)
    with opener.open(req, timeout=5) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('Response exceeded limit')
    return json.loads(raw)


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def runtime_paths(profile_path):
    profile_path = checked_path(profile_path)
    return profile_path, profile_path.parent / 'host.json'


def web_credential(profile):
    if not profile.get('web_token'):
        raise ValueError('Personal web credential required for this operation')
    return profile['web_token']


def status(profile_path):
    profile = read_profile(profile_path)
    result = safe_profile(profile, profile_path)
    try:
        if 'control_token' in profile:
            health = request(profile['control_origin'], '/status', token=profile['control_token'])
        else:
            with member_link(profile) as link:
                me = request(profile['origin'], '/api/me', token=profile['agent_token'])
                health = {'room_id': me['me']['room_id'], 'status': 'reachable'}
                if link is not None:
                    health['p2p'] = link.path()
        if health['room_id'] != profile['room_id']:
            raise ValueError('Unexpected space identity')
        # Startup can atomically replace the origin while this control request
        # waits. Return the current profile once readiness is authenticated.
        result = safe_profile(read_profile(profile_path), profile_path)
        result['status'] = health['status']
        if 'p2p' in health:
            result['p2p'] = health['p2p']
    except (OSError, ValueError, KeyError, RuntimeError):
        result['status'] = 'unreachable'
    return result


def start(profile_path):
    profile_path, host_path = runtime_paths(profile_path)
    profile, host = read_profile(profile_path), read_json(host_path)
    if not profile.get('control_token'):
        raise ValueError('Owner host profile required')
    if status(profile_path)['status'] != 'unreachable':
        raise ValueError('Space runtime is already running')
    # Child command contains state paths only; credentials stay in private files.
    log_path = profile_path.parent / ('runtime-' + uuid4().hex + '.log')
    with log_path.open('xb') as log:
        from .spaces import protect
        protect(log_path)
        child = subprocess.Popen([sys.executable, '-m', 'coopagents.space_runtime', '_serve',
                                  '--profile', str(profile_path)], stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('Runtime startup failed; see the private runtime log %s' % log_path)
        result = status(profile_path)
        if result['status'] == 'running':
            threading.Thread(target=child.wait, daemon=True).start()
            return result
        time.sleep(.2)
    # A startup cancellation belongs only to this specific spawned child.
    child.terminate()
    child.wait(timeout=10)
    raise RuntimeError('Runtime did not become ready')


def create(name, owner, state_dir, network='p2p', public_url=None, cloudflared=None):
    state = private_directory(state_dir)
    profile_path, host_path = runtime_paths(state / 'profile.json')
    if profile_path.exists() or host_path.exists() or (state / 'space.sqlite3').exists():
        raise FileExistsError('A space already exists in %s; use start --profile %s to resume it, or omit '
                              '--state-dir to create a new one' % (state, profile_path))
    if network not in ('p2p', 'local', 'quick', 'external'):
        raise ValueError('Unsupported network')
    if network == 'external':
        from .config import public_origin
        public_url = public_origin(public_url)
    elif public_url:
        raise ValueError('Public URL is only accepted in external mode')
    if network == 'quick' and not cloudflared:
        raise ValueError('Quick mode requires a verified cloudflared path')
    port, control_port = available_port(), available_port()
    while control_port == port:
        control_port = available_port()
    local = 'http://127.0.0.1:' + str(port)
    service = CoordinationService(state / 'space.sqlite3')
    identity = service.identity.create_room(name, owner)
    profile = dict(schema_version=1, origin=public_url or local,
                   room_id=identity['room_id'], member_id=identity['member_id'],
                   web_token=identity['web_token'], agent_token=identity['agent_token'],
                   control_origin='http://127.0.0.1:' + str(control_port),
                   control_token=secrets.token_urlsafe(32))
    private_write(profile_path, profile)
    host = dict(schema_version=1, network=network, local_origin=local,
                cloudflared=str(checked_path(cloudflared)) if cloudflared else None)
    if network == 'p2p':
        from .p2p import new_secret
        # The endpoint key is the space's stable network identity across restarts.
        host['p2p_secret'] = new_secret()
    private_write(host_path, host)
    return start(profile_path)


def serve(profile_path):
    import uvicorn
    from .space_server import create_space_app, create_control_app
    from .tunnels import QuickTunnel
    profile_path, host_path = runtime_paths(profile_path)
    profile, host = read_profile(profile_path), read_json(host_path)
    service = CoordinationService(profile_path.parent / 'space.sqlite3')
    principal = service.identity.authenticate(web_credential(profile), required_kind='web')
    if principal.role != 'owner' or principal.room_id != profile['room_id']:
        raise ValueError('Host profile identity does not match')
    stop = threading.Event()
    ready = threading.Event()
    tunnel = None
    link = None
    servers, threads = [], []
    # Reserve runtime ownership with an OS file lock retained for this worker's
    # entire lifetime. No PID-based signalling or stale-file deletion is needed.
    lock_path = profile_path.parent / 'runtime.lock'
    with lock_path.open('a+b') as runtime_lock:
        from .spaces import protect
        protect(lock_path)
        if runtime_lock.tell() == 0:
            runtime_lock.write(b'1')
            runtime_lock.flush()
        runtime_lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(runtime_lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if host['network'] == 'quick':
                tunnel = QuickTunnel(host['cloudflared'], host['local_origin'])
                if profile['origin'] != tunnel.origin:
                    profile['origin'] = tunnel.origin
                    private_write(profile_path, profile, update=True)
            elif host['network'] == 'p2p':
                from .p2p import HostLink
                link = HostLink(host['p2p_secret'], urlsplit(host['local_origin']).port)
            app = create_space_app(service, room_id=profile['room_id'], origin=profile['origin'])
            control = create_control_app(profile['control_origin'], profile['control_token'], stop, profile['room_id'], ready,
                                         service=service, source_token=profile['agent_token'], p2p=link)
            for application, origin in ((app, host['local_origin']), (control, profile['control_origin'])):
                config = uvicorn.Config(application, host='127.0.0.1', port=urlsplit(origin).port,
                                        log_level='warning', access_log=False, proxy_headers=False,
                                        ws_max_size=4096, ws_max_queue=4, ws_ping_interval=15,
                                        ws_ping_timeout=15)
                server = uvicorn.Server(config)
                servers.append(server)
                thread = threading.Thread(target=server.run, daemon=True)
                threads.append(thread)
                thread.start()
            while not stop.wait(.2):
                if all(server.started for server in servers):
                    ready.set()
                if any(not t.is_alive() for t in threads) or tunnel and tunnel.process.poll() is not None:
                    break
        finally:
            for server in servers:
                server.should_exit = True
            for thread in threads:
                thread.join(timeout=10)
            if tunnel:
                tunnel.close()
            if link:
                link.close()


def runtime_unlocked(profile_path):
    """Probe ownership without changing a lock file or signalling any process."""
    lock_path = checked_path(profile_path).parent / 'runtime.lock'
    if not lock_path.exists():
        return False  # A live owner must have created this durable lock file.
    try:
        with lock_path.open('r+b') as lock:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
    except OSError:
        return False
    return True


def stop(profile_path):
    profile = read_profile(profile_path)
    if not profile.get('control_token'):
        raise ValueError('Owner host profile required')
    result = request(profile['control_origin'], '/stop', token=profile['control_token'], data={})
    if result.get('room_id') != profile['room_id']:
        raise ValueError('Unexpected control space')
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if status(profile_path)['status'] == 'unreachable' and runtime_unlocked(profile_path):
            return safe_profile(profile, profile_path) | {'status': 'stopped'}
        time.sleep(.2)
    raise RuntimeError('Graceful shutdown remains pending')


def space_link(profile_path, profile):
    """Peer-to-peer link for invitations: the member's own, or the host's key."""
    if profile.get('p2p'):
        return profile['p2p']
    host_path = runtime_paths(profile_path)[1]
    if profile.get('control_token') and host_path.exists():
        host = read_json(host_path)
        if host.get('network') == 'p2p':
            from .p2p import endpoint_id
            return {'endpoint_id': endpoint_id(host['p2p_secret'])}
    return None


def invite(profile_path, share=False, message=None, hours=1):
    """Write a private invitation file; `message` (a language) also returns a shareable text with a one-time code."""
    from . import invite_message
    if message is not None and message not in invite_message.TEXT:
        raise ValueError('Unsupported message language')
    profile = read_profile(profile_path)
    with member_link(profile):
        invitation = request(profile['origin'], '/api/operations/invite', token=web_credential(profile),
                             data={'hours': hours})
        me = request(profile['origin'], '/api/me', token=web_credential(profile)) if message else None
    descriptor = dict(schema_version=1, origin=profile['origin'], **invitation)
    link = space_link(profile_path, profile)
    if link:
        descriptor['p2p'] = link
    path = checked_path(profile_path).parent / ('invitation-' + uuid4().hex + '.json')
    private_write(path, descriptor)
    result = safe_profile(profile, profile_path) | {'invitation_file': str(path), 'expires_at': invitation['expires_at']}
    if share:
        result['invitation'] = descriptor
    if message:
        # The text carries the bearer code; it is returned only on this explicit request.
        result['message'] = invite_message.compose(descriptor, me['me']['display_name'], me['room']['name'], message)
        result['local_only'] = invite_message.local_only(descriptor)
    return result


def join(invitation_file, name, state_dir, invitation_code=None):
    if (invitation_file is None) == (invitation_code is None):
        raise ValueError('Provide exactly one invitation file or code')
    from .invite_message import decode, load_invitation_file
    descriptor = load_invitation_file(invitation_file) if invitation_file is not None else decode(invitation_code)
    origin = validate_origin(descriptor['origin'])
    from datetime import datetime, timezone
    expiry = datetime.fromisoformat(descriptor['expires_at'])
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        raise ValueError('Invitation expired')
    link = validate_link(descriptor['p2p']) if 'p2p' in descriptor else None
    state = private_directory(state_dir)
    path = state / 'profile.json'
    if path.exists():
        raise FileExistsError('A personal profile already exists in %s; omit --state-dir to use a new folder' % state)
    target = {'origin': origin, 'room_id': descriptor['room_id']} | ({'p2p': link} if link else {})
    try:
        with member_link(target):
            identity = request(origin, '/api/join', data={'room_id': descriptor['room_id'],
                                                        'invite_token': descriptor['invite_token'], 'display_name': name})
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ValueError('The space did not accept this invitation: it was already used, has expired or was '
                             'revoked. Ask the inviter for a new invitation message.') from None
        raise
    if identity['room_id'] != descriptor['room_id']:
        raise ValueError('Invitation space does not match')
    profile = dict(schema_version=1, origin=origin,
                   **{key: identity[key] for key in ('room_id', 'member_id', 'web_token', 'agent_token')})
    if link:
        profile['p2p'] = link
    private_write(path, profile)
    return safe_profile(profile, path)


def reconnect(profile_path, origin, room_id):
    """User supplies the owner's newly trusted address; preserve member identity."""
    profile = read_profile(profile_path)
    if profile.get('p2p'):
        raise ValueError('Peer-to-peer profiles follow the host key; no address change is needed')
    origin = validate_origin(origin)
    if room_id != profile['room_id']:
        raise ValueError('Expected room does not match the personal profile')
    health = request(origin, '/health')
    if health.get('room_id') != room_id:
        raise ValueError('Destination space does not match')
    me = request(origin, '/api/me', token=profile['agent_token'])
    if me['me']['room_id'] != room_id or me['me']['member_id'] != profile['member_id']:
        raise ValueError('Destination personal identity does not match')
    profile['origin'] = origin
    private_write(profile_path, profile, update=True)
    return safe_profile(profile, profile_path)


def board(profile_path):
    """Issue a one-use local viewing URL through the authenticated host control."""
    profile = read_profile(profile_path)
    if not profile.get('control_token'):
        raise ValueError('Only the host owner can open its local board')
    return request(profile['control_origin'], '/board/open', token=profile['control_token'], data={})


def doctor(profile_path=None, tool=None, project_dir=None, cli=None, skills=None, name=None):
    """Run secret-free read-only onboarding checks for the current agent setup."""
    from . import onboarding_doctor
    return onboarding_doctor.run(profile_path=profile_path, tool=tool, project_dir=project_dir,
                                 cli=cli, skills=skills, name=name)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Manage a private agent-hosted Coopagents space')
    commands = parser.add_subparsers(dest='command', required=True)
    create_parser = commands.add_parser('create')
    create_parser.add_argument('--name', required=True)
    create_parser.add_argument('--owner', required=True)
    create_parser.add_argument('--state-dir', help='New private folder (default: a new folder under ~/.coopagents/spaces)')
    create_parser.add_argument('--network', choices=['p2p', 'local', 'quick', 'external'], default='p2p')
    create_parser.add_argument('--public-url')
    create_parser.add_argument('--cloudflared')
    connect_options(create_parser)
    for command in ('start', 'status', 'stop', 'board', 'invite', '_serve', 'revoke-invitation', 'revoke-member'):
        sub = commands.add_parser(command)
        sub.add_argument('--profile', required=True)
        if command == 'invite':
            sub.add_argument('--share', action='store_true')
            sub.add_argument('--message', choices=['en', 'zh'],
                             help='Also print a shareable invitation text in this language; it contains the one-time code')
            sub.add_argument('--hours', type=int, default=1, help='Invitation lifetime, 1-72 hours (default 1)')
        if command == 'revoke-invitation':
            sub.add_argument('--invitation-file', required=True)
        if command == 'revoke-member':
            sub.add_argument('--member-id', required=True)
    sub = commands.add_parser('join')
    source = sub.add_mutually_exclusive_group(required=True)
    source.add_argument('--invitation-file', help='A saved invitation message, or a private invitation file')
    source.add_argument('--invitation-code-stdin', action='store_true',
                        help='Read an invitation code, or a whole invitation message, from standard input')
    sub.add_argument('--name', required=True)
    sub.add_argument('--state-dir', help='New private folder (default: a new folder under ~/.coopagents/spaces)')
    connect_options(sub)
    sub = commands.add_parser('connect', help='Register this profile with Claude Code or Codex, install the skill and verify')
    sub.add_argument('--tool', required=True, choices=['claude', 'codex'])
    sub.add_argument('--profile', required=True)
    sub.add_argument('--name', help='MCP server name (default coopagents_<room>)')
    sub.add_argument('--cli', help='Full path of the claude or codex command when PATH has none or a broken one')
    sub.add_argument('--wake', action='store_true', help='Also install wake-up hooks for the repository folder')
    sub.add_argument('--project-dir', help='Repository folder for --wake (default: current folder)')
    sub = commands.add_parser('reconnect')
    sub.add_argument('--profile', required=True)
    sub.add_argument('--origin', required=True)
    sub.add_argument('--room-id', required=True)
    sub = commands.add_parser('doctor', help='Read-only setup and connection diagnostics')
    sub.add_argument('--name', help='Registered MCP server name when a custom name was used')
    sub.add_argument('--profile')
    sub.add_argument('--tool', choices=['claude', 'codex'])
    sub.add_argument('--cli', help='Full path of the native CLI to inspect')
    sub.add_argument('--project-dir', help='Repository folder for project-scoped checks')
    sub.add_argument('--json', action='store_true', dest='json_output', help='Print machine-readable JSON')
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    then_connect = None
    if command in ('create', 'join'):
        then_connect = (args.pop('connect'), args.pop('wake'), args.pop('project_dir'))
        if then_connect[1] and not then_connect[0]:
            parser.error('--wake requires --connect')
        if not args['state_dir']:
            args['state_dir'] = str(default_state_dir(args['name']))
    try:
        if command == '_serve':
            serve(args['profile'])
            return 0
        if command == 'doctor':
            json_output = args.pop('json_output')
            args['profile_path'] = args.pop('profile')
            result = doctor(**args)
            if json_output:
                print(json.dumps(result, ensure_ascii=True))
            else:
                from .onboarding_doctor import render_text
                print(render_text(result))
            return 0 if result.get('overall') == 'ready' else 1
        if command in ('revoke-invitation', 'revoke-member'):
            profile = read_profile(args['profile'])
            if command == 'revoke-invitation':
                descriptor = read_json(args['invitation_file'])
                data = {'invite_token': descriptor['invite_token']}
                operation = 'revoke_invite'
            else:
                data, operation = {'member_id': args['member_id']}, 'revoke_member'
            with member_link(profile):
                request(profile['origin'], '/api/operations/' + operation, token=web_credential(profile), data=data)
            result = safe_profile(profile, args['profile']) | {'status': 'revoked'}
        else:
            if command == 'connect':
                from .space_connect import connect, resolve_tool
                resolve_tool(args['tool'])
                connected = connect(args['tool'], args['profile'], name=args['name'], cli=args['cli'],
                                    wake=args['wake'], project_dir=args['project_dir'])
                print(json.dumps(connected))
                return 0
            if command == 'join' and args.pop('invitation_code_stdin'):
                from .invite_message import read_stdin
                args['invitation_code'] = read_stdin()
            if then_connect and then_connect[0]:
                from .space_connect import check_own_environment, resolve_tool
                resolve_tool(then_connect[0])
                check_own_environment()  # before anything is created, so a retry starts clean
            handler = {'create': create, 'start': start, 'status': status, 'stop': stop, 'board': board,
                       'invite': invite, 'join': join, 'reconnect': reconnect}[command]
            if 'profile' in args:
                args['profile_path'] = args.pop('profile')
            result = handler(**args)
            if then_connect and then_connect[0]:
                return connect_after(result, *then_connect)
        print(json.dumps(result))
        return 0
    except Exception as error:
        # Only this package's fixed messages and translated HTTP/network reasons are shown;
        # never remote bodies, headers, tracebacks or credentials.
        text = explain(error) or 'Space operation failed; check private state and runtime health'
        print(json.dumps({'error': type(error).__name__, 'message': text}), file=sys.stderr)
        return 1


def connect_options(parser):
    parser.add_argument('--connect', choices=['claude', 'codex'],
                        help='Then connect this agent: same as running connect --tool with the new profile')
    parser.add_argument('--wake', action='store_true', help='With --connect: also turn on wake-up for the repository')
    parser.add_argument('--project-dir', help='Repository folder for --wake (default: current folder)')


def connect_after(result, tool, wake, project_dir):
    """The space or membership exists either way; a failed connection says how to retry it alone."""
    from .space_connect import connect
    try:
        result['connect'] = connect(tool, result['profile'], wake=wake, project_dir=project_dir)
        connection = result['connect']
        result['configuration'] = connection.get('configuration', {
            'config': connection.get('config'), 'skill': connection.get('skill'),
            'verified': connection.get('verified', False)})
        result['verification'] = connection.get('verification') or doctor(
            result['profile'], tool, project_dir, None)
        result['next'] = connection.get('next', result['verification'].get('next', ''))
    except Exception as error:
        result['connect_error'] = explain(error) or 'Connecting failed'
        result['retry'] = '%s -m coopagents.space_runtime connect --tool %s --profile "%s"%s' % (
            sys.executable, tool, result['profile'], ' --wake' if wake else '')
        print(json.dumps(result))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
