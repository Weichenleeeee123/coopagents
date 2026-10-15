"""Real random-port loopback service with retained per-test databases."""
import json
from pathlib import Path
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import uvicorn
from coopagents.api import create_app


class LiveService:
    def __init__(self, database=None):
        self.database = Path(database) if database is not None else Path('.local/test-evidence') / (str(uuid4()) + '.sqlite3')
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.port = self.socket.getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}'
        self.app = create_app(self.database, base_url=self.url)
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='critical', access_log=False,
            ws_max_size=4096, ws_max_queue=4, ws_ping_interval=15, ws_ping_timeout=15))
        self.thread = threading.Thread(target=lambda: self.server.run(sockets=[self.socket]), daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Loopback service failed to start')
            time.sleep(.01)

    def close(self):
        self.server.should_exit = True
        self.thread.join(10)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError('Loopback service failed to stop')

    def request(self, method, path, token=None, data=None, headers=None, raw=None):
        headers = dict(headers or {})
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if data is not None:
            raw = json.dumps(data).encode()
            headers.setdefault('Content-Type', 'application/json')
        request = Request(self.url + path, data=raw, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            return response.status, json.loads(body) if body else None, response.headers

    def bootstrap(self):
        status, owner, _ = self.request('POST', '/api/rooms', data={'name': 'Team', 'owner_name': 'Owner'})
        assert status == 200
        status, invite, _ = self.request('POST', '/api/invites', owner['web_token'], {})
        assert status == 200
        status, member, _ = self.request('POST', '/api/join', data={'invite_token': invite['invite_token'], 'display_name': 'Member'})
        assert status == 200
        return owner, member
