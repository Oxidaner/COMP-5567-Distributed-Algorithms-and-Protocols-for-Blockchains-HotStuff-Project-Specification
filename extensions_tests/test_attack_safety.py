"""A7 safety evidence for the lock/commit side of conflicting proposals."""
import unittest

from backend.hotstuff import HotStuffDemo


class AttackCommitSafetyTests(unittest.TestCase):
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
