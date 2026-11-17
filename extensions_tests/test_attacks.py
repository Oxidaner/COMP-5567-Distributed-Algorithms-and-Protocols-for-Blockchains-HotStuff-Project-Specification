import unittest
from unittest.mock import patch

from backend.hotstuff import HotStuffDemo


class AttackTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()

    def run_until_view_changes(self, initial_view, limit=40):
        for _ in range(limit):
            if self.demo.view != initial_view:
                return
            self.demo.step()
        self.fail("The experiment did not leave its initial view")

    def test_equivocation_creates_conflicting_proposals(self):
        initial_view = self.demo.view
        leader_id = self.demo.leader_id

        first_id, second_id = self.demo.inject_attack(
            "equivocation", leader_id
        )
        first = self.demo.blocks[first_id]
        second = self.demo.blocks[second_id]

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(first.parent_id, second.parent_id)
        self.assertEqual(first.view, initial_view)
        self.assertEqual(second.view, initial_view)
        self.assertEqual(first.proposer, leader_id)
        self.assertEqual(second.proposer, leader_id)

        for block_id in (first_id, second_id):
            for node in self.demo.nodes:
                self.assertIn(block_id, node.blocks)
                self.assertIn(
                    ("vote", (node.id, block_id)),
                    self.demo.events
                )

        # Injection itself must not manufacture votes or QCs.
        self.assertEqual(self.demo.votes[first_id], set())
        self.assertEqual(self.demo.votes[second_id], set())
        self.assertNotIn(first_id, self.demo.qcs)
        self.assertNotIn(second_id, self.demo.qcs)

    def test_default_delivery_rejects_second_conflicting_vote(self):
        initial_view = self.demo.view
        first_id, second_id = self.demo.inject_attack(
            "equivocation", self.demo.leader_id
        )

        # Observe the real vote function; do not replace its behavior.
        with patch.object(
            self.demo, "vote", wraps=self.demo.vote
        ) as observed_vote:
            self.run_until_view_changes(initial_view)

            for node in self.demo.nodes:
                observed_vote.assert_any_call((node.id, first_id))
                observed_vote.assert_any_call((node.id, second_id))

        self.assertEqual(
            self.demo.votes[first_id], {1, 2, 3, 4}
        )
        self.assertEqual(self.demo.votes[second_id], set())
        self.assertIn(first_id, self.demo.qcs)
        self.assertNotIn(second_id, self.demo.qcs)

    def test_split_first_delivery_cannot_create_two_qcs(self):
        first_id, second_id = self.demo.inject_attack(
            "equivocation", self.demo.leader_id
        )

        # Only change delivery order.
        # N1/N2 see the first proposal first.
        # N3/N4 see the second proposal first.
        self.demo.events.clear()
        deliveries = [
            (1, first_id), (2, first_id),
            (3, second_id), (4, second_id),
            (1, second_id), (2, second_id),
            (3, first_id), (4, first_id),
        ]

        for delivery in deliveries:
            self.demo.events.append(("vote", delivery))

        # Execute exactly the eight injected deliveries.
        for _ in deliveries:
            self.demo.step()

        self.assertEqual(self.demo.votes[first_id], {1, 2})
        self.assertEqual(self.demo.votes[second_id], {3, 4})
        self.assertTrue(
            self.demo.votes[first_id].isdisjoint(
                self.demo.votes[second_id]
            )
        )
        self.assertNotIn(first_id, self.demo.qcs)
        self.assertNotIn(second_id, self.demo.qcs)

        qc_events = [
            event for event in self.demo.events
            if event[0] == "qc"
        ]
        self.assertEqual(qc_events, [])

        for node in self.demo.nodes:
            self.assertEqual(node.committed_blocks, ["B0"])

    def test_progress_after_attack_has_no_conflicting_commits(self):
        initial_view = self.demo.view
        leader_id = self.demo.leader_id
        first_id, second_id = self.demo.inject_attack(
            "equivocation", leader_id
        )

        self.run_until_view_changes(initial_view)

        # Continue through the actual consensus path.
        for _ in range(100):
            self.demo.step()

        honest_nodes = [
            node for node in self.demo.nodes
            if node.id != leader_id
        ]
        reference = honest_nodes[0].committed_blocks

        # Ensure the check is not passing merely because nothing committed.
        self.assertIn(first_id, reference)

        for node in honest_nodes:
            self.assertEqual(node.committed_blocks, reference)
            self.assertNotIn(second_id, node.committed_blocks)

    def test_duplicate_injection_reaches_vote_validation(self):
        initial_view = self.demo.view

        # Process the initial proposal, leaving its vote events queued.
        self.demo.step()
        block_id = self.demo.inject_attack("duplicate_vote", 2)

        queued = list(self.demo.events)
        self.assertEqual(
            queued.count(("vote", (2, block_id))),
            3
        )

        with patch.object(
            self.demo, "vote", wraps=self.demo.vote
        ) as observed_vote:
            self.run_until_view_changes(initial_view)

            node_two_calls = [
                call for call in observed_vote.call_args_list
                if call.args == ((2, block_id),)
            ]
            self.assertEqual(len(node_two_calls), 3)

        # Three requests from N2 still represent one distinct voter.
        self.assertEqual(
            self.demo.votes[block_id], {1, 2, 3, 4}
        )
        self.assertEqual(
            self.demo.qcs[block_id].voters.count(2),
            1
        )

    def test_duplicate_injection_cannot_turn_two_voters_into_quorum(self):
        self.demo.nodes[2].withhold_vote = True
        self.demo.nodes[3].withhold_vote = True

        self.demo.step()
        block_id = self.demo.inject_attack("duplicate_vote", 2)

        # Four normal vote events plus two injected duplicates.
        for _ in range(6):
            self.demo.step()

        self.assertEqual(self.demo.votes[block_id], {1, 2})
        self.assertNotIn(block_id, self.demo.qcs)
        self.assertNotIn(("qc", block_id), self.demo.events)
        self.assertEqual(self.demo.QUORUM, 3)

    def test_nonleader_cannot_inject_leader_equivocation(self):
        with self.assertRaises(ValueError):
            self.demo.inject_attack("equivocation", 2)

        self.assertEqual(set(self.demo.blocks), {"B0"})

    def test_crashed_leader_cannot_inject_equivocation(self):
        self.demo.nodes[0].crashed = True

        with self.assertRaises(ValueError):
            self.demo.inject_attack("equivocation", 1)

        self.assertEqual(set(self.demo.blocks), {"B0"})


if __name__ == "__main__":
    unittest.main()
