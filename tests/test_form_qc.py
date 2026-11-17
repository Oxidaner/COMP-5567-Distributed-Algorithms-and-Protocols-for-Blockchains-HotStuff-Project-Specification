import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.hotstuff import HotStuffDemo


class FormQCTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()
        self.demo.events.clear()
        self.demo.propose(None)

        self.block = next(
            block for block in self.demo.blocks.values()
            if block.id != "B0"
        )
        self.demo.events.clear()

    def cast_votes(self, node_ids):
        for node_id in node_ids:
            self.assertTrue(
                self.demo.vote((node_id, self.block.id))
            )

        # Invoke form_qc directly instead of processing queued events.
        self.demo.events.clear()

    def assert_no_qc_created(self, block_id):
        qcs_before = deepcopy(self.demo.qcs)
        events_before = list(self.demo.events)

        with patch.object(self.demo, "dispatch_qc") as dispatch:
            self.assertFalse(self.demo.form_qc(block_id))
            dispatch.assert_not_called()

        self.assertEqual(self.demo.qcs, qcs_before)
        self.assertEqual(list(self.demo.events), events_before)

    def test_no_votes_cannot_form_qc(self):
        self.assert_no_qc_created(self.block.id)

    def test_two_votes_cannot_form_qc(self):
        self.cast_votes((1, 2))
        self.assert_no_qc_created(self.block.id)

    def test_three_valid_votes_form_and_dispatch_qc(self):
        self.cast_votes((1, 2, 3))

        def check_registration(qc):
            # The QC must already be registered when dispatch starts.
            self.assertEqual(self.demo.qcs.get(self.block.id), qc)

        with patch.object(
            self.demo,
            "dispatch_qc",
            side_effect=check_registration
        ) as dispatch:
            self.assertTrue(self.demo.form_qc(self.block.id))

            qc = self.demo.qcs[self.block.id]
            self.assertEqual(qc.block_id, self.block.id)
            self.assertEqual(qc.view, self.block.view)
            self.assertEqual(qc.voters, (1, 2, 3))
            dispatch.assert_called_once_with(qc)

        self.assertEqual(
            list(self.demo.events),
            [("next_view", "QC")]
        )

    def test_four_valid_votes_are_supported(self):
        self.cast_votes((1, 2, 3, 4))

        with patch.object(self.demo, "dispatch_qc"):
            self.assertTrue(self.demo.form_qc(self.block.id))

        self.assertEqual(
            self.demo.qcs[self.block.id].voters,
            (1, 2, 3, 4)
        )

    def test_unknown_block_is_rejected(self):
        self.assert_no_qc_created("MISSING")

    def test_stale_view_is_rejected(self):
        self.cast_votes((1, 2, 3))
        self.demo.view = 2
        self.assert_no_qc_created(self.block.id)

    def test_voter_without_matching_history_is_not_counted(self):
        self.cast_votes((1, 2))

        # A set entry alone is not proof that node 3 voted.
        self.demo.votes[self.block.id].add(3)
        self.assert_no_qc_created(self.block.id)

    def test_wrong_vote_view_is_not_counted(self):
        self.cast_votes((1, 2, 3))
        self.demo.nodes[2].last_voted_view = 0
        self.assert_no_qc_created(self.block.id)

    def test_wrong_vote_block_is_not_counted(self):
        self.cast_votes((1, 2, 3))
        self.demo.nodes[2].last_voted_block = "OTHER"
        self.assert_no_qc_created(self.block.id)

    def test_invalid_voter_ids_cannot_make_quorum(self):
        self.cast_votes((1, 2))
        self.demo.votes[self.block.id].update({0, 5, -1, "3"})
        self.assert_no_qc_created(self.block.id)

    def test_invalid_extra_ids_are_excluded_from_certificate(self):
        self.cast_votes((1, 2, 3))
        self.demo.votes[self.block.id].update({0, 5, "4"})

        with patch.object(self.demo, "dispatch_qc"):
            self.assertTrue(self.demo.form_qc(self.block.id))

        self.assertEqual(
            self.demo.qcs[self.block.id].voters,
            (1, 2, 3)
        )

    def test_duplicate_vote_cannot_make_quorum(self):
        self.cast_votes((1, 2))
        self.assertFalse(self.demo.vote((1, self.block.id)))

        self.assertEqual(self.demo.votes[self.block.id], {1, 2})
        self.assert_no_qc_created(self.block.id)

    def test_existing_qc_is_not_dispatched_twice(self):
        self.cast_votes((1, 2, 3))

        with patch.object(self.demo, "dispatch_qc") as dispatch:
            self.assertTrue(self.demo.form_qc(self.block.id))
            original_qc = self.demo.qcs[self.block.id]

            self.assertFalse(self.demo.form_qc(self.block.id))

            dispatch.assert_called_once_with(original_qc)
            self.assertEqual(
                self.demo.qcs[self.block.id],
                original_qc
            )

        self.assertEqual(
            list(self.demo.events).count(("next_view", "QC")),
            1
        )

    def test_real_dispatch_first_qc_does_not_commit_its_block(self):
        self.cast_votes((1, 2, 3))

        committed_before = [
            list(node.committed_blocks)
            for node in self.demo.nodes
        ]
        machines_before = deepcopy([
            node.machine.__dict__
            for node in self.demo.nodes
        ])

        # Use the real dispatch_qc and receive_qc path here.
        self.assertTrue(self.demo.form_qc(self.block.id))

        qc = self.demo.qcs[self.block.id]

        for index, node in enumerate(self.demo.nodes):
            self.assertEqual(node.high_qc, qc)
            self.assertEqual(
                node.committed_blocks,
                committed_before[index]
            )
            self.assertNotIn(
                self.block.id,
                node.committed_blocks
            )

        self.assertEqual(
            [node.machine.__dict__ for node in self.demo.nodes],
            machines_before
        )


if __name__ == "__main__":
    unittest.main()
