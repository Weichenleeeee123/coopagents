"""Consistent SQLite copies; every destination is new and evidence is retained."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3


def _copy_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('Source and destination must differ')
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=30)) as original:
        if original.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise sqlite3.DatabaseError('Source integrity check failed')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL protects against races and symlinks; restrictive mode on Unix.
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(destination, timeout=30)) as copy:
            original.backup(copy, pages=256, sleep=.05)
            if copy.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise sqlite3.DatabaseError('Destination integrity check failed; file retained')
    return destination


def backup_database(source, destination):
    """Copy a live database using SQLite's online backup API."""
    return _copy_database(source, destination)


def restore_database(source, destination):
    """Validate a backup and restore to a new path; never replace a live file."""
    return _copy_database(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('backup', 'restore'))
    parser.add_argument('source')
    parser.add_argument('destination', help='New destination; existing files are refused')
    args = parser.parse_args()
    try:
        result = (backup_database if args.operation == 'backup' else restore_database)(args.source, args.destination)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, 'Copy failed. Check paths, permissions and database integrity; any partial destination is retained.\n')
    print('Validated database copy:', result)


if __name__ == '__main__':
    main()
