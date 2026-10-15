import sqlite3
from contextlib import closing
import threading
import unittest
from pathlib import Path
from uuid import uuid4

from coopagents.backup import backup_database, restore_database


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / ('backup-' + str(uuid4()))
        self.root.mkdir(parents=True)
        self.source = self.root / 'live.sqlite3'
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('CREATE TABLE evidence (value INTEGER PRIMARY KEY)')
            db.execute('INSERT INTO evidence VALUES (1)')

    def test_live_backup_restore_and_no_overwrite(self):
        stop = threading.Event()
        def write():
            with closing(sqlite3.connect(self.source)) as db:
                while not stop.is_set():
                    db.execute('INSERT INTO evidence SELECT max(value)+1 FROM evidence')
                    db.commit()
                    stop.wait(.01)
        worker = threading.Thread(target=write)
        worker.start()
        target = self.root / 'backup.sqlite3'
        try:
            backup_database(self.source, target)
        finally:
            stop.set()
            worker.join(5)
        restored = self.root / 'restored.sqlite3'
        restore_database(target, restored)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertGreaterEqual(db.execute('SELECT count(*) FROM evidence').fetchone()[0], 1)
        contents = target.read_bytes()
        for operation in (backup_database, restore_database):
            with self.assertRaises(FileExistsError):
                operation(self.source, target)
            self.assertEqual(target.read_bytes(), contents)
            with self.assertRaises(ValueError):
                operation(self.source, self.source)

    def test_missing_and_corrupt_source_do_not_create_destination(self):
        for source in (self.root / 'missing.sqlite3', self.root / 'corrupt.sqlite3'):
            if source.name.startswith('corrupt'):
                source.write_bytes(b'not a database')
            destination = self.root / (source.stem + '-result.sqlite3')
            with self.assertRaises((FileNotFoundError, sqlite3.DatabaseError)):
                restore_database(source, destination)
            self.assertFalse(destination.exists())
