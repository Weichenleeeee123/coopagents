"""Owned cloudflared quick tunnel; readiness requires a registered connection."""
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from .spaces import checked_path


class QuickTunnel:
    def __init__(self, executable, local_origin, timeout=45):
        path = checked_path(executable)
        if not path.is_file():
            raise ValueError('Verified cloudflared executable is required')
        version = subprocess.run([str(path), '--version'], capture_output=True, text=True,
                                 timeout=10, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if version.returncode or 'cloudflared version' not in version.stdout:
            raise ValueError('cloudflared verification failed')
        self.process = subprocess.Popen([str(path), 'tunnel', '--url', local_origin,
                                         '--no-autoupdate', '--protocol', 'auto'],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.origin = None
        self.registered = False
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                ready = self.origin and self.registered
            if ready:
                return
            if self.process.poll() is not None:
                break
            time.sleep(.1)
        self.close()
        raise RuntimeError('Quick tunnel did not register within the startup deadline')

    def _read(self):
        for line in self.process.stdout:
            with self.lock:
                found = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
                if found:
                    self.origin = found.group(0)
                if 'Registered tunnel connection' in line:
                    self.registered = True

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.stdout:
            self.reader.join(timeout=2)
            self.process.stdout.close()
