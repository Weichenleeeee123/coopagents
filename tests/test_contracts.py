"""Contract behavior tests retain all SQLite evidence."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Barrier
import unittest
from uuid import uuid4
from unittest.mock import patch

from coopagents.identity import IdentityStore
from coopagents.messages import MessageStore
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError
try:
    from coopagents.contracts import ContractStore
except ModuleNotFoundError:
    ContractStore = None


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ContractStore, "Contracts are not implemented")
        root = Path(__file__).resolve().parents[1] / ".local" / "test-evidence"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"contracts-{uuid4()}.sqlite3"
        self.identity = IdentityStore(self.path)
        self.a = self.identity.create_room("Room", "Alice")
        self.b = self.identity.add_member(self.a["web_token"], "Bob")
        self.other = self.identity.create_room("Other", "Eve")
        self.store = ContractStore(self.identity)

    def propose(self, version=0, **kwargs):
        args = dict(agent_token=self.a["agent_token"], contract_key=" api ",
                    expected_version=version, title=" Title ", body=" Body ")
        args.update(kwargs)
        return self.store.propose(**args)

    def decide(self, contract, version=1, decision="approved", actor=None):
        return self.store.decide((actor or self.a)["web_token"], contract["id"], version, decision)

    def test_append_effective_decisions_and_events(self):
        first = self.propose()
        self.assertEqual((first["contract_key"], first["current_version"], first["effective_version"]), ("api", 1, None))
        self.assertEqual(first["versions"][0]["proposer_member_id"], self.a["member_id"])
        approved = self.decide(first)
        self.assertEqual(approved["effective_version"], 1)
        self.assertEqual(self.decide(first), approved)
        with self.assertRaises(Conflict): self.decide(first, decision="rejected")
        with self.assertRaises(Conflict): self.decide(first, actor=self.b)
        second = self.propose(1, title="New")
        self.assertEqual((second["current_version"], second["effective_version"]), (2, 1))
        for version, decision, actor in ((1,"approved",self.a),(2,"rejected",self.b)):
            if version == 1:
                with self.assertRaises(Conflict): self.decide(first, version, decision, actor)
            else:
                result = self.decide(first, version, decision, actor)
                self.assertEqual(result["effective_version"], 1)
        with self.assertRaises(Conflict): self.decide(first, 2, "approved")
        events = self.store.list_events(self.b["agent_token"])
        self.assertEqual([(e["event_type"],e["version"]) for e in events],
                         [("proposed",1),("approved",1),("proposed",2),("rejected",2)])
        self.assertTrue(all(e["created_at"] and e["actor_member_id"] for e in events))
        self.assertEqual(ContractStore(IdentityStore(self.path)).list_contracts(self.a["web_token"]), [result])
        third = self.propose(2, body="Third")
        self.assertEqual(third["versions"][0], approved["versions"][0])
        self.assertEqual(self.decide(first,3)["effective_version"],3)

    def test_permissions_isolation_and_revocation(self):
        with self.assertRaises(AccessDenied): self.propose(agent_token=self.a["web_token"])
        first = self.propose()
        with self.assertRaises(AccessDenied): self.store.decide(self.a["agent_token"], first["id"], 1, "approved")
        with self.assertRaises(NotFound): self.decide(first, actor=self.other)
        self.assertEqual(self.store.list_contracts(self.other["agent_token"]), [])
        self.assertEqual(self.store.list_events(self.other["web_token"]), [])
        self.identity.revoke_agent(self.a["web_token"], self.a["member_id"])
        with self.assertRaises(AccessDenied): self.propose(1)
        for token in (None, "unknown"):
            with self.assertRaises(AccessDenied): self.store.list_contracts(token)

    def test_input_types_boundaries_and_stale_head(self):
        for field, values in {"expected_version": [True, -1, 1.0, "0", None],
                              "contract_key": [None, " ", "k"*201],
                              "title": [1, "", "t"*201], "body": [False, " ", "b"*4001],
                              "commit_ref": [None, 1, "r"*201],
                              "source_request_id": [True, 0, -1, 1.0, "1"]}.items():
            for value in values:
                with self.subTest(field=field,value=value), self.assertRaises(ValidationError): self.propose(**{field:value})
        with self.assertRaises(Conflict): self.propose(1)
        first = self.propose(contract_key="k"*200,title="t"*200,body="b"*4000,commit_ref="r"*200)
        with self.assertRaises(Conflict): self.propose(contract_key="k"*200)
        for version in (True, 0, -1, "1", 1.0):
            with self.assertRaises(ValidationError): self.decide(first, version)
        for value in (None, [], "pending", "APPROVED"):
            with self.assertRaises(ValidationError): self.decide(first, decision=value)
        for value in (True, 0, "1", 1.0):
            with self.assertRaises(ValidationError): self.store.decide(self.a["web_token"],value,1,"approved")

    def test_source_request_and_atomic_rollback(self):
        messages = MessageStore(self.identity)
        source = messages.send_request(self.a["agent_token"],"q",None,None,1,"Need API")
        foreign = messages.send_request(self.other["agent_token"],"q",None,None,1,"Other")
        for request_id in (foreign["id"], 999999):
            with self.assertRaises(NotFound): self.propose(source_request_id=request_id)
        self.assertEqual(self.store.list_contracts(self.a["web_token"]), [])
        with patch.object(self.store, "_event", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError): self.propose(source_request_id=source["id"])
        self.assertEqual(self.store.list_contracts(self.a["web_token"]), [])
        first = self.propose(source_request_id=source["id"])
        self.assertEqual(first["versions"][0]["source_request_id"], source["id"])
        with patch.object(self.store, "_event", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError): self.decide(first)
        self.assertIsNone(self.store.list_contracts(self.a["web_token"])[0]["effective_version"])
        self.assertEqual(len(self.store.list_events(self.a["web_token"])),1)

    def test_concurrent_decisions_have_one_winner(self):
        first = self.propose()
        barrier = Barrier(2)
        def attempt(actor):
            barrier.wait()
            try: return self.decide(first, actor=actor)
            except Conflict: return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (self.a,self.b)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(len(self.store.list_events(self.a["web_token"])),2)

    def test_concurrent_proposals_append_once_and_room_keys_are_local(self):
        first = self.propose()
        barrier = Barrier(2)
        def attempt(actor):
            barrier.wait()
            try: return self.propose(1,agent_token=actor["agent_token"])
            except Conflict: return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt,(self.a,self.b)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.store.list_contracts(self.a["web_token"])[0]["current_version"],2)
        foreign = self.propose(agent_token=self.other["agent_token"])
        self.assertNotEqual(first["id"],foreign["id"])
        self.assertEqual(foreign["current_version"],1)
        self.assertEqual(len(self.store.list_events(self.a["web_token"])),2)

    def test_approval_advances_effective_and_optional_commit_is_stripped(self):
        first = self.propose(commit_ref="  " + "r"*200 + "  ")
        self.assertEqual(first["versions"][0]["commit_ref"],"r"*200)
        self.decide(first)
        second = self.propose(1,commit_ref="  ")
        self.assertEqual(second["versions"][1]["commit_ref"],"")
        self.assertEqual(self.decide(first,2,actor=self.b)["effective_version"],2)

    def test_database_enforces_same_room_sources_and_actors(self):
        first = self.propose()
        foreign_source = MessageStore(self.identity).send_request(
            self.other["agent_token"],"foreign",None,None,1,"Foreign source")
        with self.identity.db.connect(write=True) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""INSERT INTO contract_versions
                    (contract_id,room_id,version,proposer_member_id,title,body,created_at)
                    VALUES (?,?,?,?,?,?,?)""", (first["id"],self.a["room_id"],2,self.other["member_id"],"t","b","now"))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""INSERT INTO contract_versions
                    (contract_id,room_id,version,proposer_member_id,title,body,created_at,source_request_id)
                    VALUES (?,?,?,?,?,?,?,?)""", (first["id"],self.a["room_id"],2,self.a["member_id"],"t","b","now",foreign_source["id"]))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""INSERT INTO contract_decisions
                    (contract_id,room_id,version,decision,decided_by_member_id,decided_at)
                    VALUES (?,?,?,?,?,?)""", (first["id"],self.a["room_id"],1,"approved",self.other["member_id"],"now"))
        for token in (self.a["web_token"],self.a["agent_token"]):
            self.assertNotIn(token.encode(),self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
