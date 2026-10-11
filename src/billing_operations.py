"""Small durable outbound ledger. Remote I/O never holds its SQLite writer."""
import time
from uuid import uuid4

from .errors import Conflict


class BillingOperations:
    def __init__(self, store):
        self.store=store
        with store.db.connect(write=True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS billing_outbound_operations(
                operation_id TEXT PRIMARY KEY,team_id TEXT NOT NULL REFERENCES billing_teams(team_id),
                purpose TEXT NOT NULL CHECK(purpose IN ('customer','portal')),
                idempotency_key TEXT NOT NULL UNIQUE,created_at INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','complete')),provider_id TEXT)''')
            c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS billing_one_pending_outbound
                ON billing_outbound_operations(team_id,purpose) WHERE state='pending' ''')

    def reserve(self,team_id,purpose,*,key=None):
        if purpose not in ('customer','portal'):raise ValueError('Invalid outbound purpose')
        self.store.customer_state(team_id)
        with self.store.db.connect(write=True) as c:
            # Customer keys never rotate, including a completed creation that won a binding race.
            row=c.execute("SELECT * FROM billing_outbound_operations WHERE team_id=? AND purpose=?"+
                (" AND state='pending'" if purpose=='portal' else ''),(team_id,purpose)).fetchone()
            if row:return dict(row)
            operation_id=str(uuid4())
            key=key or purpose+'_'+str(uuid4())
            c.execute('INSERT INTO billing_outbound_operations VALUES(?,?,?,?,?,?,NULL)',
                (operation_id,team_id,purpose,key,int(time.time()),'pending'))
            return dict(c.execute('SELECT * FROM billing_outbound_operations WHERE operation_id=?',(operation_id,)).fetchone())

    def complete(self,operation,provider_id):
        with self.store.db.connect(write=True) as c:
            row=c.execute('SELECT * FROM billing_outbound_operations WHERE operation_id=?',(operation['operation_id'],)).fetchone()
            if row['provider_id'] not in (None,provider_id):raise Conflict('Outbound provider binding changed')
            c.execute("UPDATE billing_outbound_operations SET state='complete',provider_id=? WHERE operation_id=?",(provider_id,operation['operation_id']))

    def pending_customer_team(self,key):
        if not isinstance(key,str):return None
        with self.store.db.connect() as c:
            row=c.execute('SELECT team_id FROM billing_teams WHERE customer_key=? AND customer_id IS NULL AND provider_mode=?',
                (key,self.store.catalog.provider_mode)).fetchone()
            return row['team_id'] if row else None

    def customer_operation(self,team_id):
        with self.store.db.connect() as c:
            row=c.execute("SELECT * FROM billing_outbound_operations WHERE team_id=? AND purpose='customer'",(team_id,)).fetchone()
            return dict(row) if row else None
