"""Retained evidence for recovery through local filesystem authority."""
import contextlib
import io
import getpass
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.accounts import AccountStore
from coopagents.identity import IdentityStore
from coopagents.workspaces import WorkspaceStore
from coopagents.errors import AccessDenied, ValidationError


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/c1-recovery') / uuid4().hex
        self.root.mkdir(parents=True)
        self.path = self.root / 'existing.sqlite3'
        self.identity = IdentityStore(self.path)
        self.accounts = AccountStore(self.identity)
        self.accounts.bootstrap('owner', 'original password 123')
        self.session = self.accounts.login('owner', 'original password 123')['session_token']
        self.workspaces = WorkspaceStore(self.accounts)
        team = self.workspaces.create_team(self.session, 'recovery')['team_id']
        project = self.workspaces.create_project(self.session, team, 'project')['room_id']
        self.web = self.workspaces.project_credential(self.session, project)['web_token']

    def test_normalized_reset_revokes_session_and_issued_web(self):
        from coopagents.account_recovery import recover_password
        recover_password(self.path, ' ＯＷＮＥＲ ', 'replacement password 456')
        for action in (lambda: self.accounts.authenticate(self.session),
                       lambda: self.identity.authenticate(self.web),
                       lambda: self.accounts.login('owner', 'original password 123')):
            with self.assertRaises(AccessDenied): action()
        self.accounts.login('owner', 'replacement password 456')

    def test_missing_file_not_created_and_unknown_or_oauth_rejected(self):
        from coopagents.account_recovery import recover_password
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(ValidationError): recover_password(missing, 'owner', 'replacement password 456')
        self.assertFalse(missing.exists())
        for name in ('unknown', 'github-name'):
            self.accounts.oauth_account('github', '123', 'github-name')
            with self.assertRaises(ValidationError): recover_password(self.path, name, 'replacement password 456')
        self.accounts.authenticate(self.session)

    def test_invalid_password_rolls_back_and_prompt_does_not_echo_secret(self):
        from coopagents.account_recovery import main, recover_password
        with self.assertRaises(ValidationError): recover_password(self.path, 'owner', 'short')
        self.accounts.authenticate(self.session)
        secret = 'replacement password 456'
        output = io.StringIO()
        with patch('coopagents.account_recovery.getpass.getpass', side_effect=[secret, secret]) as prompt, contextlib.redirect_stdout(output):
            self.assertEqual(0, main(['--database', str(self.path), '--username', 'owner']))
        self.assertEqual(2, prompt.call_count)
        self.assertNotIn(secret, output.getvalue())

    def test_mismatched_confirmation_does_not_reset(self):
        from coopagents.account_recovery import main
        with patch('coopagents.account_recovery.getpass.getpass', side_effect=['replacement password 456', 'different password 789']), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, main(['--database', str(self.path), '--username', 'owner']))
        self.accounts.authenticate(self.session)

    def test_terminal_without_hidden_input_aborts(self):
        from coopagents.account_recovery import main
        with patch('coopagents.account_recovery.getpass.getpass', side_effect=getpass.GetPassWarning('cannot hide')), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, main(['--database', str(self.path), '--username', 'owner']))
        self.accounts.authenticate(self.session)
