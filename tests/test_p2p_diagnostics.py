"""Secret-free P2P observations, without a real relay or private state."""
import errno
import threading
import time
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from coopagents import p2p
from coopagents.space_server import create_control_app


class P2PDiagnosticsTests(unittest.TestCase):
    def host(self, reason='starting', age=0, relay=None):
        host = p2p.HostLink.__new__(p2p.HostLink)
        host.endpoint_id = 'a' * 64
        host.endpoint = Mock()
        host.endpoint.addr.return_value.relay_url.return_value = relay
        host.endpoint.addr.return_value.direct_addresses.return_value = []
        host._closed = host._online = False
        host._online_reason = reason
        host._started_at = time.monotonic() - age
        host.connections = set()
        return host

    def test_starting_and_missing_relay_are_observations_not_connectivity_claims(self):
        with patch.object(p2p, 'udp_send_denied', return_value=False):
            for age, reason in ((0, 'starting'), (31, 'relay_unavailable')):
                with self.subTest(age=age):
                    status = self.host(age=age).status()
                    self.assertFalse(status['online'])
                    self.assertEqual(status['reason'], reason)
                    self.assertTrue(status['summary'])
                    self.assertTrue(status['next'])

    def test_os_udp_denial_has_specific_recovery_and_no_sandbox_guess(self):
        with patch.object(p2p, 'udp_send_denied', return_value=True):
            status = self.host(age=60).status()
        self.assertEqual(status['reason'], 'udp_send_denied')
        self.assertIn('OS denied', status['summary'])
        self.assertIn('Allow unconnected UDP', status['next'])

    def test_local_mode_and_live_relay_do_not_run_udp_probe(self):
        with patch.object(p2p, 'udp_send_denied') as probe:
            local = self.host(reason='network_mode_local').status()
            online = self.host(relay='https://relay.example').status()
        probe.assert_not_called()
        self.assertEqual(local['reason'], 'network_mode_local')
        self.assertTrue(online['online'])
        self.assertNotIn('reason', online)

    def test_probe_distinguishes_permission_from_other_os_errors(self):
        for code, denied in ((errno.EPERM, True), (errno.EACCES, True), (errno.ENETUNREACH, False)):
            with self.subTest(code=code), patch.object(p2p.socket, 'socket') as socket:
                socket.return_value.__enter__.return_value.sendto.side_effect = OSError(code, 'private failure')
                self.assertEqual(p2p.udp_send_denied(), denied)

    def test_control_status_only_reports_local_mode_for_local_network(self):
        origin = 'http://127.0.0.1:8769'
        for network in ('local', 'quick', 'external'):
            with self.subTest(network=network):
                app = create_control_app(origin, 'synthetic-control', threading.Event(), 'room', network=network)
                with TestClient(app, base_url=origin, client=('127.0.0.1', 1234)) as client:
                    result = client.get('/status', headers={'Authorization': 'Bearer synthetic-control'}).json()
                if network == 'local':
                    self.assertEqual(result['p2p']['reason'], 'network_mode_local')
                else:
                    self.assertNotIn('p2p', result)

    def test_control_status_forwards_live_host_diagnostic(self):
        origin = 'http://127.0.0.1:8769'
        host = self.host(age=60)
        app = create_control_app(origin, 'synthetic-control', threading.Event(), 'room', p2p=host)
        with patch.object(p2p, 'udp_send_denied', return_value=True), \
                TestClient(app, base_url=origin, client=('127.0.0.1', 1234)) as client:
            result = client.get('/status', headers={'Authorization': 'Bearer synthetic-control'}).json()
        self.assertEqual(result['p2p']['reason'], 'udp_send_denied')


if __name__ == '__main__':
    unittest.main()
