"""A7 safety evidence for the lock/commit side of conflicting proposals."""
import unittest
from itertools import product

from backend.hotstuff import HotStuffDemo
from backend.models import QC


class AttackCommitSafetyTests(unittest.TestCase):
    def test_late_equivocation_preserves_already_scheduled_qc(self):
        demo = HotStuffDemo()
        demo.step()  # B1 is proposed.
        original = 'B1'
        for _ in range(3):
            demo.step()  # Three authenticated votes schedule a QC.
        self.assertIn(('qc', original), demo.events)

        rivals = demo.inject_attack('equivocation', demo.leader_id)
        for _ in range(25):
            demo.step()
        self.assertIn(original, demo.qcs)
        self.assertTrue(all(block_id not in demo.qcs for block_id in rivals))

    def test_duplicate_identity_evidence_cannot_form_qc(self):
        demo = HotStuffDemo()
        demo.step()
        for voter in (1, 2):
            self.assertTrue(demo.vote((voter, 'B1')))
        demo.votes['B1'] = [1, 1, 2]
        self.assertFalse(demo.form_qc('B1'))
        self.assertNotIn('B1', demo.qcs)

    def test_all_first_delivery_orders_preserve_quorum_safety(self):
        for choices in product((0, 1), repeat=4):
            with self.subTest(first_seen=choices):
                demo = HotStuffDemo()
                first, second = demo.inject_attack('equivocation', demo.leader_id)
                proposals = (first, second)
                demo.events.clear()
                for node_id, choice in enumerate(choices, start=1):
                    demo.events.append(('vote', (node_id, proposals[choice])))
                for node_id, choice in enumerate(choices, start=1):
                    demo.events.append(('vote', (node_id, proposals[1 - choice])))
                for _ in range(8):
                    demo.step()
                self.assertLessEqual(sum(block_id in demo.qcs for block_id in proposals), 1)
                self.assertTrue(set(demo.votes[first]).isdisjoint(demo.votes[second]))
                for node in demo.nodes:
                    self.assertEqual(node.committed_blocks, ['B0'])

    def test_wrong_view_and_duplicate_qcs_do_not_change_replica_state(self):
        demo = HotStuffDemo()
        demo.step()
        block = demo.blocks['B1']
        for node in demo.nodes:
            high, locked = node.high_qc, node.locked_qc
            self.assertEqual(node.receive_qc(QC(block.id, block.view + 1, (1, 2, 3))), [])
            self.assertEqual(node.receive_qc(QC(block.id, block.view, (1, 1, 2))), [])
            self.assertEqual((node.high_qc, node.locked_qc), (high, locked))
            self.assertEqual(node.committed_blocks, ['B0'])

    def test_malformed_parent_qc_cannot_gain_votes_or_certificate(self):
        demo = HotStuffDemo()
        demo.step()
        demo.blocks['B1'].qc = 'forged certificate'
        for node in demo.nodes:
            self.assertFalse(demo.vote((node.id, 'B1')))
            self.assertEqual(node.last_voted_view, 0)
        self.assertFalse(demo.form_qc('B1'))
        self.assertEqual(demo.votes['B1'], set())
        self.assertNotIn('B1', demo.qcs)

    def test_equivocation_never_certifies_both_forks(self):
        demo = HotStuffDemo()
        first, second = demo.inject_attack('equivocation', demo.leader_id)
        for _ in range(60):
            demo.step()
        certified = [block_id for block_id in (first, second) if block_id in demo.qcs]
        self.assertLessEqual(len(certified), 1)
        for node in demo.nodes:
            self.assertLessEqual(len(set((first, second)) & set(node.committed_blocks)), 1)
        self.assertTrue(all(node.committed_blocks == demo.nodes[0].committed_blocks
                            for node in demo.nodes))

    def test_invalid_qc_event_does_not_change_locks(self):
        demo = HotStuffDemo()
        demo.inject_attack('invalid_qc', demo.leader_id)
        demo.step()  # Normal proposal.
        demo.step()  # Invalid QC event.
        self.assertEqual(list(demo.qcs), ['B0'])
        self.assertTrue(all(node.locked_qc.block_id == 'B0' for node in demo.nodes))
        self.assertTrue(all(node.committed_blocks == ['B0'] for node in demo.nodes))
