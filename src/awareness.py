"""Room-scoped discovery of active work and durable, evidence-backed implementation choices."""
from datetime import datetime, timedelta, timezone
import re
import unicodedata

from .errors import Conflict, NotFound, ValidationError
from .protocol import _text, fields


OPERATIONS = {
    'share_work': fields('subject summary', {'reference': '', 'also_called': ''}),
    'find_related': fields('subject', {'also_called': ''}),
    'remember_choice': fields('subject summary request_id reply_id expected_revision', {'reference': ''}),
}

# Ignore scaffolding words which would otherwise connect unrelated features.
_GENERIC = set('a an the for to in of and add build create fix update implement page pages screen '
               'frontend component feature work on ui 页面 前端 实现 功能 开发 添加 修改'.split())
_WORDS = re.compile(r'[\u3400-\u9fff]+|[^\W_]+', re.UNICODE)


def topic(value, also_called=''):
    label = _text(value, 'subject', 120)
    key = ' '.join(unicodedata.normalize('NFKC', label).casefold().split())
    aliases = []
    if also_called:
        alias_text = _text(also_called, 'also_called', 120)
        aliases = unicodedata.normalize('NFKC', alias_text).casefold().split(',')
    terms = {}
    for phrase in (key, *aliases):
        phrase = ' '.join(phrase.split())
        if not phrase or phrase in _GENERIC:
            continue
        terms[phrase] = 1
        for word in _WORDS.findall(phrase):
            if '\u3400' <= word[0] <= '\u9fff':
                tokens = [word[i:i+2] for i in range(len(word)-1)]
            else:
                tokens = [word] if len(word) > 1 else []
            for token in tokens:
                if token not in _GENERIC:
                    terms.setdefault(token, 0)
    return label, key, terms


class AwarenessStore:
    def __init__(self, identity, *, clock=None):
        self.identity = identity
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with identity.db.connect(write=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS work_subjects (
                id INTEGER PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id),
                label TEXT NOT NULL, subject_key TEXT NOT NULL, UNIQUE(room_id, subject_key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS work_terms (
                subject_id INTEGER NOT NULL REFERENCES work_subjects(id), term TEXT NOT NULL, whole INTEGER NOT NULL,
                PRIMARY KEY(term, subject_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS work_signals (
                subject_id INTEGER NOT NULL REFERENCES work_subjects(id), member_id TEXT NOT NULL REFERENCES members(id),
                summary TEXT NOT NULL, reference TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                PRIMARY KEY(subject_id, member_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS implementation_choices (
                subject_id INTEGER NOT NULL REFERENCES work_subjects(id), revision INTEGER NOT NULL,
                member_id TEXT NOT NULL REFERENCES members(id), summary TEXT NOT NULL, reference TEXT NOT NULL,
                request_id INTEGER NOT NULL, reply_id INTEGER NOT NULL REFERENCES message_replies(id),
                updated_at TEXT NOT NULL, PRIMARY KEY(subject_id, revision), UNIQUE(subject_id, reply_id))""")

    @staticmethod
    def _subject(db, room, label, key, terms):
        db.execute('INSERT INTO work_subjects(room_id,label,subject_key) VALUES(?,?,?) '
                   'ON CONFLICT(room_id,subject_key) DO NOTHING', (room, label, key))
        subject_id = db.execute('SELECT id FROM work_subjects WHERE room_id=? AND subject_key=?',
                                (room, key)).fetchone()[0]
        db.executemany("""INSERT INTO work_terms(subject_id,term,whole) VALUES(?,?,?)
            ON CONFLICT(term,subject_id) DO UPDATE SET whole=MAX(whole,excluded.whole)""",
            [(subject_id, term, whole) for term, whole in terms.items()])
        return subject_id

    @staticmethod
    def _related(db, principal, key, terms, now):
        # Evaluate eligible signals/current decisions before limiting results. Expired
        # work and historical revisions cannot crowd out a current implementation.
        # One shared generic fragment ("settings" in two different settings pages)
        # is weak. A full label/alias or two common terms warrants a closer look.
        slots = ','.join('(?,?)' for _ in terms) or '(NULL,0)'
        matches = f"""WITH probe(term,whole) AS (VALUES {slots}), matches AS (
            SELECT s.id,s.label,1000 AS score FROM work_subjects s WHERE room_id=? AND subject_key=?
            UNION ALL SELECT s.id,s.label,SUM(1 + MAX(t.whole,p.whole)) AS score
            FROM probe p JOIN work_terms t ON t.term=p.term JOIN work_subjects s ON s.id=t.subject_id
            WHERE s.room_id=? AND s.subject_key<>? GROUP BY s.id HAVING SUM(1 + MAX(t.whole,p.whole))>=2)
            SELECT m.label AS subject,m.score,"""
        bindings = [v for pair in terms.items() for v in pair]
        args = (*bindings, principal.room_id, key, principal.room_id, key)
        signals = db.execute(matches + """ w.member_id,w.summary,w.reference,w.updated_at,w.expires_at
            FROM matches m JOIN work_signals w ON w.subject_id=m.id
            WHERE w.member_id<>? AND w.expires_at>? ORDER BY m.score DESC,w.updated_at DESC,m.id,w.member_id LIMIT 6""",
            (*args, principal.member_id, now))
        choices = db.execute(matches + """ c.revision,c.member_id,c.summary,c.reference,c.request_id,c.reply_id,c.updated_at
            FROM matches m JOIN implementation_choices c ON c.subject_id=m.id
            WHERE c.revision=(SELECT MAX(revision) FROM implementation_choices WHERE subject_id=m.id)
            ORDER BY m.score DESC,c.updated_at DESC,m.id LIMIT 6""", args)
        def project(rows):
            result = []
            for row in rows:
                item = dict(row)
                item['match'] = 'same_subject' if item.pop('score') == 1000 else 'shared_terms'
                result.append(item)
            return result
        return {'related_work': project(signals), 'choices': project(choices)}

    def find_related(self, token, subject, also_called=''):
        _, key, terms = topic(subject, also_called)
        with self.identity.db.connect() as db:
            db.execute('BEGIN')
            principal = self.identity.resolve(db, token, 'agent')
            return self._related(db, principal, key, terms, self.clock().isoformat())

    def share_work(self, token, subject, summary, reference='', also_called=''):
        label, key, terms = topic(subject, also_called)
        summary = _text(summary, 'summary', 400)
        if reference:
            reference = _text(reference, 'reference', 500)
        with self.identity.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, 'agent')
            now = self.clock()
            subject_id = self._subject(db, p.room_id, label, key, terms)
            expires = (now + timedelta(hours=6)).isoformat()
            db.execute("""INSERT INTO work_signals VALUES(?,?,?,?,?,?)
                ON CONFLICT(subject_id,member_id) DO UPDATE SET summary=excluded.summary,
                reference=excluded.reference,updated_at=excluded.updated_at,expires_at=excluded.expires_at""",
                (subject_id, p.member_id, summary, reference, now.isoformat(), expires))
            return {'expires_at': expires, **self._related(db, p, key, terms, now.isoformat())}

    def remember_choice(self, token, subject, summary, request_id, reply_id, expected_revision, reference=''):
        label, key, terms = topic(subject)
        summary = _text(summary, 'summary', 400)
        if (any(type(n) is not int or not 0 < n < 2**63 for n in (request_id, reply_id))
                or type(expected_revision) is not int or not 0 <= expected_revision < 2**63 - 1):
            raise ValidationError('Invalid request, reply or revision')
        with self.identity.db.connect(write=True) as db:
            p = self.identity.resolve(db, token, 'agent')
            answer = db.execute("""SELECT y.evidence FROM message_requests r JOIN message_replies y ON r.id=y.request_id
                WHERE r.room_id=? AND r.sender_member_id=? AND r.receiver_member_id<>r.sender_member_id
                AND y.author_member_id=r.receiver_member_id AND r.id=? AND y.id=?
                AND r.task_id IS NULL AND y.context_version=r.context_version""", (p.room_id, p.member_id, request_id, reply_id)).fetchone()
            if answer is None:
                raise NotFound('No matching answer from a teammate to your request')
            if not answer['evidence']:
                raise ValidationError('The teammate must supply the chosen implementation reference in reply.evidence')
            reference = _text(reference, 'reference', 500) if reference else answer['evidence']
            if reference not in answer['evidence']:
                raise ValidationError('Use the exact implementation reference from the answer evidence')
            sid = self._subject(db, p.room_id, label, key, terms)
            existing = db.execute('SELECT * FROM implementation_choices WHERE subject_id=? AND reply_id=?',
                                  (sid, reply_id)).fetchone()
            if existing:
                if (existing['revision'] != expected_revision + 1 or existing['summary'] != summary
                        or existing['reference'] != reference):
                    raise Conflict('Answer already recorded with a different payload')
                return dict(existing, subject=label)
            current = db.execute('SELECT COALESCE(MAX(revision),0) FROM implementation_choices WHERE subject_id=?',
                                 (sid,)).fetchone()[0]
            if expected_revision != current:
                raise Conflict('Implementation choice changed; find_related before revising it')
            row = db.execute("""INSERT INTO implementation_choices VALUES(?,?,?,?,?,?,?,?)
                RETURNING *""", (sid, current + 1, p.member_id, summary, reference,
                                 request_id, reply_id, self.clock().isoformat())).fetchone()
            return dict(row, subject=label)
