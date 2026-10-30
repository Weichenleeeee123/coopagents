"""Project-scoped session discovery and evidence for exact Harness/version/platform combinations."""
from datetime import datetime, timezone
import json

from .errors import ValidationError
from .harness_adapters import adapter_for, SUPPORTED_HARNESSES
from .repositories import require_manager
from .tasks import _text, _utc_now

TARGET_HARNESSES = ('claude-code', 'codex', 'cursor', 'opencode', 'pi', 'kimi-code', 'zcode')
DISPLAY_NAMES = {'claude-code': 'Claude Code', 'codex': 'Codex', 'cursor': 'Cursor',
                 'opencode': 'OpenCode', 'pi': 'Pi', 'kimi-code': 'Kimi Code', 'zcode': 'ZCode'}
CAPABILITIES = ('mcp', 'project_context', 'session_lifecycle', 'native_hook', 'idle_wake')
STATUSES = ('supported', 'unsupported', 'unknown', 'unavailable')
STALE_SECONDS = 900
EVIDENCE_SECONDS = 30 * 86400


def when(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


class CapabilityStore:
    def __init__(self, identity):
        self.identity, self.db = identity, identity.db
        with self.db.connect(write=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS capability_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, harness TEXT NOT NULL,
                version TEXT NOT NULL,platform TEXT NOT NULL,capability TEXT NOT NULL,status TEXT NOT NULL,
                evidence TEXT NOT NULL,constraints TEXT NOT NULL,verified_by TEXT NOT NULL,verified_at TEXT NOT NULL,
                FOREIGN KEY(verified_by,room_id) REFERENCES members(id,room_id))""")

    def record(self, token, harness, version, platform, capability, status, evidence, constraints=''):
        if harness not in TARGET_HARNESSES or capability not in CAPABILITIES or status not in STATUSES:
            raise ValidationError('Unsupported Harness capability verification')
        version = _text(version, 'Version', 100)
        if version == 'unknown' or platform not in ('windows', 'macos', 'linux'):
            raise ValidationError('Verification requires an exact version and platform')
        evidence = _text(evidence, 'Evidence reference', 1000)
        if not isinstance(constraints, str) or len(constraints) > 1000:
            raise ValidationError('Constraints must contain at most 1000 characters')
        with self.db.connect(write=True) as db:
            principal = self.identity.resolve(db, token, required_kind='web')
            require_manager(self.identity, db, principal)
            cursor = db.execute("""INSERT INTO capability_verifications
                (room_id,harness,version,platform,capability,status,evidence,constraints,verified_by,verified_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (principal.room_id,harness,version,platform,capability,status,
                evidence,constraints,principal.member_id,_utc_now()))
            return dict(db.execute('SELECT * FROM capability_verifications WHERE id=?',(cursor.lastrowid,)).fetchone())

    def evidence(self, token):
        with self.db.connect() as db:
            p = self.identity.resolve(db, token)
            rows = [dict(r) for r in db.execute("""SELECT v.* FROM capability_verifications v WHERE v.room_id=?
                AND NOT EXISTS(SELECT 1 FROM capability_verifications n WHERE n.room_id=v.room_id
                AND n.harness=v.harness AND n.version=v.version AND n.platform=v.platform
                AND n.capability=v.capability AND n.id>v.id) ORDER BY v.id DESC LIMIT 501""",(p.room_id,))]
        return rows[:500], len(rows)>500

    def project(self, snapshot, *, now=None):
        now = now or datetime.now(timezone.utc)
        records = snapshot.get('capability_records', [])
        combinations = {}
        for record in records:
            combinations.setdefault((record['harness'],record['version'],record['platform']),{})[record['capability']] = record
        matrix = []
        for name in TARGET_HARNESSES:
            config = adapter_for(name).capabilities() if name in SUPPORTED_HARNESSES else {}
            caps = {key: ('unsupported' if config.get(key)=='unsupported' else 'unknown') for key in CAPABILITIES}
            matrix.append({'harness':name,'name':DISPLAY_NAMES[name], 'capabilities':caps,
                'configuration':{key:config.get(key,'unknown') for key in CAPABILITIES},
                'evidence':{'source':'adapter_contract' if config else 'unverified','version':'unknown','platform':'unknown',
                    'verified_at':None,'constraints':config.get('notes','Native capabilities require verification for the exact version and platform.')}})
        for (harness,version,platform), cells in combinations.items():
            caps = {key:'unknown' for key in CAPABILITIES}
            evidence = {}
            for key, row in cells.items():
                observed = when(row['verified_at'])
                caps[key] = row['status'] if observed and 0 <= (now-observed).total_seconds() <= EVIDENCE_SECONDS else 'stale'
                evidence[key] = {k:row[k] for k in ('id','status','evidence','constraints','verified_by','verified_at')}
            matrix.append({'harness':harness,'name':DISPLAY_NAMES[harness],'capabilities':caps,
                'evidence':{'source':'member_verification','version':version,'platform':platform,
                    'verified_at':max(r['verified_at'] for r in cells.values()),'constraints':'; '.join(dict.fromkeys(r['constraints'] for r in cells.values()))},
                'capability_evidence':evidence})
        by_key = {(r['member_id'],r['session_key']):r for r in snapshot.get('capabilities',[])}
        members=[]
        for member in snapshot.get('members',[]):
            agents=[]
            for session in snapshot.get('sessions',[]):
                if session['member_id'] != member['member_id']:
                    continue
                report = by_key.get((session['member_id'],session['session_key']),{})
                harness = report.get('harness') or ('codex' if session['tool'].startswith('codex') else session['tool'])
                version,platform = report.get('version','unknown'), report.get('platform','unknown')
                verified = next((r for r in matrix if r['harness']==harness and r['evidence']['version']==version
                                 and r['evidence']['platform']==platform), None)
                observed = when(session['updated_at'])
                fresh = observed is not None and 0 <= (now-observed).total_seconds() <= STALE_SECONDS
                available = report.get('credential_status','unknown')
                checkpoint = next((c for c in snapshot.get('collaboration',{}).get('checkpoints',[])
                                   if c.get('member_id')==session['member_id']
                                   and c.get('session_key')==session['session_key']
                                   and c.get('tool')==session['tool']),None)
                last_seen = checkpoint.get('updated_at') if checkpoint else None
                last_seen_at = when(last_seen)
                recently_present = last_seen_at is not None and 0 <= (now-last_seen_at).total_seconds() <= STALE_SECONDS
                agents.append({'session_key':session['session_key'],'tool':session['tool'],'harness':harness,
                    'version':version,'platform':platform,'repository':session['repository'],'branch':session['branch'],
                    'task_id':session['task_id'],'updated_at':session['updated_at'],
                    'status':'unavailable' if available=='unavailable' else 'registered' if fresh else 'stale',
                    'credential_status':available,'connection_status':'unknown','model_status':'unknown',
                    'last_seen_at':last_seen,'recent_presence':'recent' if recently_present else 'stale' if last_seen_at else 'unknown',
                    'event_delivery_status':'unknown','last_event_delivery_at':None,
                    'capabilities':verified['capabilities'] if verified else {key:'unknown' for key in CAPABILITIES},
                    'capability_evidence':verified.get('capability_evidence',{}) if verified else {},
                    'reported_capabilities':report.get('capabilities',{}), 'evidence_source':report.get('evidence_source','session_registry')})
            members.append({**member,'agents':agents,'agent_count':len(agents),
                'last_registered_at':max((a['updated_at'] for a in agents),default=None)})
        return {'members':members,'harnesses':matrix,'generated_at':now.isoformat(),
            'status_legend':['supported','unsupported','unknown','unavailable','stale'],
            'verification_truncated':snapshot.get('capability_records_truncated',False)}
