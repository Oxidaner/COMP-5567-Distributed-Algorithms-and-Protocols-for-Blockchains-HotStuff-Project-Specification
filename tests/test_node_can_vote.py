import unittest
from copy import deepcopy

from backend.hotstuff import HotStuffDemo
from backend.models import Block, QC


class NodeCanVoteTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()
        self.node = self.demo.nodes[0]

        # The node is in view 4 and has not voted in this view.
        self.node.view = 4
        self.node.last_voted_view = 0

        # Locked branch: B0 <- L1 <- L2
        self.qc_l1 = QC("L1", 1, (1, 2, 3))
        self.qc_l2 = QC("L2", 2, (1, 2, 3))
        self.node.blocks["L1"] = Block(
            "L1", "B0", 1, 1, qc=self.demo.qcs["B0"]
        )
        self.node.blocks["L2"] = Block(
            "L2", "L1", 2, 2, qc=self.qc_l1
        )
        self.node.locked_qc = self.qc_l2

        # An alternative branch, with certificates from different views.
        self.qc_f1 = QC("F1", 1, (1, 2, 3))
        self.qc_f2 = QC("F2", 2, (1, 2, 3))
        self.qc_f3 = QC("F3", 3, (1, 2, 3))

        self.node.blocks["F1"] = Block(
            "F1", "B0", 1, 1, qc=self.demo.qcs["B0"]
        )
        self.node.blocks["F2"] = Block(
            "F2", "F1", 2, 2, qc=self.qc_f1
        )
        self.node.blocks["F3"] = Block(
            "F3", "F2", 3, 3, qc=self.qc_f2
        )

        # A normal proposal extending the locked block.
        self.proposal = Block(
            "P4", "L2", 4, 4, qc=self.qc_l2
        )

    def test_extending_locked_branch_is_allowed(self):
        self.assertTrue(self.node.can_vote(self.proposal))

    def test_crashed_node_cannot_vote(self):
        self.node.crashed = True
        self.assertFalse(self.node.can_vote(self.proposal))

    def test_withholding_node_cannot_vote(self):
        self.node.withhold_vote = True
        self.assertFalse(self.node.can_vote(self.proposal))

    def test_old_view_is_rejected(self):
        self.proposal.view = 3
        self.assertFalse(self.node.can_vote(self.proposal))

    def test_future_view_is_rejected(self):
        self.proposal.view = 5
        self.assertFalse(self.node.can_vote(self.proposal))

    def test_already_voted_in_current_view(self):
        self.node.last_voted_view = 4
        self.assertFalse(self.node.can_vote(self.proposal))

    def test_higher_recorded_vote_blocks_older_vote(self):
        self.node.last_voted_view = 5
        self.assertFalse(self.node.can_vote(self.proposal))

    def test_vote_in_previous_view_does_not_block_current_view(self):
        self.node.last_voted_view = 3
        self.assertTrue(self.node.can_vote(self.proposal))

    def test_conflicting_branch_with_older_qc_is_rejected(self):
        proposal = Block("P4", "F1", 4, 4, qc=self.qc_f1)
        self.assertFalse(self.node.can_vote(proposal))

    def test_conflicting_branch_with_equal_qc_is_rejected(self):
        proposal = Block("P4", "F2", 4, 4, qc=self.qc_f2)
        self.assertFalse(self.node.can_vote(proposal))

    def test_conflicting_branch_with_newer_qc_is_allowed(self):
        proposal = Block("P4", "F3", 4, 4, qc=self.qc_f3)
        self.assertTrue(self.node.can_vote(proposal))

    def test_check_does_not_modify_node_state(self):
        machine_before = self.node.machine
        machine_state_before = deepcopy(machine_before.__dict__)
        before = deepcopy({
            key: value
            for key, value in self.node.__dict__.items()
            if key != "machine"
        })
        proposal_before = deepcopy(self.proposal)

        self.assertTrue(self.node.can_vote(self.proposal))
        self.assertTrue(self.node.can_vote(self.proposal))

        after = {
            key: value
            for key, value in self.node.__dict__.items()
            if key != "machine"
        }

        self.assertEqual(after, before)
        self.assertIs(self.node.machine, machine_before)
        self.assertEqual(
            self.node.machine.__dict__,
            machine_state_before
        )
        self.assertEqual(self.proposal, proposal_before)


if __name__ == "__main__":
    unittest.main()
