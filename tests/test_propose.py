import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.hotstuff import HotStuffDemo
from backend.models import Block, QC, Transaction


class ProposeTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()

        # Call propose directly, so remove the initial queued proposal.
        self.demo.events.clear()

    def make_proposal(self):
        before = set(self.demo.blocks)
        self.demo.propose(None)
        new_ids = set(self.demo.blocks) - before
        self.assertEqual(len(new_ids), 1)
        return self.demo.blocks[new_ids.pop()]

    def test_initial_proposal_fields(self):
        leader = self.demo.nodes[self.demo.leader_id - 1]
        block = self.make_proposal()

        self.assertEqual(block.view, self.demo.view)
        self.assertEqual(block.proposer, leader.id)
        self.assertEqual(block.parent_id, leader.high_qc.block_id)
        self.assertEqual(block.qc, leader.high_qc)
        self.assertEqual(block.transactions, [])

    def test_parent_selected_from_leader_high_qc(self):
        # A synthetic certified parent for isolated proposal testing.
        parent = Block(
            "P1", "B0", 1, 1, qc=self.demo.qcs["B0"]
        )
        parent_qc = QC("P1", 1, (1, 2, 3))

        self.demo.blocks[parent.id] = parent
        self.demo.qcs[parent.id] = parent_qc
        self.demo.view = 2

        for node in self.demo.nodes:
            node.blocks[parent.id] = parent
            node.view = 2

        leader = self.demo.nodes[self.demo.leader_id - 1]
        leader.high_qc = parent_qc

        block = self.make_proposal()

        self.assertEqual(block.parent_id, "P1")
        self.assertEqual(block.qc, parent_qc)
        self.assertEqual(block.view, 2)
        self.assertEqual(block.proposer, 2)

    def test_empty_pool_does_not_call_transaction_selection(self):
        with patch.object(
            self.demo,
            "select_transactions",
            side_effect=AssertionError(
                "Empty-pool proposals must not call Task B"
            )
        ) as select:
            block = self.make_proposal()

        select.assert_not_called()
        self.assertEqual(block.transactions, [])

    def test_nonempty_pool_calls_selection_with_parent(self):
        tx = Transaction("T1", "Alice", "Bob", 10)
        self.demo.transactions[tx.id] = tx
        self.demo.mempool.append(tx.id)
        parent = self.demo.blocks["B0"]

        with patch.object(
            self.demo,
            "select_transactions",
            return_value=[tx]
        ) as select:
            block = self.make_proposal()

        select.assert_called_once_with(parent)
        self.assertEqual(block.transactions, [tx])
        self.assertEqual(self.demo.mempool, ["T1"])

    def test_distributes_to_all_live_nodes(self):
        block = self.make_proposal()

        for node in self.demo.nodes:
            self.assertIn(block.id, node.blocks)
            self.assertEqual(node.blocks[block.id], block)

    def test_crashed_replica_receives_no_proposal_or_vote_event(self):
        crashed = self.demo.nodes[1]
        crashed.crashed = True
        block = self.make_proposal()

        self.assertNotIn(block.id, crashed.blocks)

        expected = [
            ("vote", (node.id, block.id))
            for node in self.demo.nodes
            if not node.crashed
        ]
        self.assertEqual(list(self.demo.events), expected)

    def test_queues_one_vote_event_per_live_node(self):
        block = self.make_proposal()

        expected = [
            ("vote", (node.id, block.id))
            for node in self.demo.nodes
        ]
        self.assertEqual(list(self.demo.events), expected)

    def test_proposal_does_not_vote_certify_commit_or_execute(self):
        qcs_before = deepcopy(self.demo.qcs)
        states_before = [
            (
                deepcopy(node.machine.__dict__),
                list(node.committed_blocks),
                node.last_voted_view,
                node.last_voted_block,
                node.high_qc,
                node.locked_qc,
            )
            for node in self.demo.nodes
        ]

        block = self.make_proposal()

        self.assertEqual(self.demo.votes[block.id], set())
        self.assertEqual(self.demo.qcs, qcs_before)
        self.assertNotIn(block.id, self.demo.qcs)

        states_after = [
            (
                deepcopy(node.machine.__dict__),
                list(node.committed_blocks),
                node.last_voted_view,
                node.last_voted_block,
                node.high_qc,
                node.locked_qc,
            )
            for node in self.demo.nodes
        ]
        self.assertEqual(states_after, states_before)

    def test_existing_block_id_is_not_overwritten(self):
        # B0 and B2 exist, so len(blocks) points to an occupied ID.
        existing = Block("B2", "B0", 1, 1)
        self.demo.blocks["B2"] = existing

        block = self.make_proposal()

        self.assertNotEqual(block.id, "B2")
        self.assertIs(self.demo.blocks["B2"], existing)

    def test_unknown_high_qc_parent_is_rejected(self):
        leader = self.demo.nodes[self.demo.leader_id - 1]
        leader.high_qc = QC("MISSING", 1, (1, 2, 3))
        blocks_before = deepcopy(self.demo.blocks)

        with self.assertRaises(ValueError):
            self.demo.propose(None)

        self.assertEqual(self.demo.blocks, blocks_before)
        self.assertEqual(self.demo.votes, {})
        self.assertEqual(list(self.demo.events), [])

    def test_crashed_leader_schedules_timeout_without_proposal(self):
        leader = self.demo.nodes[self.demo.leader_id - 1]
        leader.crashed = True
        blocks_before = deepcopy(self.demo.blocks)

        self.demo.propose(None)

        self.assertEqual(self.demo.blocks, blocks_before)
        self.assertEqual(self.demo.votes, {})
        self.assertEqual(
            list(self.demo.events),
            [("timeout", self.demo.TIMEOUT_TICKS)]
        )

    def test_crashed_leader_does_not_duplicate_timeout(self):
        leader = self.demo.nodes[self.demo.leader_id - 1]
        leader.crashed = True

        self.demo.propose(None)
        self.demo.propose(None)

        timeouts = [
            event for event in self.demo.events
            if event[0] == "timeout"
        ]
        self.assertEqual(len(timeouts), 1)


if __name__ == "__main__":
    unittest.main()
