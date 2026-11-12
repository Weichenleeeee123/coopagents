import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from coopagents.kimi_acp import AcpClient, AcpError, AcpTimeout
except ImportError:
    AcpClient = None

FAKE = str(Path(__file__).with_name('fake_acp_agent.py').resolve())


def argv():
    return [sys.executable, FAKE]


class KimiAcpTestCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(AcpClient, 'kimi_acp module is missing')
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.state = str(Path(self._directory.name) / 'state.jsonl')

    def records(self):
        path = Path(self.state)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def client(self, **kwargs):
        return AcpClient(argv(), **kwargs)

    def env(self, **extra):
        values = {'FAKE_ACP_STATE': self.state}
        values.update(extra)
        return patch.dict('os.environ', values)


class RoundTripTests(KimiAcpTestCase):
    def test_initialize_new_prompt_cancel_close(self):
        seen = []
        with self.env():
            with self.client(on_update=lambda method, params: seen.append((method, params))) as client:
                hello = client.initialize()
                self.assertEqual(hello['agentInfo']['name'], 'Kimi Code CLI')
                session = client.new_session(self._directory.name)
                self.assertEqual(session['sessionId'], 'sess-1')
                result = client.prompt('sess-1', 'hello')
                self.assertEqual(result['stopReason'], 'end_turn')
                self.assertEqual(client.cancel('sess-1'), {})
                self.assertEqual(client.close_session('sess-1'), {})
        self.assertEqual([method for method, _ in seen], ['session/update'])
        methods = [record['method'] for record in self.records()]
        self.assertEqual(methods, ['initialize', 'session/new', 'session/prompt',
                                   'session/cancel', 'session/close'])

    def test_mcp_servers_are_forwarded_to_new_session(self):
        servers = [{'name': 'coopagents', 'type': 'http', 'url': 'https://team.example/mcp'}]
        with self.env():
            with self.client() as client:
                client.initialize()
                client.new_session(self._directory.name, mcp_servers=servers)
        created = next(record for record in self.records() if record['method'] == 'session/new')
        self.assertEqual(created['params']['mcpServers'], servers)

    def test_new_session_always_sends_mcp_servers_even_when_none_given(self):
        # Regression: live kimi rejects session/new without the mcpServers
        # key (Invalid params); an omitted key is not the same as [].
        with self.env():
            with self.client() as client:
                client.initialize()
                client.new_session(self._directory.name)
        created = next(record for record in self.records() if record['method'] == 'session/new')
        self.assertEqual(created['params']['mcpServers'], [])

    def test_authenticate_passes_method_id_through(self):
        with self.env():
            with self.client() as client:
                self.assertEqual(client.authenticate(), {})
        auth = next(record for record in self.records() if record['method'] == 'authenticate')
        self.assertEqual(auth['params'], {'methodId': 'login'})

    def test_notify_sends_without_waiting_for_a_response(self):
        with self.env():
            with self.client() as client:
                client.notify('session/update', {'sessionId': 'sess-1'})
                client.initialize()
        methods = [record['method'] for record in self.records()]
        self.assertEqual(methods[0], 'session/update')
        self.assertEqual(methods[1], 'initialize')


class ReverseRpcTests(KimiAcpTestCase):
    def test_reverse_requests_are_refused_by_default(self):
        with self.env(FAKE_ACP_REVERSE='1'):
            with self.client() as client:
                client.new_session(self._directory.name)
        reply = next(record['reverse_reply'] for record in self.records() if 'reverse_reply' in record)
        self.assertEqual(reply['error']['code'], -32601)

    def test_registered_handler_answers_reverse_requests(self):
        def read_file(params):
            self.assertEqual(params, {'path': '/tmp/kimi-acp-probe.txt'})
            return {'content': 'hello'}
        with self.env(FAKE_ACP_REVERSE='1'):
            with self.client() as client:
                client.register_handler('fs/read_text_file', read_file)
                client.new_session(self._directory.name)
        reply = next(record['reverse_reply'] for record in self.records() if 'reverse_reply' in record)
        self.assertEqual(reply['result'], {'content': 'hello'})

    def test_failing_handler_reports_an_internal_error(self):
        def boom(params):
            raise RuntimeError('probe failure')
        with self.env(FAKE_ACP_REVERSE='1'):
            with self.client() as client:
                client.register_handler('fs/read_text_file', boom)
                client.new_session(self._directory.name)
        reply = next(record['reverse_reply'] for record in self.records() if 'reverse_reply' in record)
        self.assertEqual(reply['error']['code'], -32603)


class FailureTests(KimiAcpTestCase):
    def test_agent_error_surfaces_as_acp_error(self):
        with self.env():
            with self.client() as client:
                with self.assertRaises(AcpError) as caught:
                    client.request('session/fail')
        self.assertIn('Stub failure', str(caught.exception))

    def test_unknown_method_surfaces_the_agent_error(self):
        with self.env():
            with self.client() as client:
                with self.assertRaises(AcpError):
                    client.request('session/nope')

    def test_prompt_timeout_raises_and_client_closes_cleanly(self):
        with self.env(FAKE_ACP_SLEEP='3'):
            with self.client() as client:
                with self.assertRaises(AcpTimeout):
                    client.prompt('sess-1', 'hello', timeout=0.2)

    def test_agent_exit_fails_requests(self):
        with self.env(FAKE_ACP_EXIT='1'):
            with self.assertRaises(AcpError):
                with self.client() as client:
                    client.initialize(timeout=5)

    def test_garbage_line_fails_requests(self):
        with self.env(FAKE_ACP_GARBAGE='1'):
            with self.assertRaises(AcpError):
                with self.client() as client:
                    client.initialize(timeout=5)

    def test_missing_binary_reports_clearly(self):
        with self.assertRaises(AcpError) as caught:
            with AcpClient(['definitely-not-a-kimi-binary']) as client:
                client.initialize(timeout=5)
        self.assertIn('Could not start', str(caught.exception))

    def test_argument_validation(self):
        client = self.client()
        with self.assertRaises(ValueError):
            client.request('initialize', params=['not', 'an', 'object'])
        with self.assertRaises(ValueError):
            client.new_session('')
        with self.assertRaises(ValueError):
            client.prompt('', 'hi')
        with self.assertRaises(ValueError):
            client.register_handler('fs/read_text_file', 'not callable')
        with self.assertRaises(ValueError):
            AcpClient([])
        client.close()

    def test_close_is_idempotent_and_terminates_the_process(self):
        with self.env():
            client = self.client()
            client.start()
            process = client._process
            client.close()
            client.close()
        self.assertIsNotNone(process.poll())
        with self.assertRaises(AcpError):
            client.initialize(timeout=1)


if __name__ == '__main__':
    unittest.main()
