"""Consistent SQLite copies; every destination is new and evidence is retained."""
import argparse
from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import shutil
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


def _copy_project_data(source_database, source_assets, destination_database, destination_assets):
    source_database = Path(source_database).resolve()
    source_assets = Path(source_assets)
    if source_assets.is_symlink():
        raise ValueError('Asset source must not be a symbolic link')
    source_assets = source_assets.resolve()
    destination_database = Path(destination_database).resolve()
    destination_assets = Path(destination_assets)
    if destination_assets.is_symlink():
        raise ValueError('Asset destination must not be a symbolic link')
    destination_assets = destination_assets.resolve()
    if source_database == destination_database or source_assets == destination_assets:
        raise ValueError('Source and destination must differ')
    if destination_database.exists() or destination_assets.exists():
        raise FileExistsError('Database and asset destinations must both be new')
    if not source_assets.is_dir() or source_assets.is_symlink():
        raise FileNotFoundError(source_assets)
    backup_database(source_database, destination_database)
    with closing(sqlite3.connect(destination_database.as_uri() + '?mode=ro', uri=True, timeout=30)) as database:
        if database.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise sqlite3.DatabaseError('Source integrity check failed')
        try:
            assets = database.execute('SELECT blob_key, size_bytes, sha256 FROM project_assets').fetchall()
        except sqlite3.Error as error:
            raise sqlite3.DatabaseError('Source database has no asset manifest') from error
    verified = []
    for key, size, digest in assets:
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key):
            raise sqlite3.DatabaseError('Invalid asset storage key')
        path = source_assets / (key + '.blob')
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
        with path.open('rb') as stream:
            content_hash = hashlib.sha256()
            byte_count = 0
            while chunk := stream.read(1024 * 1024):
                byte_count += len(chunk)
                content_hash.update(chunk)
        if byte_count != size or content_hash.hexdigest() != digest:
            raise sqlite3.DatabaseError('Asset integrity check failed')
        verified.append((path, key + '.blob'))
    destination_assets.mkdir(parents=True, exist_ok=False)
    try:
        os.chmod(destination_assets, 0o700)
    except OSError:
        pass
    for source, name in verified:
        target = destination_assets / name
        with source.open('rb') as original, target.open('xb') as copy:
            shutil.copyfileobj(original, copy, 1024 * 1024)
            copy.flush()
            os.fsync(copy.fileno())
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    return destination_database, destination_assets


def backup_project_data(source_database, source_assets, destination_database, destination_assets):
    """Create a digest-verified database and asset copy at new destinations."""
    return _copy_project_data(source_database, source_assets, destination_database, destination_assets)


def restore_project_data(source_database, source_assets, destination_database, destination_assets):
    """Restore a digest-verified project backup without replacing existing data."""
    return _copy_project_data(source_database, source_assets, destination_database, destination_assets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('backup', 'restore'))
    parser.add_argument('source')
    parser.add_argument('destination', help='New destination; existing files are refused')
    parser.add_argument('--assets-source', help='Asset directory paired with the source database')
    parser.add_argument('--assets-destination', help='New asset directory paired with the destination database')
    args = parser.parse_args()
    if bool(args.assets_source) != bool(args.assets_destination):
        parser.error('--assets-source and --assets-destination must be provided together')
    try:
        if args.assets_source:
            operation = backup_project_data if args.operation == 'backup' else restore_project_data
            result = operation(args.source, args.assets_source, args.destination, args.assets_destination)
        else:
            operation = backup_database if args.operation == 'backup' else restore_database
            result = operation(args.source, args.destination)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, 'Copy failed. Check paths, permissions and database integrity; any partial destination is retained.\n')
    print('Validated project data copy:' if args.assets_source else 'Validated database copy:', result)


if __name__ == '__main__':
    main()
