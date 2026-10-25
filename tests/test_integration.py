import unittest
from backend.hotstuff import HotStuffDemo
from backend.models import Block, QC

class HotStuffTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()

    def advance_until(self, predicate, limit=300):
        for _ in range(limit):
            if predicate():
                return
            self.demo.step()
        self.fail("Protocol did not reach expected state")

    def assert_agreement(self):
        live = [node for node in self.demo.nodes if not node.crashed]
        for node in live[1:]:
            self.assertEqual(node.committed_blocks, live[0].committed_blocks)
            self.assertEqual(node.machine.accounts, live[0].machine.accounts)
            self.assertEqual(node.machine.receipts, live[0].machine.receipts)
        for qc in self.demo.qcs.values():
            self.assertGreaterEqual(len(set(qc.voters)), 3)

    def test_three_chain_and_transfer(self):
        tx = self.demo.submit("Alice", "Bob", 10)
        self.advance_until(lambda: "B2" in self.demo.qcs)
        for node in self.demo.nodes:
            self.assertEqual(node.machine.accounts["Alice"], 100)
            self.assertEqual(node.locked_qc.block_id, "B1")
            self.assertEqual(node.high_qc.block_id, "B2")
        self.advance_until(lambda: "B3" in self.demo.qcs)
        for node in self.demo.nodes:
            self.assertIn("B1", node.committed_blocks)
            self.assertNotIn("B2", node.committed_blocks)
            self.assertEqual(node.machine.accounts, {"Alice": 90, "Bob": 110, "Charlie": 100})
        self.assertNotIn(tx.id, self.demo.mempool)
        for _ in range(60):
            self.demo.step()
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 90)
        self.assert_agreement()

    def test_insufficient_funds_rejected_at_commit(self):
        self.demo.submit("Alice", "Bob", 80)
        self.demo.submit("Alice", "Charlie", 80)
        self.advance_until(lambda: not self.demo.mempool)
        for node in self.demo.nodes:
            self.assertEqual(node.machine.accounts, {"Alice": 20, "Bob": 180, "Charlie": 100})
            self.assertEqual(node.machine.receipts["Tx2"]["status"], "rejected")
        self.assert_agreement()

    def test_lock_and_one_vote_per_view(self):
        node = self.demo.nodes[0]
        node.view = 3
        node.blocks["A"] = Block("A", "B0", 1, 1, [], self.demo.qcs["B0"])
        node.locked_qc = QC("A", 1, (1, 2, 3))
        fork = Block("F", "B0", 3, 3, [], self.demo.qcs["B0"])
        self.assertFalse(node.can_vote(fork))
        extension = Block("E", "A", 3, 3, [], node.locked_qc)
        self.assertTrue(node.can_vote(extension))
        node.last_voted_view = 3
        self.assertFalse(node.can_vote(extension))

    def test_batching_and_ancestor_deduplication(self):
        for _ in range(7):
            self.demo.submit("Alice", "Bob", 1)
        self.advance_until(lambda: not self.demo.mempool)
        self.assertEqual(len(self.demo.blocks["B1"].transactions), 5)
        self.assertEqual(len(self.demo.blocks["B2"].transactions), 2)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 93)
        self.assert_agreement()

    def test_reset_clears_faults_events_and_accounts(self):
        self.demo.submit("Alice", "Bob", 10)
        self.demo.step()
        self.demo.set_byzantine(4)
        self.demo.crash_leader()
        self.demo.running = True
        self.demo.reset()
        self.assertEqual(self.demo.view, 1)
        self.assertEqual(self.demo.steps, 0)
        self.assertEqual(len(self.demo.blocks), 1)
        self.assertFalse(self.demo.running)
        self.assertFalse(self.demo.mempool)
        self.assertTrue(all(not n.crashed and not n.withhold_vote for n in self.demo.nodes))
        self.assert_agreement()

    def test_invalid_transaction_inputs(self):
        for amount in (0, -1, 1.5, True, 1_000_001):
            with self.assertRaises(ValueError):
                self.demo.submit("Alice", "Bob", amount)
        with self.assertRaises(ValueError):
            self.demo.submit("Unknown", "Bob", 1)

