import unittest
from copy import deepcopy

from backend.hotstuff import HotStuffDemo
from backend.models import Block


class NodeExtendsTests(unittest.TestCase):
    def setUp(self):
        self.demo = HotStuffDemo()
        self.node = self.demo.nodes[0]

        # A known chain: B0 <- B1 <- B2
        self.node.blocks["B1"] = Block("B1", "B0", 1, 1)
        self.node.blocks["B2"] = Block("B2", "B1", 2, 2)

    def test_known_block_extends_itself(self):
        self.assertTrue(self.node.extends("B1", "B1"))

    def test_direct_parent(self):
        self.assertTrue(self.node.extends("B2", "B1"))

    def test_distant_ancestor(self):
        self.assertTrue(self.node.extends("B2", "B0"))

    def test_ancestor_does_not_extend_descendant(self):
        self.assertFalse(self.node.extends("B1", "B2"))

    def test_sibling_is_not_ancestor(self):
        self.node.blocks["F1"] = Block("F1", "B0", 1, 1)
        self.assertFalse(self.node.extends("B2", "F1"))

    def test_unknown_start(self):
        self.assertFalse(self.node.extends("MISSING", "B0"))

    def test_unknown_block_does_not_extend_itself(self):
        self.assertFalse(self.node.extends("MISSING", "MISSING"))

    def test_missing_parent_is_not_accepted(self):
        self.node.blocks["X"] = Block("X", "MISSING", 3, 3)
        self.assertFalse(self.node.extends("X", "MISSING"))
        self.assertFalse(self.node.extends("X", "B0"))

    def test_cycle_cannot_reach_unrelated_ancestor(self):
        self.node.blocks["X"] = Block("X", "Y", 3, 3)
        self.node.blocks["Y"] = Block("Y", "X", 4, 4)
        self.assertFalse(self.node.extends("X", "B0"))

    def test_query_does_not_modify_node_state(self):
        # Keep the original machine object and compare its contents separately.
        machine_before = self.node.machine

        before = deepcopy({
            key: value
            for key, value in self.node.__dict__.items()
            if key != "machine"
        })
        machine_state_before = deepcopy(self.node.machine.__dict__)

        self.node.extends("B2", "B0")
        self.node.extends("MISSING", "MISSING")

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

if __name__ == "__main__":
    unittest.main()
