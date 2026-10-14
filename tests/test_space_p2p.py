"""Peer-to-peer transport: real iroh endpoints on this computer, relay and discovery disabled."""
import asyncio
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from crewmesh import p2p
from crewmesh.space_runtime import available_port


def start_echo():
    """TCP echo on a loopback port; returns the port."""
    server = socket.create_server(('127.0.0.1', 0))
    port = server.getsockname()[1]

    def serve():
        while True:
            client, _ = server.accept()
            threading.Thread(target=echo, args=(client,), daemon=True).start()

    def echo(client):
        with client:
            while data := client.recv(65536):
                client.sendall(data)

    threading.Thread(target=serve, daemon=True).start()
    return port


def start_health(room_id):
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'status': 'ok', 'room_id': room_id}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def round_trip(port, payload):
    with socket.create_connection(('127.0.0.1', port), timeout=20) as sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        received = b''
        while chunk := sock.recv(65536):
            received += chunk
    return received


class Transport(unittest.TestCase):
    def link_pair(self, target_port, secret=None):
        host = p2p.HostLink(secret or p2p.new_secret(), target_port, local_only=True)
        self.addCleanup(host.close)
        member = p2p.MemberLink(host.endpoint_id, available_port(), addresses=host.addresses(), local_only=True)
        self.addCleanup(member.close)
        return host, member

    def test_streams_forward_bytes_both_ways(self):
        host, member = self.link_pair(start_echo())
        payload = bytes(range(256)) * 4096  # 1 MiB, every byte value
        self.assertEqual(round_trip(member.port, payload), payload)
        self.assertEqual(round_trip(member.port, b'second connection'), b'second connection')
        self.assertEqual(member.path()['state'], 'direct')

    def test_concurrent_connections_share_one_quic_connection(self):
        host, member = self.link_pair(start_echo())
        results = {}

        def worker(n):
            results[n] = round_trip(member.port, f'client {n}'.encode() * 1000)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(results, {n: f'client {n}'.encode() * 1000 for n in range(8)})
        self.assertEqual(len(host.connections), 1)

    def test_http_and_websocket_cross_the_link(self):
        async def serve_ws(ws):
            async for message in ws:
                await ws.send(message)

        ws_port = available_port()
        ready = threading.Event()

        def run_ws():
            from websockets.asyncio.server import serve

            async def main():
                async with serve(serve_ws, '127.0.0.1', ws_port):
                    ready.set()
                    await asyncio.Future()
            asyncio.run(main())

        threading.Thread(target=run_ws, daemon=True).start()
        ready.wait(10)
        host, member = self.link_pair(ws_port)

        async def client():
            from websockets.asyncio.client import connect
            async with connect(f'ws://127.0.0.1:{member.port}/') as ws:
                await ws.send('ping over iroh')
                return await ws.recv()
        self.assertEqual(asyncio.run(client()), 'ping over iroh')

        health = start_health('room-http')
        self.addCleanup(health.shutdown)
        http_host, http_member = self.link_pair(health.server_address[1])
        self.assertTrue(p2p._serves_space(f'http://127.0.0.1:{http_member.port}', 'room-http'))

    def test_persistent_secret_keeps_endpoint_id(self):
        secret = p2p.new_secret()
        self.assertEqual(p2p.endpoint_id(secret), p2p.endpoint_id(secret))
        host = p2p.HostLink(secret, start_echo(), local_only=True)
        self.addCleanup(host.close)
        self.assertEqual(host.endpoint_id, p2p.endpoint_id(secret))
        self.assertNotEqual(p2p.endpoint_id(p2p.new_secret()), host.endpoint_id)

    def test_member_reconnects_after_host_restart(self):
        target, secret = start_echo(), p2p.new_secret()
        host = p2p.HostLink(secret, target, local_only=True)
        member = p2p.MemberLink(host.endpoint_id, available_port(), addresses=host.addresses(), local_only=True)
        self.addCleanup(member.close)
        self.assertEqual(round_trip(member.port, b'before'), b'before')
        host.close()
        restarted = p2p.HostLink(secret, target, local_only=True)
        self.addCleanup(restarted.close)
        member.addresses = restarted.addresses()  # same identity; local test has no discovery
        self.assertEqual(round_trip(member.port, b'after restart'), b'after restart')

    def test_unreachable_target_resets_stream_but_link_survives(self):
        closed = available_port()
        host, member = self.link_pair(closed)
        self.assertEqual(round_trip(member.port, b'nobody listening'), b'')
        self.assertEqual(member.path()['state'], 'direct')

    def test_wrong_endpoint_key_is_never_reached(self):
        host = p2p.HostLink(p2p.new_secret(), start_echo(), local_only=True)
        self.addCleanup(host.close)
        stranger = p2p.endpoint_id(p2p.new_secret())
        member = p2p.MemberLink(stranger, available_port(), addresses=host.addresses(), local_only=True,
                                connect_timeout=3)
        self.addCleanup(member.close)
        try:
            received = round_trip(member.port, b'must not arrive')
        except ConnectionError:  # Windows may abort the refused socket instead of a clean EOF
            received = b''
        self.assertEqual(received, b'')
        self.assertEqual(host.connections, set())


class ProfileLinks(unittest.TestCase):
    def test_validation(self):
        good = 'a' * 64
        self.assertEqual(p2p.validate_link({'endpoint_id': good}), {'endpoint_id': good})
        for bad in ({}, {'endpoint_id': 'A' * 64}, {'endpoint_id': 'a' * 63}, {'endpoint_id': good, 'extra': 1},
                    {'endpoint_id': 64}, 'a' * 64):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                p2p.validate_link(bad)

    def test_profile_without_link_needs_nothing(self):
        with p2p.member_link({'origin': 'https://space.example.com', 'room_id': 'r'}) as link:
            self.assertIsNone(link)

    def test_busy_port_reused_only_for_the_same_space(self):
        health = start_health('room-1')
        self.addCleanup(health.shutdown)
        origin = f'http://127.0.0.1:{health.server_address[1]}'
        profile = {'origin': origin, 'room_id': 'room-1', 'p2p': {'endpoint_id': 'b' * 64}}
        with p2p.member_link(profile) as link:
            self.assertIsNone(link)  # the port already serves this space
        with self.assertRaises(ValueError):
            p2p.member_link(profile | {'room_id': 'another-room'})

    def test_missing_iroh_is_a_clear_error(self):
        with patch.dict('sys.modules', {'iroh': None}):
            with self.assertRaisesRegex(RuntimeError, 'space extra'):
                p2p._iroh()


if __name__ == '__main__':
    unittest.main()
