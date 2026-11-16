"""Append-preserving task reliance on approved shared agreement versions."""
from .errors import Conflict, NotFound, ValidationError
from .messages import _positive
from .task_lifecycle import execution_task
from .tasks import _utc_now


SCHEMA = {
    'task_id': (int, True, None), 'contract_id': (int, True, None),
    'version': (int, True, None), 'session_key': (str, False, None),
    'ownership_epoch': (int, False, None),
}


class AgreementUsageStore:
    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        with self.db.connect(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS task_agreement_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                task_id INTEGER NOT NULL, contract_id INTEGER NOT NULL, version INTEGER NOT NULL,
                member_id TEXT NOT NULL, session_key TEXT NOT NULL, ownership_epoch INTEGER NOT NULL,
                used_at TEXT NOT NULL,
                UNIQUE(task_id,contract_id,version,member_id,session_key,ownership_epoch),
                FOREIGN KEY(task_id,room_id) REFERENCES tasks(id,room_id),
                FOREIGN KEY(contract_id,room_id,version) REFERENCES contract_versions(contract_id,room_id,version),
                FOREIGN KEY(member_id,room_id) REFERENCES members(id,room_id))''')
            db.execute('''CREATE INDEX IF NOT EXISTS agreement_use_task
                ON task_agreement_uses(room_id,task_id,contract_id)''')

    def record(self, token, task_id, contract_id, version, session_key=None, ownership_epoch=None):
        contract_id = _positive(contract_id, 'Contract id')
        version = _positive(version, 'Version')
        if contract_id >= 2**63 or version >= 2**63:
            raise ValidationError('Agreement identifiers must fit signed 64-bit integers')
        with self.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, required_kind='agent')
            task = execution_task(db, p, task_id, session_key, ownership_epoch)
            contract = db.execute('SELECT id FROM contracts WHERE id=? AND room_id=?',
                                  (contract_id, p.room_id)).fetchone()
            if not contract:
                raise NotFound('Contract not found')
            approved = db.execute('''SELECT 1 FROM contract_decisions
                WHERE contract_id=? AND room_id=? AND version=? AND decision='approved' ''',
                (contract_id, p.room_id, version)).fetchone()
            if not approved:
                raise Conflict('Only an approved agreement version can be used')
            key = task['execution_session_key'] or ''
            db.execute('''INSERT INTO task_agreement_uses
                (room_id,task_id,contract_id,version,member_id,session_key,ownership_epoch,used_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
                (p.room_id, task_id, contract_id, version, p.member_id, key, task['ownership_epoch'], _utc_now()))
            record = dict(db.execute('''SELECT * FROM task_agreement_uses
                WHERE task_id=? AND contract_id=? AND version=? AND member_id=?
                    AND session_key=? AND ownership_epoch=?''',
                (task_id, contract_id, version, p.member_id, key, task['ownership_epoch'])).fetchone())
            current = next(item for item in self.project(db, p, task_id) if item['contract_id'] == contract_id)
            return {**record, 'baseline_version': current['baseline_version'],
                    'effective_version': current['effective_version'],
                    'review_required': current['review_required']}

    @staticmethod
    def project(db, p, task_id=None):
        rows = db.execute('''SELECT u.task_id,u.contract_id,MAX(u.version) AS baseline_version,
                t.title AS task_title,t.owner_member_id,t.execution_session_key,t.ownership_epoch,
                MAX(u.used_at) AS used_at,
                (SELECT MAX(d.version) FROM contract_decisions d WHERE d.contract_id=u.contract_id
                    AND d.room_id=u.room_id AND d.decision='approved') AS effective_version
            FROM task_agreement_uses u JOIN tasks t ON t.id=u.task_id AND t.room_id=u.room_id
            WHERE u.room_id=? AND t.cancelled_at IS NULL AND t.state='claimed'
                AND u.member_id=t.owner_member_id AND u.ownership_epoch=t.ownership_epoch
                AND u.session_key=COALESCE(t.execution_session_key,'')
                AND (? IS NULL OR t.id=?) GROUP BY u.task_id,u.contract_id
            ORDER BY u.task_id,u.contract_id''', (p.room_id, task_id, task_id)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            current = db.execute('''SELECT title,body FROM contract_versions
                WHERE contract_id=? AND room_id=? AND version=?''',
                (row['contract_id'], p.room_id, row['effective_version'])).fetchone()
            item['title'] = current['title']
            item['body'] = current['body'][:800]
            item['excerpted'] = len(current['body']) > 800
            item['review_required'] = row['effective_version'] > row['baseline_version']
            result.append(item)
        return result
