"""Offline local-password recovery; possession of the database is authority."""
import argparse
from contextlib import contextmanager
import getpass
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import warnings

from .accounts import AccountStore, _username
from .errors import ValidationError


class ExistingDatabase:
    """Open only an existing file, including if the file disappears after validation."""
    def __init__(self, path):
        self.uri = Path(path).resolve().as_uri() + '?mode=rw'

    @contextmanager
    def connect(self, write=False):
        c = sqlite3.connect(self.uri, uri=True, timeout=10, isolation_level=None)
        try:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            if write:
                c.execute('BEGIN IMMEDIATE')
            try:
                yield c
                if write:
                    c.commit()
            except BaseException:
                if write:
                    c.rollback()
                raise
        finally:
            c.close()


def recover_password(database, username, new_password):
    username = _username(username)
    db = ExistingDatabase(database)
    try:
        # Deliberately do not run schema creation/migrations during recovery.
        # Use the domain reset on the existing schema in one writer transaction.
        with db.connect(write=True) as c:
            row = c.execute('SELECT id,password_hash FROM accounts WHERE username=?', (username,)).fetchone()
            if row is None or row['password_hash'] is None:
                raise ValidationError('Existing local password account required')
            store = AccountStore.__new__(AccountStore)
            store.db = db
            store.identity = SimpleNamespace(db=db)
            store._reset_password(c, row['id'], new_password)
    except sqlite3.Error:
        raise ValidationError('Existing account database could not be opened or updated') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Existing Coopagents SQLite file')
    parser.add_argument('--username', required=True, help='Existing local username (not GitHub display name)')
    args = parser.parse_args(argv)
    try:
        # getpass otherwise falls back to echoed stdin on terminals it cannot
        # control. Abort before that fallback can read a plaintext password.
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('New password (12–256 characters): ')
            confirmation = getpass.getpass('Repeat new password: ')
        if password != confirmation:
            raise ValidationError('Password confirmation does not match')
        recover_password(args.database, args.username, password)
    except getpass.GetPassWarning:
        print('Recovery requires a terminal with hidden password input', file=sys.stderr)
        return 1
    except (ValidationError, OSError, EOFError, KeyboardInterrupt) as error:
        print(str(error) or 'Recovery cancelled', file=sys.stderr)
        return 1
    print('Password reset. All account sessions and their project web access are invalidated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
