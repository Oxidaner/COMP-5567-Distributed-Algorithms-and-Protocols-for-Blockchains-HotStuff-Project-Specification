import unittest
from copy import deepcopy

from backend.hotstuff import HotStuffDemo
from backend.models import Block, QC


class VoteTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()

        # Create a normal proposal, then test voting directly.
        self.demo.events.clear()
        self.demo.propose(None)
        self.block = next(
            block for block in self.demo.blocks.values()
            if block.id != "B0"
        )
        self.demo.events.clear()

    def protected_state(self):
        # Compare data rather than StateMachine object identities.
        return deepcopy({
            "votes": self.demo.votes,
            "qcs": self.demo.qcs,
            "qc_scheduled": self.demo.qc_scheduled,
            "nodes": [
                {
                    "last_voted_view": node.last_voted_view,
                    "last_voted_block": node.last_voted_block,
                    "committed_blocks": node.committed_blocks,
                    "high_qc": node.high_qc,
                    "locked_qc": node.locked_qc,
                    "machine": node.machine.__dict__,
                }
                for node in self.demo.nodes
            ],
        })

    def assert_rejected_without_state_change(self, data):
        before = self.protected_state()
        self.assertFalse(self.demo.vote(data))
        self.assertEqual(self.protected_state(), before)

    def test_valid_vote_records_identity_and_history(self):
        self.assertTrue(self.demo.vote((1, self.block.id)))

        node = self.demo.nodes[0]
        self.assertEqual(self.demo.votes[self.block.id], {1})
        self.assertEqual(node.last_voted_view, self.block.view)
        self.assertEqual(node.last_voted_block, self.block.id)

    def test_duplicate_vote_is_rejected(self):
        self.assertTrue(self.demo.vote((1, self.block.id)))
        self.assert_rejected_without_state_change((1, self.block.id))
        self.assertEqual(self.demo.votes[self.block.id], {1})

    def test_same_view_conflicting_vote_is_rejected(self):
        self.assertTrue(self.demo.vote((1, self.block.id)))

        fork = Block(
            "FORK",
            self.block.parent_id,
            self.block.view,
            self.block.proposer,
            qc=self.block.qc,
        )
        self.demo.blocks[fork.id] = fork
        self.demo.votes[fork.id] = set()

        for node in self.demo.nodes:
            node.blocks[fork.id] = fork

        self.assert_rejected_without_state_change((1, fork.id))
        self.assertEqual(self.demo.votes[fork.id], set())

    def test_wrong_leader_is_rejected(self):
        self.block.proposer = 2
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_wrong_view_is_rejected(self):
        self.block.view = 2
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_unknown_block_is_rejected(self):
        self.assert_rejected_without_state_change((1, "MISSING"))

    def test_proposal_missing_from_local_node_is_rejected(self):
        del self.demo.nodes[0].blocks[self.block.id]
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_missing_parent_is_rejected(self):
        self.block.parent_id = "MISSING"
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_missing_parent_qc_is_rejected(self):
        self.block.qc = None
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_parent_qc_block_mismatch_is_rejected(self):
        self.block.qc = QC("OTHER", 0, (1, 2, 3))
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_parent_qc_view_mismatch_is_rejected(self):
        self.block.qc = QC("B0", 99, (1, 2, 3))
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_unregistered_parent_qc_is_rejected(self):
        # Structurally plausible, but different from the registered QC.
        self.block.qc = QC("B0", 0, (1, 2, 3))
        self.assert_rejected_without_state_change((1, self.block.id))

    def test_malformed_registered_qc_is_rejected(self):
        # Deliberately corrupt the registry to test structural validation.
        cases = [
            ("too_few_voters", (1, 2)),
            ("duplicate_voter", (1, 1, 2)),
            ("unknown_voter", (1, 2, 9)),
            ("boolean_voter", (True, 2, 3)),
        ]

        for label, voters in cases:
            with self.subTest(case=label):
                bad_qc = QC("B0", 0, voters)
                self.block.qc = bad_qc
                self.demo.qcs["B0"] = bad_qc
                self.assert_rejected_without_state_change(
                    (1, self.block.id)
                )

    def test_invalid_node_ids_are_rejected(self):
        for node_id in (0, 5, -1, True, "1"):
            with self.subTest(node_id=node_id):
                self.assert_rejected_without_state_change(
                    (node_id, self.block.id)
                )

    def test_crashed_replica_cannot_vote(self):
        self.demo.nodes[1].crashed = True
        self.assert_rejected_without_state_change((2, self.block.id))

    def test_withholding_replica_cannot_vote(self):
        self.demo.nodes[1].withhold_vote = True
        self.assert_rejected_without_state_change((2, self.block.id))

    def test_two_votes_do_not_schedule_qc(self):
        self.assertTrue(self.demo.vote((1, self.block.id)))
        self.assertTrue(self.demo.vote((2, self.block.id)))

        self.assertNotIn(("qc", self.block.id), self.demo.events)
        self.assertNotIn(self.block.id, self.demo.qc_scheduled)
        self.assertNotIn(self.block.id, self.demo.qcs)

    def test_third_vote_schedules_qc_exactly_once(self):
        for node_id in (1, 2, 3):
            self.assertTrue(self.demo.vote((node_id, self.block.id)))

        self.assertEqual(
            list(self.demo.events).count(("qc", self.block.id)),
            1
        )
        self.assertIn(self.block.id, self.demo.qc_scheduled)

        # Scheduling a QC is not the same as forming it.
        self.assertNotIn(self.block.id, self.demo.qcs)

    def test_fourth_vote_does_not_duplicate_qc_event(self):
        for node_id in (1, 2, 3, 4):
            self.assertTrue(self.demo.vote((node_id, self.block.id)))

        self.assertEqual(self.demo.votes[self.block.id], {1, 2, 3, 4})
        self.assertEqual(
            list(self.demo.events).count(("qc", self.block.id)),
            1
        )

    def test_voting_does_not_execute_or_commit(self):
        before = deepcopy([
            (node.machine.__dict__, node.committed_blocks)
            for node in self.demo.nodes
        ])
        qcs_before = deepcopy(self.demo.qcs)

        for node_id in (1, 2, 3):
            self.demo.vote((node_id, self.block.id))

        after = deepcopy([
            (node.machine.__dict__, node.committed_blocks)
            for node in self.demo.nodes
        ])

        self.assertEqual(after, before)
        self.assertEqual(self.demo.qcs, qcs_before)

    def test_insufficient_available_voters_schedule_one_timeout(self):
        self.demo.nodes[2].withhold_vote = True
        self.demo.nodes[3].withhold_vote = True

        self.assertTrue(self.demo.vote((1, self.block.id)))
        self.assertTrue(self.demo.vote((2, self.block.id)))

        timeouts = [
            event for event in self.demo.events
            if event[0] == "timeout"
        ]
        self.assertEqual(len(timeouts), 1)
        self.assertNotIn(("qc", self.block.id), self.demo.events)
        self.assertEqual(self.demo.QUORUM, 3)


if __name__ == "__main__":
    unittest.main()
