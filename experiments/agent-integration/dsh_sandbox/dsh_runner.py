"""Opt-in native DeepSeek Harness headless process adapter."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import uuid4


MODEL_ALIAS = 'deepseekv41flash-auto-b'
PROVIDER_ALIAS = 'mota'
MCP_PLUGIN = '@deepseek-ai/dsh-mcp-client'
_ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _loopback_url(value: str, *, label: str, path_required: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError(f'{label} must be a loopback HTTP URL')
    parsed = urlsplit(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
        port = parsed.port
    except ValueError:
        raise ValueError(f'{label} must be a loopback HTTP URL') from None
    if (parsed.scheme != 'http' or not address.is_loopback or parsed.username or parsed.password
            or parsed.query or parsed.fragment or (port is not None and not 1 <= port <= 65535)
            or parsed.path.endswith('/') or (path_required and not parsed.path)):
        raise ValueError(f'{label} must be a loopback HTTP URL')
    return value


def _proxy_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError('Proxy base URL must be HTTPS or loopback HTTP')
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('Proxy base URL must be HTTPS or loopback HTTP') from None
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.endswith('/') or (port is not None and not 1 <= port <= 65535)):
        raise ValueError('Proxy base URL must be HTTPS or loopback HTTP')
    if parsed.scheme == 'https':
        return value
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        raise ValueError('Proxy base URL must be HTTPS or loopback HTTP') from None
    if parsed.scheme != 'http' or not address.is_loopback:
        raise ValueError('Proxy base URL must be HTTPS or loopback HTTP')
    return value


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        path.chmod(0o700)


def _secure_run_directory(path: Path) -> None:
    if os.name != 'nt':
        path.chmod(0o700)
        return
    try:
        identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                   capture_output=True, text=True, timeout=10, check=False)
        rows = list(csv.reader(line for line in identity.stdout.splitlines() if line.strip()))
        sid = rows[0][-1] if identity.returncode == 0 and rows and rows[0] else ''
        if not re.fullmatch(r'S-\d-(?:\d+-)*\d+', sid):
            raise OSError
        acl = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                              f'*{sid}:(OI)(CI)F'], capture_output=True,
                             text=True, timeout=10, check=False)
        if acl.returncode != 0:
            raise OSError
    except (OSError, subprocess.SubprocessError, IndexError, csv.Error):
        raise PermissionError('Unable to secure the private DSH run directory') from None


def _private_write(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
    if os.name != 'nt':
        path.chmod(0o600)


def build_patch(*, proxy_base_url: str, mcp_url: str, api_key_env: str,
                arm: str) -> list[dict]:
    """Return the JSON-compatible Cordis patch list (JSON is valid YAML)."""
    proxy_base_url = _proxy_url(proxy_base_url)
    if proxy_base_url.rstrip('/').endswith('/chat/completions'):
        raise ValueError('Proxy base URL must be an origin and prefix, not a completion endpoint')
    if arm not in ('control', 'coopagents'):
        raise ValueError('Arm must be control or coopagents')
    if not isinstance(api_key_env, str) or not _ENV_NAME.fullmatch(api_key_env):
        raise ValueError('API key environment variable name is invalid')

    rows = [
        {
            'id': 'llm-pi-ai',
            'config': {'providers': {PROVIDER_ALIAS: {
                'apiKeyEnv': api_key_env,
                'api': 'openai-completions',
                'baseURL': proxy_base_url,
                'compat': {'thinkingFormat': 'deepseek'},
                'models': [{'id': MODEL_ALIAS, 'contextWindow': 131072, 'maxTokens': 2048}],
            }}},
        },
        {'id': 'agent-default-model', 'config': {
            'provider': PROVIDER_ALIAS, 'model': MODEL_ALIAS,
        }},
    ]
    if arm == 'coopagents':
        mcp_url = _loopback_url(mcp_url, label='MCP URL', path_required=True)
        rows.append({'insert': [{'id': 'coopagents-mcp-client', 'name': MCP_PLUGIN,
                                 'config': {'serverName': 'coopagents',
                                            'transport': 'streamable-http', 'url': mcp_url}}]})
    return rows


def write_patch(path: str | Path, *, proxy_base_url: str, mcp_url: str,
                api_key_env: str, arm: str) -> Path:
    target = Path(path)
    _private_directory(target.parent)
    _private_write(target, (json.dumps(build_patch(proxy_base_url=proxy_base_url,
                                                    mcp_url=mcp_url, api_key_env=api_key_env,
                                                    arm=arm), ensure_ascii=True, indent=2) + '\n').encode('utf-8'))
    return target


def _events(stdout: bytes) -> tuple[list[dict], bool, str | None, list[str], int, float | None]:
    events = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            events.append(value)
    session_id = next((event.get('sessionId') for event in events
                       if event.get('type') == 'session' and isinstance(event.get('sessionId'), str)), None)
    turn_completed = any(event.get('type') == 'status'
                         and event.get('phase') == 'turn_end'
                         and event.get('reason') == 'completed' for event in events)
    final_seen = bool(events and events[-1].get('type') == 'final')
    tools = []
    tool_count = 0
    for event in events:
        name = event.get('tool') if event.get('type') == 'tool_call' else None
        if isinstance(name, str):
            tool_count += 1
            if name not in tools:
                tools.append(name)
    cost = None
    for event in events:
        value = event.get('cost_usd')
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            cost = float(value)
    return events, bool(session_id and turn_completed and final_seen), session_id, tools, tool_count, cost


class DshNativeRunner:
    def __init__(self, *, output_root: str | Path, proxy_base_url: str, mcp_url: str,
                 api_key_env: str, command: tuple[str, ...] | list[str] | None = None,
                 native_process: bool = True, execute_native: bool = False,
                 key_rotated: bool = False):
        self.output_root = Path(output_root).expanduser().resolve()
        self.proxy_base_url = _proxy_url(proxy_base_url)
        self.mcp_url = _loopback_url(mcp_url, label='MCP URL', path_required=True)
        if self.proxy_base_url.rstrip('/').endswith('/chat/completions'):
            raise ValueError('Proxy base URL must be an origin and prefix, not a completion endpoint')
        if not isinstance(api_key_env, str) or not _ENV_NAME.fullmatch(api_key_env):
            raise ValueError('API key environment variable name is invalid')
        self.api_key_env = api_key_env
        default_command = command is None
        if command is None:
            command = ('dsh.cmd' if os.name == 'nt' else 'dsh',)
        self.command = tuple(command)
        self.native_process = native_process and default_command
        self.execute_native = execute_native
        self.key_rotated = key_rotated
        self._run_roots: dict[tuple[str, str, str], Path] = {}

    def _check_version(self, env: dict[str, str]) -> bool:
        try:
            completed = subprocess.run([*self.command, '--version'], env=env,
                                       capture_output=True, timeout=15, check=False,
                                       text=True, shell=(os.name == 'nt' and self.command[0].lower().endswith(('.cmd', '.bat'))))
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 and bool(re.search(r'\b\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?\b',
                                                              completed.stdout + completed.stderr))

    async def run_turn(self, *, arm, role, prompt, session_id, fresh_session,
                       workspace, timeout_seconds, budget_remaining_usd):
        del budget_remaining_usd
        alias = f'{arm}-{role}'
        base = {
            'status': 'failed', 'source': 'harness_only', 'exit_code': None,
            'session_id': None, 'model_alias': MODEL_ALIAS, 'trace_ref': None,
            'trace_sha256': None, 'tool_names': [], 'tool_count': 0, 'cost_usd': None,
        }
        if arm not in ('control', 'coopagents') or role not in ('frontend', 'backend', 'integration'):
            return base
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            return base
        if self.native_process and not (self.execute_native and self.key_rotated):
            return base
        inherited = os.environ
        env = {name: inherited[name] for name in (
            'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
            'USERDOMAIN', 'USERNAME', 'LANG', 'LC_ALL', 'TERM', 'NO_COLOR', 'CI')
            if name in inherited}
        runtime_key = inherited.get(self.api_key_env)
        if not runtime_key:
            return base
        env[self.api_key_env] = runtime_key
        try:
            run_key = (arm, role, str(Path(workspace).resolve()))
            run_root = self._run_roots.get(run_key)
            if run_root is None:
                _private_directory(self.output_root)
                run_root = self.output_root / (uuid4().hex)
                run_root.mkdir(mode=0o700, exist_ok=False)
                _secure_run_directory(run_root)
                self._run_roots[run_key] = run_root
            home = run_root / 'home'
            profile = home / 'profiles' / 'headless'
            patch_file = run_root / 'cordis.patch.yml'
            workspace_path = Path(workspace).resolve()
            workspace_path.mkdir(parents=True, exist_ok=True)
            trace_path = run_root / ('trace-' + uuid4().hex + '.jsonl')
            stderr_path = run_root / ('stderr-' + uuid4().hex + '.log')
            write_patch(patch_file, proxy_base_url=self.proxy_base_url, mcp_url=self.mcp_url,
                        api_key_env=self.api_key_env, arm=arm)
            _private_directory(home)
            _private_directory(profile.parent)
            _private_directory(home / 'AppData' / 'Roaming')
            _private_directory(home / 'AppData' / 'Local')
            env['DSH_HOME'] = str(home)
            env['HOME'] = str(home)
            env['USERPROFILE'] = str(home)
            env['APPDATA'] = str(home / 'AppData' / 'Roaming')
            env['LOCALAPPDATA'] = str(home / 'AppData' / 'Local')
            if not self._check_version(env):
                return base
            argv = [*self.command, '--profile', 'headless']
            if not profile.exists():
                argv.extend(['--from-default-profile', 'headless'])
            argv.extend(['--json', '--patch', str(patch_file)])
            if session_id and not fresh_session:
                argv.extend(['--session-id', str(session_id)])
            argv.append('-')
            shell = os.name == 'nt' and self.command[0].lower().endswith(('.cmd', '.bat'))
            try:
                completed = await asyncio.to_thread(
                    subprocess.run, argv, cwd=workspace_path, env=env,
                    input=prompt.encode('utf-8'), capture_output=True,
                    timeout=timeout_seconds, check=False, shell=shell)
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or b''
                stderr = exc.stderr or b''
                if isinstance(stdout, str):
                    stdout = stdout.encode('utf-8', errors='replace')
                if isinstance(stderr, str):
                    stderr = stderr.encode('utf-8', errors='replace')
                _private_write(trace_path, stdout)
                _private_write(stderr_path, stderr)
                return base | {'status': 'timeout', 'trace_ref': str(trace_path),
                               'trace_sha256': hashlib.sha256(stdout).hexdigest()}
            _private_write(trace_path, completed.stdout)
            _private_write(stderr_path, completed.stderr)
            digest = hashlib.sha256(completed.stdout).hexdigest()
            events, completed_turn, native_session, tools, tool_count, cost = _events(completed.stdout)
            okay = completed.returncode == 0 and completed_turn
            return base | {
                'status': 'completed' if okay else 'failed',
                'source': 'native' if okay and self.native_process else 'harness_only',
                'exit_code': completed.returncode,
                'session_id': native_session if okay else None,
                'trace_ref': str(trace_path), 'trace_sha256': digest,
                'tool_names': tools, 'tool_count': tool_count, 'cost_usd': cost,
            }
        except (OSError, ValueError, TypeError):
            return base


def _default_output_root() -> Path:
    configured = os.environ.get('DSH_NATIVE_OUTPUT_ROOT')
    if configured:
        return Path(configured)
    return Path('.local') / 'dsh-native-runs'


def _command_override(environ):
    raw = environ.get('DSH_NATIVE_COMMAND')
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError('DSH_NATIVE_COMMAND must be a nonempty string list')
    return tuple(value)


def _contained_path(value, root: Path, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError('Required path is missing')
    candidate = Path(value).expanduser().resolve(strict=must_exist)
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError('Path is outside the private role root') from None
    return candidate


def _run_config(config_path: str | Path, *, environ=None) -> dict:
    env = os.environ if environ is None else environ
    runs_root = Path(env.get('DSH_NATIVE_RUNS_ROOT', '/var/lib/dsh-sandbox/runs')).resolve()
    config_file = _contained_path(str(config_path), runs_root, must_exist=True)
    if config_file.name != 'config.json' or len(config_file.relative_to(runs_root).parts) != 4:
        raise ValueError('Config must be runs/<run>/<arm>/<role>/config.json')
    run_name, arm_name, role_name, _ = config_file.relative_to(runs_root).parts
    if (not run_name or run_name in ('.', '..') or arm_name not in ('control', 'coopagents')
            or role_name not in ('frontend', 'backend', 'integration')):
        raise ValueError('Config path has an invalid run, arm, or role')
    role_root = config_file.parent
    config = json.loads(config_file.read_text(encoding='utf-8'))
    if (not isinstance(config, dict) or config.get('schema_version') != 1
            or config.get('run_id') != run_name or config.get('arm') != arm_name
            or config.get('role') != role_name):
        raise ValueError('Config metadata does not match its private path')
    if config.get('execute_native') is not True or config.get('key_rotated') is not True:
        raise ValueError('Config must attest execute_native and key_rotated')
    prompt_file = _contained_path(config.get('prompt_path'), role_root, must_exist=True)
    workspace = _contained_path(config.get('workspace'), role_root, must_exist=True)
    if not prompt_file.is_file() or not workspace.is_dir():
        raise ValueError('Prompt and workspace paths have invalid types')
    prompt = prompt_file.read_text(encoding='utf-8')
    timeout = config.get('timeout_seconds')
    budget = config.get('budget_remaining_usd')
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
            or isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget < 0):
        raise ValueError('Config timeout or budget is invalid')
    session_id = config.get('session_id')
    if session_id is not None and (not isinstance(session_id, str) or not session_id):
        raise ValueError('Config session id is invalid')
    fresh_session = config.get('fresh_session', False)
    if type(fresh_session) is not bool:
        raise ValueError('Config fresh_session value is invalid')
    runner = DshNativeRunner(
        output_root=role_root, proxy_base_url=env['DSH_NATIVE_PROXY_BASE_URL'],
        mcp_url=env['DSH_NATIVE_MCP_URL'],
        api_key_env=env.get('DSH_NATIVE_API_KEY_ENV', 'LLM_API_KEY'),
        command=_command_override(env), execute_native=True, key_rotated=True)
    return asyncio.run(runner.run_turn(
        arm=arm_name, role=role_name, prompt=prompt, session_id=session_id,
        fresh_session=fresh_session, workspace=workspace, timeout_seconds=timeout,
        budget_remaining_usd=budget))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Opt-in native DeepSeek Harness runner')
    sub = parser.add_subparsers(dest='command', required=True)
    config_run = sub.add_parser('run-config')
    config_run.add_argument('--config', required=True)
    run = sub.add_parser('run')
    run.add_argument('--prompt', required=True)
    run.add_argument('--arm', choices=('control', 'coopagents'), default='control')
    run.add_argument('--role', choices=('frontend', 'backend', 'integration'), default='integration')
    run.add_argument('--workspace', default=os.getcwd())
    run.add_argument('--session-id')
    run.add_argument('--fresh-session', action='store_true')
    run.add_argument('--execute-native', action='store_true')
    run.add_argument('--key-rotated', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'run-config':
        try:
            result = _run_config(args.config)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            print(json.dumps({'status': 'configuration_error'}))
            return 2
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result['status'] == 'completed' else 1
    if not args.execute_native or not args.key_rotated:
        parser.error('Live DSH execution requires --execute-native and --key-rotated')
    try:
        command = _command_override(os.environ)
        runner = DshNativeRunner(
            output_root=_default_output_root(),
            proxy_base_url=os.environ['DSH_NATIVE_PROXY_BASE_URL'],
            mcp_url=os.environ['DSH_NATIVE_MCP_URL'],
            api_key_env=os.environ.get('DSH_NATIVE_API_KEY_ENV', 'LLM_API_KEY'),
            command=command, execute_native=args.execute_native,
            key_rotated=args.key_rotated)
        result = asyncio.run(runner.run_turn(
            arm=args.arm, role=args.role, prompt=args.prompt, session_id=args.session_id,
            fresh_session=args.fresh_session, workspace=args.workspace,
            timeout_seconds=120, budget_remaining_usd=1.0))
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        print(json.dumps({'status': 'configuration_error'}))
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
