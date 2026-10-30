"""Explicit, project-scoped file sharing with content-address verification."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
import stat
from uuid import uuid4

from .errors import AccessDenied, NotFound, ValidationError


SAFE_MEDIA_TYPES = frozenset({
    'application/json', 'application/octet-stream', 'application/pdf',
    'image/jpeg', 'image/png', 'image/webp', 'text/markdown', 'text/plain',
})
SAFE_SOURCE_TYPES = frozenset({'upload', 'path', 'commit', 'pull_request', 'release'})
MAX_FILENAME_BYTES = 255
MAX_SOURCE_REF = 500
DEFAULT_ASSET_LIMITS = {
    'max_file_bytes': 10 * 1024 * 1024,
    'max_project_bytes': 100 * 1024 * 1024,
    'max_total_bytes': 1024 * 1024 * 1024,
}
MAX_ASSET_FILE_BYTES = 10 * 1024 * 1024
ASSET_LIMIT_ENV = {
    'max_file_bytes': 'COOPAGENTS_ASSET_MAX_FILE_BYTES',
    'max_project_bytes': 'COOPAGENTS_ASSET_MAX_PROJECT_BYTES',
    'max_total_bytes': 'COOPAGENTS_ASSET_MAX_TOTAL_BYTES',
}


def asset_limits_from_env(environ=None):
    environ = os.environ if environ is None else environ
    limits = dict(DEFAULT_ASSET_LIMITS)
    for name, key in ASSET_LIMIT_ENV.items():
        raw = environ.get(key)
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw.isdecimal():
            raise ValueError('Asset storage limits must be positive integer byte counts')
        value = int(raw)
        maximum = MAX_ASSET_FILE_BYTES if name == 'max_file_bytes' else 1024 * 1024 * 1024 * 1024
        if not 1 <= value <= maximum:
            raise ValueError('Asset storage limits exceed the supported bound')
        limits[name] = value
    if limits['max_file_bytes'] > limits['max_project_bytes'] or limits['max_project_bytes'] > limits['max_total_bytes']:
        raise ValueError('Asset limits must satisfy file <= project <= total')
    return limits


def _bounded_positive(name, value):
    if type(value) is not int or value < 1:
        raise ValueError(name + ' must be a positive integer')
    return value


class AssetStore:
    def __init__(self, identity, data_root, *, max_file_bytes=10 * 1024 * 1024,
                 max_project_bytes=100 * 1024 * 1024, max_total_bytes=1024 * 1024 * 1024):
        self.identity = identity
        self.db = identity.db
        self.data_root = Path(data_root)
        self.max_file_bytes = _bounded_positive('max_file_bytes', max_file_bytes)
        self.max_project_bytes = _bounded_positive('max_project_bytes', max_project_bytes)
        self.max_total_bytes = _bounded_positive('max_total_bytes', max_total_bytes)
        if self.max_file_bytes > self.max_project_bytes or self.max_project_bytes > self.max_total_bytes:
            raise ValueError('Asset limits must satisfy file <= project <= total')
        self.data_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_root, 0o700)
        except OSError:
            pass

    @staticmethod
    def _validate(filename, media_type, content, source_type, source_ref):
        try:
            filename_size = len(filename.encode('utf-8')) if isinstance(filename, str) else MAX_FILENAME_BYTES + 1
        except UnicodeEncodeError:
            filename_size = MAX_FILENAME_BYTES + 1
        if (not isinstance(filename, str) or not filename or filename in ('.', '..')
                or '/' in filename or '\\' in filename or filename_size > MAX_FILENAME_BYTES
                or any(ord(char) < 32 or ord(char) == 127 for char in filename)):
            raise ValidationError('Invalid asset filename')
        if not isinstance(media_type, str) or media_type not in SAFE_MEDIA_TYPES:
            raise ValidationError('Unsupported asset media type')
        if not isinstance(content, bytes):
            raise ValidationError('Asset content must be bytes')
        if (not isinstance(source_type, str) or source_type not in SAFE_SOURCE_TYPES
                or not isinstance(source_ref, str) or len(source_ref) > MAX_SOURCE_REF):
            raise ValidationError('Invalid asset source reference')
        if source_type == 'upload' and source_ref:
            raise ValidationError('Uploaded assets cannot claim a repository source reference')
        if source_type != 'upload' and not source_ref.strip():
            raise ValidationError('Repository assets require an explicit source reference')
        if source_type == 'path' and (PurePosixPath(source_ref).is_absolute()
                or PureWindowsPath(source_ref).is_absolute() or PureWindowsPath(source_ref).drive or '\\' in source_ref
                or any(part in ('.', '..') for part in PurePosixPath(source_ref).parts)):
            raise ValidationError('Repository paths must be relative and remain inside the project')

    @staticmethod
    def _metadata(row):
        result = dict(row)
        result.pop('blob_key', None)
        return result

    def _stored_blob_bytes(self):
        total = 0
        for path in self.data_root.iterdir():
            if path.suffix != '.blob':
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValidationError('Asset storage contains a non-regular blob')
            total += info.st_size
        return total

    def upload(self, token, filename, media_type, content, *, source_type='upload', source_ref=''):
        self._validate(filename, media_type, content, source_type, source_ref)
        if len(content) > self.max_file_bytes:
            raise ValidationError('Asset exceeds the per-file limit')
        digest = hashlib.sha256(content).hexdigest()
        asset_id = str(uuid4())
        blob_key = uuid4().hex
        blob_path = self.data_root / (blob_key + '.blob')
        with self.db.connect(write=True) as connection:
            principal = self.identity.resolve(connection, token)
            used = connection.execute('SELECT COALESCE(SUM(size_bytes), 0) FROM project_assets WHERE room_id=?',
                                      (principal.room_id,)).fetchone()[0]
            if used + len(content) > self.max_project_bytes:
                raise ValidationError('Project asset storage limit exceeded')
            total = connection.execute('SELECT COALESCE(SUM(size_bytes), 0) FROM project_assets').fetchone()[0]
            total = max(total, self._stored_blob_bytes())
            if total + len(content) > self.max_total_bytes:
                raise ValidationError('Service asset storage limit exceeded')
            with blob_path.open('xb') as blob:
                blob.write(content)
                blob.flush()
            try:
                os.chmod(blob_path, 0o600)
            except OSError:
                pass
            created_at = datetime.now(timezone.utc).isoformat()
            connection.execute('''INSERT INTO project_assets
                (id, room_id, uploader_member_id, filename, media_type, size_bytes, sha256,
                 blob_key, source_type, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (asset_id, principal.room_id, principal.member_id, filename, media_type,
                 len(content), digest, blob_key, source_type, source_ref, created_at))
            row = connection.execute('SELECT * FROM project_assets WHERE id=?', (asset_id,)).fetchone()
            return self._metadata(row)

    def list_assets(self, token):
        with self.db.connect() as connection:
            principal = self.identity.resolve(connection, token)
            rows = connection.execute('''SELECT id, room_id, uploader_member_id, filename, media_type,
                    size_bytes, sha256, source_type, source_ref, created_at
                FROM project_assets WHERE room_id=? ORDER BY created_at DESC, id DESC''',
                (principal.room_id,)).fetchall()
            return [dict(row) for row in rows]

    def read_asset(self, token, asset_id):
        with self.db.connect() as connection:
            principal = self.identity.resolve(connection, token)
            row = connection.execute('SELECT * FROM project_assets WHERE id=? AND room_id=?',
                                     (asset_id, principal.room_id)).fetchone()
            if row is None:
                raise NotFound('Asset not found')
            blob_path = self.data_root / (row['blob_key'] + '.blob')
            try:
                content = blob_path.read_bytes()
            except OSError:
                raise NotFound('Asset content unavailable') from None
            if len(content) != row['size_bytes'] or hashlib.sha256(content).hexdigest() != row['sha256']:
                raise ValidationError('Asset content integrity check failed')
            return self._metadata(row), content
