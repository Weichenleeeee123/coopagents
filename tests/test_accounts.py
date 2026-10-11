import unittest
from pathlib import Path
from uuid import uuid4
from crewmesh.identity import IdentityStore
from crewmesh.accounts import AccountStore
from crewmesh.errors import AccessDenied, ValidationError


class AccountTests(unittest.TestCase):
    def setUp(self):
        root = Path('.local/c1-tests'); root.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(root / (str(uuid4()) + '.sqlite'))
        self.accounts = AccountStore(self.identity)

    def test_bootstrap_login_csrf_logout(self):
        account = self.accounts.bootstrap(' Alice ', 'long password 123')
        session = self.accounts.login('ALICE', 'long password 123')
        self.assertEqual(account['id'], self.accounts.authenticate(session['session_token'], session['csrf_token'])['id'])
        with self.assertRaises(AccessDenied): self.accounts.authenticate(session['session_token'], 'wrong')
        with self.assertRaises(AccessDenied): self.accounts.bootstrap('bob', 'long password 456')
        self.accounts.logout(session['session_token'])
        with self.assertRaises(AccessDenied): self.accounts.authenticate(session['session_token'])

    def test_password_limits_change_and_expiry(self):
        with self.assertRaises(ValidationError): self.accounts.bootstrap('alice', 'short')
        self.accounts.bootstrap('alice', 'long password 123')
        session = self.accounts.login('alice', 'long password 123')
        with self.assertRaises(AccessDenied): self.accounts.change_password(session['session_token'], 'wrong', 'long password 456')
        self.accounts.change_password(session['session_token'], 'long password 123', 'long password 456')
        with self.assertRaises(AccessDenied): self.accounts.authenticate(session['session_token'])
        fresh = self.accounts.login('alice', 'long password 456')
        with self.accounts.db.connect(write=True) as c: c.execute("UPDATE account_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
        with self.assertRaises(AccessDenied): self.accounts.authenticate(fresh['session_token'])

    def test_oauth_identity_does_not_link_by_name(self):
        self.accounts.bootstrap('alice', 'long password 123')
        one = self.accounts.oauth_account('github', '123', 'alice')
        two = self.accounts.oauth_account('github', '123', 'changed')
        self.assertEqual(one['id'], two['id'])
        self.assertNotEqual(one['id'], self.accounts.login('alice', 'long password 123')['account']['id'])

    def test_storage_contains_salted_hashes_only_and_session_refresh(self):
        self.accounts.bootstrap('alice', 'long password 123')
        session = self.accounts.login('alice', 'long password 123')
        self.assertEqual(session['csrf_token'], self.accounts.session_info(session['session_token'])['csrf_token'])
        with self.accounts.db.connect() as c:
            account = dict(c.execute('SELECT * FROM accounts').fetchone())
            stored = dict(c.execute('SELECT * FROM account_sessions').fetchone())
        self.assertNotIn('long password 123', str(account))
        self.assertEqual(32, len(account['password_salt']))
        self.assertNotIn(session['session_token'], str(stored))
        self.assertNotEqual(session['csrf_token'], session['session_token'])

    def test_provider_validation_and_generic_bad_login(self):
        for provider, provider_id in [('github','abc'), ('other','123'), ('github','１２３')]:
            with self.assertRaises(ValidationError): self.accounts.oauth_account(provider, provider_id, 'name')
        with self.assertRaises(AccessDenied): self.accounts.login('missing', 'short')

    def test_invalid_unicode_username_is_rejected_without_echo(self):
        invalid = '\ud800'
        with self.assertRaises(ValidationError) as bootstrap_error:
            self.accounts.bootstrap(invalid, 'long password 123')
        self.assertNotIn(invalid, str(bootstrap_error.exception))
        with self.assertRaises(AccessDenied) as login_error:
            self.accounts.login(invalid, 'long password 123')
        self.assertEqual('Login not accepted', str(login_error.exception))
