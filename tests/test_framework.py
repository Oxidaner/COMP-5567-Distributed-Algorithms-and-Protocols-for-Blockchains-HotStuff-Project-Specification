"""These checks pass before TODOs are completed; they do not award task marks."""
import unittest
from backend.hotstuff import HotStuffDemo

class FrameworkTests(unittest.TestCase):
    def test_initial_snapshot(self):
        d=HotStuffDemo();s=d.snapshot()
        self.assertEqual(s['quorum'],3)
        self.assertEqual(len(s['nodes']),4)
        self.assertEqual(s['committed_chain'],['B0'])
        self.assertEqual(s['accounts'],{'Alice':100,'Bob':100,'Charlie':100})

    def test_missing_event_can_be_retried(self):
        d=HotStuffDemo()
        def incomplete(_):
            d.blocks.clear()
            raise NotImplementedError('test incomplete action')
        d.propose=incomplete
        with self.assertRaises(NotImplementedError):d.step()
        self.assertIn('B0',d.blocks)
        self.assertEqual(d.steps,0)
        self.assertEqual(list(d.events),[('propose',None)])
        self.assertFalse(d.running)

    def test_reset_framework(self):
        d=HotStuffDemo();d.crash_leader();d.set_byzantine(4)
        d.max_txs_per_block=2;d.reset()
        self.assertFalse(any(n.crashed or n.withhold_vote for n in d.nodes))
        self.assertEqual(d.max_txs_per_block,5)
