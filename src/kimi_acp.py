"""Minimal Agent Client Protocol client for driving Kimi Code's ACP agent.

Kimi Code exposes an ACP agent over stdio through the ``kimi acp``
subcommand: newline-delimited JSON-RPC 2.0 with the namespaced method set
documented at https://moonshotai.github.io/kimi-code/en/reference/kimi-acp
(checked 2026-11-12; the page reports the full core 3/3 and session 11/11
agent-side surface, 10/11 client reverse-RPC methods, and the
``session/set_model`` extension). This module implements the client side:
it spawns the agent subprocess, correlates requests, collects agent
notifications, and answers the agent's reverse-RPC requests through
explicit handlers.

Authentication is the user's terminal login (``kimi login``); the client
never sees or stores credentials. Reverse-RPC requests are refused with
``methodNotFound`` by default — a handler that reads files or runs
terminals must be registered explicitly by the caller, who owns the trust
decision.

Live acceptance against a real ``kimi acp`` process needs a logged-in Kimi
session with a model backend and is unverified. The client is tested
against a stub ACP agent (tests/fake_acp_agent.py) over real stdio pipes.
"""
from collections import deque
import json
from importlib import metadata
import subprocess
import threading

KIMI_ACP_ARGV = ('kimi', 'acp')
DEFAULT_TIMEOUT = 30
PROMPT_TIMEOUT = 600
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
MAX_UPDATES = 200
MAX_STDERR_LINES = 50
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


class AcpError(Exception):
    """The ACP agent failed, exited, or violated the protocol."""


class AcpTimeout(AcpError):
    """No response arrived within the request timeout."""


def _text(value, name, limit=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('%s must be a nonempty string of at most %d characters' % (name, limit))
    return value


def _result_dict(result, method):
    if not isinstance(result, dict):
        raise AcpError('ACP agent returned a non-object result for %s' % method)
    return result


class AcpClient:
    """JSON-RPC client for one ACP agent subprocess. Requests are serialized."""

    def __init__(self, argv=None, *, timeout=DEFAULT_TIMEOUT, on_update=None, handlers=None):
        self.argv = [str(item) for item in (argv if argv is not None else KIMI_ACP_ARGV)]
        if not self.argv:
            raise ValueError('ACP argv must not be empty')
        self.timeout = timeout
        self._on_update = on_update
        self._handlers = dict(handlers or {})
        self.updates = deque(maxlen=MAX_UPDATES)
        self._stderr_lines = deque(maxlen=MAX_STDERR_LINES)
        self._state_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._pending = {}
        self._process = None
        self._reader = None
        self._stderr_reader = None
        self._broken = None
        self._closed = False

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
        return False

    def start(self):
        """Spawn the agent subprocess. Idempotent; request() also starts lazily."""
        with self._state_lock:
            if self._process is not None:
                return self
            if self._closed:
                raise AcpError('ACP client is closed')
            try:
                self._process = subprocess.Popen(self.argv, stdin=subprocess.PIPE,
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as error:
                raise AcpError('Could not start the ACP agent (%s): %s'
                               % (' '.join(self.argv), error.strerror or error)) from error
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            self._stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True)
            self._stderr_reader.start()
            return self

    def close(self):
        """Terminate the agent subprocess. Idempotent."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
        if process is not None:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for thread in (self._reader, self._stderr_reader):
                if thread is not None:
                    thread.join(timeout=2)
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        self._fail_all(AcpError('ACP client is closed'))

    @property
    def stderr_text(self):
        """The agent's recent stderr lines (logs go there, never to stdout)."""
        return '\n'.join(self._stderr_lines)

    def register_handler(self, method, handler):
        """Answer one agent reverse-RPC method. The handler receives params and
        must return a JSON-serializable result; it owns its trust decision."""
        method = _text(method, 'ACP method', 128)
        if not callable(handler):
            raise ValueError('ACP handler must be callable')
        self._handlers[method] = handler

    def request(self, method, params=None, timeout=None):
        """Send one request and return its result, or raise AcpError/AcpTimeout."""
        method = _text(method, 'ACP method', 128)
        if params is not None and not isinstance(params, dict):
            raise ValueError('ACP params must be an object')
        self.start()
        event, slot = threading.Event(), {}
        with self._state_lock:
            if self._broken is not None:
                raise self._broken
            self._next_id += 1
            request_id = self._next_id
            self._pending[request_id] = (event, slot)
        try:
            self._send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}})
        except AcpError:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        limit = self.timeout if timeout is None else timeout
        if not event.wait(limit):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise AcpTimeout('No response to %s within %s seconds' % (method, limit))
        if 'error' in slot:
            error = slot['error']
            raise AcpError('ACP agent error for %s: %s'
                           % (method, error.get('message') if isinstance(error, dict) else error))
        return slot.get('result')

    def notify(self, method, params=None):
        """Send a notification (no response is expected)."""
        method = _text(method, 'ACP method', 128)
        if params is not None and not isinstance(params, dict):
            raise ValueError('ACP params must be an object')
        self.start()
        with self._state_lock:
            if self._broken is not None:
                raise self._broken
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    def initialize(self, *, protocol_version=1, client_name='coopagents', capabilities=None, timeout=None):
        """ACP initialize. Returns the agent's result (agentInfo, capabilities, authMethods)."""
        try:
            client_version = metadata.version('coopagents')
        except metadata.PackageNotFoundError:
            client_version = 'unknown'
        return _result_dict(self.request('initialize', {
            'protocolVersion': protocol_version,
            'clientInfo': {'name': _text(client_name, 'client name', 128), 'version': client_version},
            'capabilities': capabilities or {},
        }, timeout), 'initialize')

    def authenticate(self, method_id='login', timeout=None):
        """ACP authenticate. Kimi validates method_id 'login' against the
        terminal login state; run `kimi login` first when it rejects."""
        return _result_dict(self.request(
            'authenticate', {'methodId': _text(method_id, 'auth method id', 128)}, timeout), 'authenticate')

    def new_session(self, cwd, *, mcp_servers=None, timeout=None):
        """Create a session. mcp_servers forwards MCP servers into the
        session (http/stdio/sse per the kimi acp reference); it is how a
        Coopagents MCP server reaches a Kimi session driven over ACP."""
        params = {'cwd': _text(cwd, 'working directory', 4096)}
        if mcp_servers is not None:
            if not isinstance(mcp_servers, list) or any(not isinstance(entry, dict) for entry in mcp_servers):
                raise ValueError('MCP servers must be a list of objects')
            params['mcpServers'] = mcp_servers
        return _result_dict(self.request('session/new', params, timeout), 'session/new')

    def prompt(self, session_id, text, *, timeout=PROMPT_TIMEOUT):
        """Send one prompt and wait for the turn to finish. The long default
        timeout covers a model turn; pass a shorter one for a liveness probe."""
        return _result_dict(self.request('session/prompt', {
            'sessionId': _text(session_id, 'session id'),
            'prompt': [{'type': 'text', 'text': _text(text, 'prompt', 100000)}],
        }, timeout), 'session/prompt')

    def cancel(self, session_id, timeout=None):
        return _result_dict(self.request(
            'session/cancel', {'sessionId': _text(session_id, 'session id')}, timeout), 'session/cancel')

    def close_session(self, session_id, timeout=None):
        return _result_dict(self.request(
            'session/close', {'sessionId': _text(session_id, 'session id')}, timeout), 'session/close')

    def _send(self, payload):
        try:
            data = (json.dumps(payload) + '\n').encode('utf-8')
        except (TypeError, ValueError) as error:
            raise AcpError('ACP payload is not JSON-serializable: %s' % error) from error
        with self._write_lock:
            try:
                self._process.stdin.write(data)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                self._fail_all(AcpError('ACP agent connection broke: %s' % error))
                raise AcpError('ACP agent connection broke') from error

    def _fail_all(self, error):
        with self._state_lock:
            if self._broken is None:
                self._broken = error
            pending = list(self._pending.values())
            self._pending.clear()
        for event, slot in pending:
            slot['error'] = {'code': -32000, 'message': str(error)}
            event.set()

    def _read_loop(self):
        stream = self._process.stdout
        while True:
            line = stream.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                self._fail_all(AcpError('ACP agent exited'))
                return
            if len(line) > MAX_MESSAGE_BYTES and not line.endswith(b'\n'):
                self._fail_all(AcpError('ACP agent message exceeds the size limit'))
                return
            try:
                message = json.loads(line)
            except ValueError:
                self._fail_all(AcpError('ACP agent sent invalid JSON'))
                return
            if not isinstance(message, dict):
                self._fail_all(AcpError('ACP agent sent a non-object message'))
                return
            self._dispatch(message)

    def _dispatch(self, message):
        if 'id' in message and ('result' in message or 'error' in message):
            with self._state_lock:
                entry = self._pending.pop(message['id'], None)
            if entry is not None:
                event, slot = entry
                if 'result' in message:
                    slot['result'] = message['result']
                else:
                    slot['error'] = message.get('error')
                event.set()
            return
        if 'method' in message and 'id' in message:
            handler = self._handlers.get(message['method'])
            if handler is None:
                reply = {'jsonrpc': '2.0', 'id': message['id'],
                         'error': {'code': METHOD_NOT_FOUND, 'message': 'Method not found'}}
            else:
                try:
                    result = handler(message.get('params') or {})
                except Exception:
                    reply = {'jsonrpc': '2.0', 'id': message['id'],
                             'error': {'code': INTERNAL_ERROR, 'message': 'Handler failed'}}
                else:
                    reply = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
            try:
                self._send(reply)
            except AcpError:
                pass  # The connection already failed; the reader exits on EOF.
            return
        if 'method' in message:
            params = message.get('params')
            self.updates.append((message['method'], params))
            if self._on_update is not None:
                try:
                    self._on_update(message['method'], params)
                except Exception:
                    pass  # A failing callback must never kill the reader.
            return
        self._fail_all(AcpError('ACP agent sent a message without a method or result'))

    def _drain_stderr(self):
        try:
            for line in self._process.stderr:
                self._stderr_lines.append(line.decode('utf-8', 'replace').rstrip('\n'))
        except (OSError, ValueError):
            pass
