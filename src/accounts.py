"""Local accounts and revocable browser sessions, independent of room tokens."""
import hashlib
import hmac
import secrets
import sqlite3
import unicodedata
from datetime import timedelta
from uuid import uuid4

from .errors import AccessDenied, ValidationError
from .identity import _name, _token_hash, _utcnow, _expired


def _username(value):
    if not isinstance(value, str):
        raise ValidationError('Username required')
    value = unicodedata.normalize('NFKC', value).strip().casefold()
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise ValidationError('Username must be valid Unicode') from None
    if not 1 <= len(value) <= 120 or any(ord(ch) < 32 for ch in value):
        raise ValidationError('Username must contain 1 to 120 characters')
    return value


def _password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 256:
        raise ValidationError('Password must contain 12 to 256 characters')
    try:
        return value.encode('utf-8')
    except UnicodeEncodeError:
        raise ValidationError('Password must be valid Unicode') from None


def _hash_password(password, salt):
    return hashlib.scrypt(_password(password), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


class AccountStore:
    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        with self.db.connect(write=True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY, username TEXT UNIQUE, display_name TEXT NOT NULL,
                password_salt TEXT, password_hash TEXT, created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS account_sessions (
                token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                expires_at TEXT NOT NULL, revoked_at TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS oauth_accounts (
                provider TEXT NOT NULL, provider_id TEXT NOT NULL,
                account_id TEXT NOT NULL REFERENCES accounts(id), PRIMARY KEY(provider,provider_id))''')

    def local_setup_available(self):
        with self.db.connect() as c:
            return c.execute('SELECT 1 FROM accounts LIMIT 1').fetchone() is None

    def _create_local(self, c, username, password, display_name=None):
        username = _username(username)
        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)
        account_id = str(uuid4())
        try:
            c.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?)',
                      (account_id, username, _name(display_name or username), salt, password_hash, _utcnow().isoformat()))
        except sqlite3.IntegrityError:
            raise ValidationError('Username unavailable') from None
        return self._get(c, account_id)

    def bootstrap(self, username, password, display_name=None):
        with self.db.connect(write=True) as c:
            if c.execute('SELECT 1 FROM accounts LIMIT 1').fetchone():
                raise AccessDenied('Initial account already exists')
            return self._create_local(c, username, password, display_name)

    bootstrap_account = bootstrap

    def _get(self, c, account_id):
        row = c.execute('SELECT id,username,display_name FROM accounts WHERE id=?', (account_id,)).fetchone()
        if row is None:
            raise AccessDenied('Account not accepted')
        return dict(row)

    def get_account(self, account_id):
        with self.db.connect() as c:
            return self._get(c, account_id)

    @staticmethod
    def csrf_token(session_token):
        _token_hash(session_token)
        return hashlib.sha256(('coopagents-csrf:' + session_token).encode()).hexdigest()

    def _create_session(self, c, account_id):
        account = self._get(c, account_id)
        token = secrets.token_urlsafe(32)
        expiry = (_utcnow() + timedelta(days=7)).isoformat()
        c.execute('INSERT INTO account_sessions VALUES(?,?,?,NULL)', (_token_hash(token), account_id, expiry))
        return {'session_token': token, 'csrf_token': self.csrf_token(token), 'expires_at': expiry, 'account': account}

    def create_session(self, account_id):
        """Trusted OAuth adapter hook; never expose arbitrary IDs as HTTP login."""
        with self.db.connect(write=True) as c:
            return self._create_session(c, account_id)

    def login(self, username, password):
        try:
            username = _username(username)
            _password(password)
        except ValidationError:
            raise AccessDenied('Login not accepted') from None
        with self.db.connect() as c:
            row = c.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
        # Password work stays outside the SQLite writer lock. Recheck the verified
        # hash inside the transaction so a concurrent reset cannot grant a session.
        salt = row['password_salt'] if row and row['password_salt'] else '00' * 16
        candidate = _hash_password(password, salt)
        if row is None or not row['password_hash'] or not hmac.compare_digest(candidate, row['password_hash']):
            raise AccessDenied('Login not accepted')
        with self.db.connect(write=True) as c:
            current = c.execute('SELECT password_hash FROM accounts WHERE id=?', (row['id'],)).fetchone()
            if current is None or current['password_hash'] != row['password_hash']:
                raise AccessDenied('Login not accepted')
            return self._create_session(c, row['id'])

    def resolve(self, c, session_token, csrf_token=None):
        row = c.execute('SELECT account_id,expires_at FROM account_sessions WHERE token_hash=? AND revoked_at IS NULL',
                        (_token_hash(session_token),)).fetchone()
        if row is None or _expired(row['expires_at'], _utcnow()):
            raise AccessDenied('Account session not accepted')
        if csrf_token is not None and (not isinstance(csrf_token, str) or not hmac.compare_digest(csrf_token, self.csrf_token(session_token))):
            raise AccessDenied('CSRF credential not accepted')
        return self._get(c, row['account_id'])

    def authenticate(self, session_token, csrf_token=None):
        with self.db.connect() as c:
            return self.resolve(c, session_token, csrf_token)

    def session_info(self, session_token):
        with self.db.connect() as c:
            account = self.resolve(c, session_token)
            row = c.execute('SELECT expires_at FROM account_sessions WHERE token_hash=?', (_token_hash(session_token),)).fetchone()
            return {'account': account, 'csrf_token': self.csrf_token(session_token), 'expires_at': row['expires_at']}

    def logout(self, session_token):
        with self.db.connect(write=True) as c:
            c.execute('UPDATE account_sessions SET revoked_at=? WHERE token_hash=?', (_utcnow().isoformat(), _token_hash(session_token)))

    def _reset_password(self, c, account_id, new_password):
        row = c.execute('SELECT password_hash FROM accounts WHERE id=?', (account_id,)).fetchone()
        if row is None or row['password_hash'] is None:
            raise ValidationError('Local password account required')
        salt = secrets.token_hex(16)
        c.execute('UPDATE accounts SET password_salt=?,password_hash=? WHERE id=?', (salt, _hash_password(new_password, salt), account_id))
        c.execute('UPDATE account_sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL', (_utcnow().isoformat(), account_id))

    def change_password(self, session_token, current_password, new_password):
        with self.db.connect(write=True) as c:
            account = self.resolve(c, session_token)
            row = c.execute('SELECT password_salt,password_hash FROM accounts WHERE id=?', (account['id'],)).fetchone()
            try:
                valid = row['password_hash'] and hmac.compare_digest(_hash_password(current_password, row['password_salt']), row['password_hash'])
            except ValidationError:
                valid = False
            if not valid:
                raise AccessDenied('Current password not accepted')
            self._reset_password(c, account['id'], new_password)

    def oauth_account(self, provider, provider_id, display_name):
        if provider != 'github' or not isinstance(provider_id, str) or not provider_id.isascii() or not provider_id.isdigit():
            raise ValidationError('GitHub numeric provider ID required')
        with self.db.connect(write=True) as c:
            row = c.execute('SELECT account_id FROM oauth_accounts WHERE provider=? AND provider_id=?', (provider, provider_id)).fetchone()
            if row:
                return self._get(c, row['account_id'])
            account_id = str(uuid4())
            c.execute('INSERT INTO accounts VALUES(?,NULL,?,NULL,NULL,?)', (account_id, _name(display_name), _utcnow().isoformat()))
            c.execute('INSERT INTO oauth_accounts VALUES(?,?,?)', (provider, provider_id, account_id))
            return self._get(c, account_id)
