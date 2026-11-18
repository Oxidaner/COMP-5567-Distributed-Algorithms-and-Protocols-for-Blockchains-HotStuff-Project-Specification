import unittest
from backend.hotstuff import HotStuffDemo
from backend.models import Block, QC
from backend.blockchain import sign_transaction

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

    def test_crash_leader_timeout_and_recovery(self):
        self.demo.crash_leader()
        self.demo.submit("Alice", "Bob", 10)
        self.advance_until(lambda: self.demo.view == 2)
        self.assertEqual(self.demo.leader_id, 2)
        self.assertEqual(self.demo.nodes[0].view, 1)
        self.advance_until(lambda: self.demo.nodes[1].machine.accounts["Alice"] == 90)
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 100)
        self.assert_agreement()
        self.demo.recover()
        self.assertTrue(all(not node.crashed for node in self.demo.nodes))
        self.assert_agreement()

    def test_one_byzantine_replica_and_leader_rotation(self):
        self.demo.set_byzantine(4)
        self.demo.submit("Alice", "Bob", 10)
        self.advance_until(lambda: self.demo.view >= 6)
        for block_id, qc in self.demo.qcs.items():
            if block_id != "B0":
                self.assertEqual(qc.voters, (1, 2, 3))
        self.assertEqual(self.demo.nodes[3].machine.accounts["Alice"], 90)
        self.assert_agreement()

    def test_two_unavailable_voters_stall_without_false_qc(self):
        self.demo.crash_leader()
        self.demo.set_byzantine(4)
        for _ in range(60):
            self.demo.step()
        self.assertGreater(self.demo.view, 2)
        self.assertEqual(list(self.demo.qcs), ["B0"])
        self.assert_agreement()

    def test_orphaned_transaction_is_reproposed(self):
        tx = self.demo.submit("Alice", "Bob", 10)
        self.demo.step()  # B1 proposed, but its leader dies before QC.
        self.demo.crash_leader()
        self.advance_until(lambda: self.demo.nodes[1].machine.accounts["Alice"] == 90)
        self.assertNotIn("B1", self.demo.qcs)
        self.assertIn(tx, self.demo.blocks["B2"].transactions)
        self.assertNotIn(tx.id, self.demo.mempool)
        self.demo.recover()
        self.assert_agreement()

    def test_view_gap_delays_commit_until_consecutive_chain(self):
        self.advance_until(lambda: self.demo.view == 2)
        self.demo.crash_leader()  # Skip view 2; next chain has views 1,3,4.
        self.advance_until(lambda: self.demo.view == 5)
        self.assertEqual(self.demo.nodes[0].committed_blocks, ["B0"])
        self.advance_until(lambda: self.demo.view == 6)
        # The 3,4,5 chain commits view 3 and also its view 1 ancestor.
        self.assertEqual(self.demo.nodes[0].committed_blocks, ["B0", "B1", "B2"])
        self.assert_agreement()

    def test_recovery_does_not_lower_existing_lock(self):
        node = self.demo.nodes[0]
        block = Block('B1', 'B0', 1, 1, [], self.demo.qcs['B0'])
        certificate = QC('B1', 1, (1, 2, 3))
        self.demo.blocks[block.id] = block
        self.demo.qcs[block.id] = certificate
        node.blocks[block.id] = block
        node.high_qc = certificate
        node.locked_qc = certificate
        node.crashed = True

        self.demo.recover()

        self.assertEqual(node.high_qc, certificate)
        self.assertEqual(node.locked_qc, certificate)
        self.assertIn(block.id, node.blocks)

    def test_recovery_restores_receipt_and_nonce_state(self):
        signature = sign_transaction('Alice', 'Bob', 10, 0)
        tx = self.demo.submit('Alice', 'Bob', 10, 0, signature)
        self.demo.crash_leader()
        self.advance_until(lambda: tx.id in self.demo.nodes[1].machine.receipts)
        self.demo.recover()
        for node in self.demo.nodes:
            self.assertEqual(node.machine.receipts[tx.id],
                             {'status': 'committed', 'error': None})
            self.assertEqual(node.machine.nonces['Alice'], 1)

