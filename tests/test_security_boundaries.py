"""Regressions for authentication bypass and lost committed rejection receipts."""
from dataclasses import replace
import unittest

from backend.blockchain import sign_transaction, transaction_id
from backend.hotstuff import HotStuffDemo
from backend.models import Transaction


def signed_transaction(nonce=0):
    return Transaction(
        transaction_id("Alice", "Bob", 10, nonce),
        "Alice", "Bob", 10, nonce,
        sign_transaction("Alice", "Bob", 10, nonce),
    )


class SecurityBoundaryTests(unittest.TestCase):
    def advance_until(self, demo, predicate):
        for _ in range(300):
            if predicate():
                return
            demo.step()
        self.fail("Consensus did not reach the expected state")

    def test_unsigned_admission_is_rejected_without_mutation(self):
        demo = HotStuffDemo()
        with self.assertRaises(ValueError):
            demo.submit("Alice", "Bob", 10)
        self.assertEqual(demo.mempool, [])
        self.assertEqual(demo.transactions, {})

    def test_committed_unsigned_payload_is_rejected_and_queryable(self):
        demo = HotStuffDemo()
        demo.step()
        demo.blocks["B1"].transactions = [Transaction("Tx1", "Alice", "Bob", 10)]
        self.advance_until(demo, lambda: "B1" in demo.nodes[0].committed_blocks)
        records = demo.snapshot()["execution_receipts"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["block_id"], "B1")
        self.assertEqual(records[0]["transaction_index"], 0)
        self.assertEqual(records[0]["status"], "rejected")
        for node in demo.nodes:
            self.assertEqual(node.machine.accounts["Alice"], 100)
            self.assertEqual(node.machine.nonces["Alice"], 0)
            self.assertNotIn("Tx1", node.machine.receipts)

    def test_invalid_attempt_has_a_receipt_without_poisoning_valid_retry(self):
        demo = HotStuffDemo()
        tx = signed_transaction()
        demo.step()
        demo.blocks["B1"].transactions = [replace(tx, signature="bad")]
        self.advance_until(demo, lambda: "B1" in demo.nodes[0].committed_blocks)
        failed = demo.snapshot()["execution_receipts"][0]
        self.assertEqual(failed["id"], tx.id)
        self.assertEqual(failed["status"], "rejected")
        self.assertNotIn(tx.id, demo.nodes[0].machine.receipts)
        demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.advance_until(demo, lambda: not demo.mempool)
        for node in demo.nodes:
            self.assertEqual(node.machine.receipts[tx.id]["status"], "committed")
            self.assertEqual(node.machine.accounts["Alice"], 90)
        records = demo.snapshot()["execution_receipts"]
        self.assertEqual([r["status"] for r in records], ["rejected", "committed"])

    def test_wrong_nonce_block_replay_does_not_retry_its_failed_execution(self):
        demo = HotStuffDemo()
        future = signed_transaction(nonce=1)
        demo.step()
        demo.blocks["B1"].transactions = [future]
        self.advance_until(demo, lambda: "B1" in demo.nodes[0].committed_blocks)
        first = signed_transaction()
        demo.submit(first.sender, first.receiver, first.amount, first.nonce, first.signature)
        self.advance_until(demo, lambda: not demo.mempool)
        for node in demo.nodes:
            before = node.machine.accounts.copy()
            receipts = node.execute_committed(["B1"])
            self.assertEqual(receipts[0]["status"], "rejected")
            self.assertEqual(node.machine.accounts, before)
            self.assertEqual(node.machine.nonces["Alice"], 1)
        self.assertEqual(len(demo.snapshot()["execution_receipts"]), 2)
