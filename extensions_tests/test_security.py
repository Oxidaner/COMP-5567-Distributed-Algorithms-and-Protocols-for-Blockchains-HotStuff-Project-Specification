"""B6 checks use real signatures and consensus, not committed-history fixtures."""
from dataclasses import replace
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.blockchain import (
    CLASSROOM_PRIVATE_KEYS,
    StateMachine,
    sign_transaction,
    transaction_id,
    verify_transaction,
)
from backend.hotstuff import HotStuffDemo
from backend.models import Transaction


def signed_transaction(sender="Alice", receiver="Bob", amount=10, nonce=0):
    return Transaction(
        transaction_id(sender, receiver, amount, nonce),
        sender, receiver, amount, nonce,
        sign_transaction(sender, receiver, amount, nonce),
    )


class SignatureTests(unittest.TestCase):
    def test_standard_ed25519_signature_and_public_key_verification(self):
        seed = bytes(range(32))
        key = Ed25519PrivateKey.from_private_bytes(seed)
        payload = (
            b'{"amount":10,"chain":"COMP5567-HotStuff","nonce":0,'
            b'"receiver":"Bob","sender":"Alice"}'
        )
        signature = sign_transaction("Alice", "Bob", 10, 0, private_key=seed)
        key.public_key().verify(bytes.fromhex(signature), payload)
        self.assertTrue(verify_transaction(
            "Alice", "Bob", 10, 0, signature,
            public_key=key.public_key().public_bytes_raw(),
        ))

    def test_tampering_wrong_account_and_domain_are_rejected(self):
        tx = signed_transaction()
        self.assertFalse(verify_transaction("Alice", "Charlie", 10, 0, tx.signature))
        self.assertFalse(verify_transaction("Alice", "Bob", 11, 0, tx.signature))
        self.assertFalse(verify_transaction("Alice", "Bob", 10, 1, tx.signature))
        wrong_account = sign_transaction(
            "Alice", "Bob", 10, 0, private_key=CLASSROOM_PRIVATE_KEYS["Bob"]
        )
        self.assertFalse(verify_transaction("Alice", "Bob", 10, 0, wrong_account))
        other_domain = (
            b'{"amount":10,"chain":"another-chain","nonce":0,'
            b'"receiver":"Bob","sender":"Alice"}'
        )
        key = Ed25519PrivateKey.from_private_bytes(CLASSROOM_PRIVATE_KEYS["Alice"])
        self.assertFalse(verify_transaction(
            "Alice", "Bob", 10, 0, key.sign(other_domain).hex()
        ))

    def test_malformed_signatures_return_false(self):
        for signature in ("", "not-hex", "00", "\u7b7e\u540d", None, 123):
            with self.subTest(signature=signature):
                self.assertFalse(verify_transaction("Alice", "Bob", 10, 0, signature))


class ExecutionIdentityTests(unittest.TestCase):
    def test_signed_id_must_match_the_authenticated_payload(self):
        tx = signed_transaction()
        impostor = signed_transaction("Bob", "Charlie", 1)
        for invalid in (
            replace(tx, id="arbitrary-id"),
            replace(tx, nonce=None, signature=None),
            replace(impostor, id=tx.id),
        ):
            with self.subTest(transaction=invalid):
                machine = StateMachine()
                self.assertEqual(machine.apply(invalid)["status"], "rejected")
                self.assertEqual(machine.accounts, {"Alice": 100, "Bob": 100, "Charlie": 100})
                self.assertEqual(machine.nonces, {"Alice": 0, "Bob": 0, "Charlie": 0})
                self.assertEqual(machine.receipts, {})

    def test_invalid_signature_does_not_poison_a_later_valid_execution(self):
        machine = StateMachine()
        tx = signed_transaction()
        self.assertEqual(machine.apply(replace(tx, signature="bad"))["status"], "rejected")
        self.assertNotIn(tx.id, machine.receipts)
        self.assertEqual(machine.nonces["Alice"], 0)
        self.assertEqual(machine.apply(tx)["status"], "committed")
        self.assertEqual(machine.accounts["Alice"], 90)
        self.assertEqual(machine.nonces["Alice"], 1)

    def test_cached_receipt_does_not_bypass_signature_verification(self):
        machine = StateMachine()
        tx = signed_transaction()
        receipt = machine.apply(tx)
        for invalid in (replace(tx, amount=99), replace(tx, signature="bad")):
            self.assertEqual(machine.apply(invalid)["status"], "rejected")
        self.assertEqual(machine.receipts[tx.id], receipt)
        self.assertEqual(machine.apply(tx), receipt)
        self.assertEqual(machine.accounts["Alice"], 90)
        self.assertEqual(machine.nonces["Alice"], 1)

    def test_wrong_nonce_reserves_neither_nonce_nor_identity(self):
        machine = StateMachine()
        future = signed_transaction(nonce=1)
        self.assertEqual(machine.apply(future)["status"], "rejected")
        self.assertNotIn(future.id, machine.receipts)
        self.assertEqual(machine.nonces["Alice"], 0)
        self.assertEqual(machine.apply(signed_transaction())["status"], "committed")
        self.assertEqual(machine.apply(future)["status"], "committed")
        self.assertEqual(machine.accounts["Alice"], 80)
        self.assertEqual(machine.nonces["Alice"], 2)


class SecurityConsensusTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()

    def advance_until(self, predicate, limit=300):
        for _ in range(limit):
            if predicate():
                return
            self.demo.step()
        self.fail("Consensus did not reach the expected application state")

    def assert_agreement(self):
        live = [node for node in self.demo.nodes if not node.crashed]
        for node in live[1:]:
            self.assertEqual(node.committed_blocks, live[0].committed_blocks)
            self.assertEqual(node.machine.accounts, live[0].machine.accounts)
            self.assertEqual(node.machine.receipts, live[0].machine.receipts)
            self.assertEqual(node.machine.nonces, live[0].machine.nonces)
            self.assertEqual(node.machine.execution_receipts, live[0].machine.execution_receipts)

    def test_relabelled_payload_does_not_finalize_another_transaction(self):
        tx = signed_transaction()
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.demo.step()
        impostor = replace(signed_transaction("Bob", "Charlie", 1), id=tx.id)
        # A malicious proposer substitutes a payload before any votes are cast.
        self.demo.blocks["B1"].transactions = [impostor]
        self.advance_until(lambda: "B1" in self.demo.nodes[0].committed_blocks)
        self.assertIn(tx.id, self.demo.mempool)
        for node in self.demo.nodes:
            self.assertNotIn(tx.id, node.machine.receipts)
            self.assertEqual(node.machine.accounts, {"Alice": 100, "Bob": 100, "Charlie": 100})
        self.advance_until(lambda: not self.demo.mempool)
        self.assertEqual(self.demo.nodes[0].machine.accounts, {"Alice": 90, "Bob": 110, "Charlie": 100})
        self.assertEqual(self.demo.nodes[0].machine.receipts[tx.id]["status"], "committed")
        self.assert_agreement()

    def test_bad_committed_signature_cannot_block_later_admission(self):
        tx = signed_transaction()
        self.demo.step()
        self.demo.blocks["B1"].transactions = [replace(tx, signature="bad")]
        self.advance_until(lambda: "B1" in self.demo.nodes[0].committed_blocks)
        for node in self.demo.nodes:
            self.assertNotIn(tx.id, node.machine.receipts)
            self.assertEqual(node.machine.nonces["Alice"], 0)
        failed = self.demo.snapshot()["execution_receipts"][0]
        self.assertEqual(failed["status"], "rejected")
        self.assertEqual(failed["block_id"], "B1")
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.advance_until(lambda: not self.demo.mempool)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 90)
        self.assert_agreement()

    def test_wrong_nonce_in_committed_ancestry_does_not_block_future_nonce(self):
        future = signed_transaction(receiver="Charlie", nonce=1)
        self.demo.step()
        self.demo.blocks["B1"].transactions = [future]
        self.advance_until(lambda: "B1" in self.demo.nodes[0].committed_blocks)
        self.assertNotIn(future.id, self.demo.nodes[0].machine.receipts)
        self.assertEqual(self.demo.snapshot()["execution_receipts"][0]["status"], "rejected")
        first = signed_transaction()
        self.demo.submit(first.sender, first.receiver, first.amount, first.nonce, first.signature)
        self.advance_until(lambda: not self.demo.mempool)
        self.demo.submit(
            future.sender, future.receiver, future.amount, future.nonce, future.signature
        )
        self.advance_until(lambda: not self.demo.mempool)
        self.assertEqual(self.demo.nodes[0].machine.accounts, {"Alice": 80, "Bob": 110, "Charlie": 110})
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 2)
        self.assert_agreement()

    def test_consecutive_future_nonces_queue_and_execute_in_order(self):
        txs = [signed_transaction(amount=1, nonce=nonce) for nonce in range(7)]
        for tx in txs:
            self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 0)
        self.assertEqual(len(self.demo.mempool), 7)
        gap = signed_transaction(nonce=8)
        with self.assertRaises(ValueError):
            self.demo.submit(gap.sender, gap.receiver, gap.amount, gap.nonce, gap.signature)
        self.advance_until(lambda: not self.demo.mempool)
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 7)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 93)
        self.assertEqual([tx.nonce for tx in self.demo.blocks["B1"].transactions], list(range(5)))
        self.assertEqual([tx.nonce for tx in self.demo.blocks["B2"].transactions], [5, 6])
        self.assert_agreement()

    def test_signed_retries_before_and_after_commit_keep_one_identity(self):
        tx = signed_transaction()
        first = self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        retry = self.demo.submit(
            tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature.upper()
        )
        self.assertIs(first, retry)
        self.assertEqual(self.demo.mempool, [tx.id])
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 100)
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 0)
        self.advance_until(lambda: "B2" in self.demo.qcs)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 100)
        self.advance_until(lambda: not self.demo.mempool)
        receipt = self.demo.nodes[0].machine.receipts[tx.id].copy()
        self.assertIs(
            self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature),
            first,
        )
        self.assertFalse(self.demo.mempool)
        for _ in range(30):
            self.demo.step()
        self.assertEqual(self.demo.nodes[0].machine.receipts[tx.id], receipt)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 90)
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 1)
        self.assert_agreement()

    def test_admission_rejects_invalid_signatures_and_conflicting_nonces(self):
        tx = signed_transaction()
        for nonce, signature in (
            (0, "bad"), (0, "\u7b7e\u540d"), (True, tx.signature), (-1, tx.signature),
            (None, tx.signature), (0, None),
            (1, sign_transaction("Alice", "Bob", 10, 1)),
        ):
            with self.subTest(nonce=nonce, signature=signature):
                with self.assertRaises(ValueError):
                    self.demo.submit("Alice", "Bob", 10, nonce, signature)
                self.assertFalse(self.demo.mempool)
                self.assertFalse(self.demo.transactions)
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        conflict = signed_transaction(receiver="Charlie")
        with self.assertRaises(ValueError):
            self.demo.submit(
                conflict.sender, conflict.receiver, conflict.amount,
                conflict.nonce, conflict.signature,
            )
        self.advance_until(lambda: not self.demo.mempool)
        with self.assertRaises(ValueError):
            self.demo.submit(
                conflict.sender, conflict.receiver, conflict.amount,
                conflict.nonce, conflict.signature,
            )

    def test_authenticated_insufficient_funds_consumes_nonce_only_once(self):
        tx = signed_transaction(amount=101)
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.advance_until(lambda: not self.demo.mempool)
        for node in self.demo.nodes:
            self.assertEqual(node.machine.receipts[tx.id]["status"], "rejected")
            self.assertEqual(node.machine.accounts["Alice"], 100)
            self.assertEqual(node.machine.nonces["Alice"], 1)
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.assertFalse(self.demo.mempool)
        next_tx = signed_transaction(nonce=1)
        self.demo.submit(
            next_tx.sender, next_tx.receiver, next_tx.amount, next_tx.nonce, next_tx.signature
        )
        self.advance_until(lambda: not self.demo.mempool)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 90)
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 2)
        self.assert_agreement()

    def test_signed_orphan_is_reproposed_and_recovery_preserves_receipts_and_nonces(self):
        tx = signed_transaction()
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.demo.step()
        self.demo.crash_leader()
        self.advance_until(lambda: self.demo.nodes[1].machine.nonces["Alice"] == 1)
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 0)
        self.assertNotIn("B1", self.demo.qcs)
        self.demo.recover()
        self.assert_agreement()
        self.assertTrue(all(node.machine.nonces["Alice"] == 1 for node in self.demo.nodes))
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.assertFalse(self.demo.mempool)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 90)

    def test_reset_restores_nonce_receipt_and_batch_state(self):
        tx = signed_transaction()
        self.demo.submit(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        self.advance_until(lambda: not self.demo.mempool)
        self.demo.configure_batch(2)
        self.demo.reset()
        self.assertEqual(self.demo.max_txs_per_block, 5)
        for node in self.demo.nodes:
            self.assertEqual(node.machine.nonces, {"Alice": 0, "Bob": 0, "Charlie": 0})
            self.assertEqual(node.machine.receipts, {})
            self.assertEqual(node.machine.execution_receipts, {})
