"""Isolated native process plumbing; no scenario runner or evidence scoring.

Only prepare_native and run_turn are public entry points. Returned environments
and raw events are private data: callers must not print or publish them. CLI
commands contain private configuration paths, never MCP bearer credentials.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit

import cold_start_acceptance as cold
from coopagents.spaces import checked_path, private_directory, private_write, protect


SERVER = 'coopagents_workflow'
_WINDOWS = os.name == 'nt'


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and not any(c in value for c in '\r\n\0')


def _exclusive_directory(value):
    path = checked_path(value)
    if path.exists():
        raise FileExistsError('Private run directory already exists')
    private_directory(path.parent)
    path.mkdir(exist_ok=False)
    protect(path, directory=True)
    return path


def prepare_native(run: Path, harness: str, executable: str, server_url: str, token: str,
                   enabled_tools: list[str], codex_source: Path | None = None,
                   claude_settings: Path | None = None) -> dict:
    """Create one fresh private participant home, preserving selected auth/model.

    The caller supplies a service whose advertised tools match this arm. Claude
    allow rules additionally deny unapproved calls; they do not filter tools/list.
    No executable is launched here, and no personal native settings are edited.
    """
    if harness not in ('codex', 'claude') or not _text(executable) or not _text(token):
        raise ValueError('Invalid native harness, executable or credential')
    if (not isinstance(enabled_tools, list)
            or any(not isinstance(t, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', t)
                   for t in enabled_tools)
            or len(set(enabled_tools)) != len(enabled_tools)):
        raise ValueError('Enabled tools must be a unique list of operation names')
    if not _text(server_url):
        raise ValueError('Invalid HTTP MCP endpoint')
    parsed = urlsplit(server_url)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('Invalid HTTP MCP endpoint') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or '\\' in server_url or any(c.isspace() for c in server_url)
            or (parsed.scheme == 'http' and (parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or not port))):
        raise ValueError('Use HTTPS or an explicit loopback HTTP MCP endpoint')
    original_home = Path.home()
    codex_source = Path(codex_source) if codex_source is not None else Path(
        os.environ.get('CODEX_HOME') or original_home / '.codex')
    claude_settings = Path(claude_settings) if claude_settings is not None else Path(
        os.environ.get('CLAUDE_CONFIG_DIR') or original_home / '.claude') / 'settings.json'
    run = _exclusive_directory(run)
    # Reuse the existing auth/provider allowlist; do not forward the parent env.
    env = cold.prepare_homes(run, codex_source, claude_settings, tool=harness)
    if harness == 'codex':
        config = run / 'codex-home' / 'config.toml'
        server = dict(url=server_url, http_headers={'Authorization': 'Bearer ' + token},
                      enabled_tools=list(enabled_tools))
        # prepare_homes just created this protected file. Append our only server
        # without replacing the selected provider/model or any pre-existing run.
        with config.open('a', encoding='utf-8') as stream:
            stream.write('sandbox_mode = "workspace-write"\n')
            if _WINDOWS:
                # Without an active Windows sandbox, Codex downgrades a legacy
                # workspace-write mode to read-only. Use the normal restricted
                # token backend only in this new private participant profile.
                stream.write('windows = {sandbox = "unelevated"}\n')
            stream.write('mcp_servers = ' + cold.toml_value({SERVER: server}) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    else:
        config = run / 'workflow-mcp.json'
        private_write(config, {'mcpServers': {SERVER: {'type': 'http', 'url': server_url,
                       'headers': {'Authorization': 'Bearer ' + token}}}})
    return {'harness': harness, 'executable': executable, 'run_dir': str(run),
            'env': dict(env), 'enabled_tools': list(enabled_tools), 'mcp_config': str(config)}


def _command(participant, project, resume):
    harness, executable = participant['harness'], participant['executable']
    if harness == 'codex':
        overrides = []
        for tool in participant['enabled_tools']:
            overrides += ['-c', 'mcp_servers.' + SERVER + '.tools.' + tool + '.approval_mode="approve"']
        if resume is None:
            # exec owns these flags; the top-level sandbox option does not
            # propagate into a new exec turn on the installed native CLI.
            return [executable, '--no-daemon', 'exec', '--sandbox', 'workspace-write',
                    '-C', str(project), *overrides, '--json', '-']
        # exec resume accepts config overrides, not exec's --sandbox / -C.
        # Popen's cwd supplies the project; root verifies the resumed native
        # turn_context against this explicit normal-sandbox override.
        return [executable, '--no-daemon', '-c', 'sandbox_mode="workspace-write"',
                *overrides, 'exec', 'resume', resume, '--json', '-']
    allowed = ['Read(./**)', 'Edit(./**)', 'Write(./**)']
    allowed += ['mcp__' + SERVER + '__' + tool for tool in participant['enabled_tools']]
    command = [executable, '--print', '--verbose', '--output-format', 'stream-json',
               '--restricted', '--strict-mcp-config', '--mcp-config', participant['mcp_config'],
               '--settings', str(Path(participant['env']['CLAUDE_CONFIG_DIR']) / 'settings.json'),
               '--tools', 'Read,Edit,Write', '--allowedTools', ','.join(allowed),
               '--permission-prompts', 'none']
    return command + (['--resume', resume] if resume is not None else [])


class _WindowsJob:
    """Own only this launch and descendants; closing kills remaining helpers."""
    def __init__(self, process):
        import ctypes
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', w.DWORD), ('min_working_set', ctypes.c_size_t), ('max_working_set', ctypes.c_size_t),
                ('active_processes', w.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', w.DWORD), ('scheduling', w.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', Counters), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t),
                ('peak_job_memory', ctypes.c_size_t)]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = [w.HANDLE, w.HANDLE], w.BOOL
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                or not kernel.AssignProcessToJobObject(handle, int(process._handle))):
            error = ctypes.get_last_error()
            kernel.CloseHandle(handle)
            raise ctypes.WinError(error)
        self.kernel, self.handle = kernel, handle

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _stop_tree(process, job):
    if job is not None:
        job.close()
    elif os.name != 'nt':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        # Used only if attaching our private job failed before capture starts.
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if process.poll() is None:
        process.wait(timeout=15)


def _capture(command, env, project, turn_dir, prompt_path, timeout, cancel_event=None):
    paths = {name: turn_dir / filename for name, filename in
             (('events', 'events.jsonl'), ('raw', 'stdout.log'), ('stderr', 'stderr.log'))}
    events, errors = [], []
    process = job = reader = None
    timed_out, cancelled, exit_code = False, False, None
    with ExitStack() as stack:
        streams = {}
        for name, path in paths.items():
            streams[name] = stack.enter_context(path.open('xb'))
            protect(path)
        stdin = stack.enter_context(prompt_path.open('rb'))
        started_at = time.time()
        try:
            process = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=streams['stderr'],
                env=env, cwd=project, start_new_session=os.name != 'nt',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if os.name == 'nt':
                job = _WindowsJob(process)

            def consume():
                try:
                    for line in iter(process.stdout.readline, b''):
                        streams['raw'].write(line)
                        streams['raw'].flush()
                        try:
                            event = json.loads(line.decode('utf-8'), parse_constant=lambda value:
                                (_ for _ in ()).throw(ValueError('Non-JSON numeric constant')))
                        except (ValueError, UnicodeError):
                            continue
                        wrapped = {'at': time.time(), 'event': event}
                        streams['events'].write((json.dumps(wrapped, ensure_ascii=True) + '\n').encode('utf-8'))
                        streams['events'].flush()
                        events.append(wrapped)
                except Exception as error:
                    errors.append(type(error).__name__)

            reader = threading.Thread(target=consume, name='workflow-native-events', daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    try:
                        exit_code = process.wait(timeout=min(.2, remaining))
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                # Also stop inherited-pipe helpers after a normally exited CLI.
                _stop_tree(process, job)
                exit_code = process.returncode
                reader.join(timeout=5)
            if reader.is_alive():
                errors.append('EventReaderTimeout')
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            if process is not None:
                _stop_tree(process, job)
                if reader is not None:
                    reader.join(timeout=5)
                if reader is None or not reader.is_alive():
                    process.stdout.close()
            if errors:
                exit_code = None
                streams['stderr'].write(('Native process capture failed: ' + ','.join(errors) + '\n').encode())
            streams['stderr'].flush()
            finished_at = time.time()
    return {'exit_code': exit_code, 'timed_out': timed_out, 'cancelled': cancelled, 'events': events,
            'started_at': started_at, 'finished_at': finished_at,
            'event_path': str(paths['events']), 'stderr_path': str(paths['stderr'])}


def run_turn(participant: dict, prompt: str, project: Path, turn_dir: Path, timeout: int = 180,
             resume: str | None = None, cancel_event: threading.Event | None = None) -> dict:
    """Run one real CLI turn; retain all private evidence, including failures.

    Session IDs are supplied by an external native-trace parser. This adapter
    never interprets a final assistant response as a delivered reply or success.
    Intentional cancellation is separate from timeout and cannot count as a
    normally completed native turn; all evidence remains in the private turn.
    """
    if (not isinstance(participant, dict) or participant.get('harness') not in ('codex', 'claude')
            or not _text(participant.get('executable')) or not isinstance(participant.get('env'), dict)
            or not isinstance(prompt, str) or type(timeout) is not int or timeout <= 0
            or (cancel_event is not None and not isinstance(cancel_event, threading.Event))
            or (resume is not None and (not _text(resume) or resume.startswith('-')))):
        raise ValueError('Invalid native turn arguments')
    project = checked_path(project)
    if not project.is_dir():
        raise ValueError('Native project directory is absent')
    command = _command(participant, project, resume)
    prompt_bytes = prompt.encode('utf-8')
    turn_dir = _exclusive_directory(turn_dir)
    prompt_path = turn_dir / 'prompt.txt'
    with prompt_path.open('xb') as stream:
        protect(prompt_path)
        stream.write(prompt_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    return _capture(command, dict(participant['env']), project, turn_dir, prompt_path, timeout, cancel_event)
