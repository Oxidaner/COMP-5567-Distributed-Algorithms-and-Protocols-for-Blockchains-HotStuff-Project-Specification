"""Task A tests use empty blocks and never require transaction TODOs."""
import unittest
from backend.hotstuff import HotStuffDemo
from backend.models import Block, QC

class TaskATests(unittest.TestCase):
    def test_empty_chain_commits(self):
        d=HotStuffDemo()
        for _ in range(100):
            d.step()
            if all(len(n.committed_blocks)>1 for n in d.nodes):break
        self.assertTrue(all(len(n.committed_blocks)>1 for n in d.nodes))
        for n in d.nodes:
            self.assertEqual(n.committed_blocks,d.nodes[0].committed_blocks)
            self.assertEqual(n.machine.accounts,{'Alice':100,'Bob':100,'Charlie':100})
        for q in d.qcs.values():self.assertGreaterEqual(len(set(q.voters)),3)

    def test_one_qc_does_not_commit_own_block(self):
        d=HotStuffDemo();n=d.nodes[0]
        n.blocks['B1']=Block('B1','B0',1,1,[],d.qcs['B0'])
        n.receive_qc(QC('B1',1,(1,2,3)))
        self.assertEqual(n.high_qc.block_id,'B1')
        self.assertEqual(n.committed_blocks,['B0'])

    def test_quorum_not_reached(self):
        d=HotStuffDemo()
        d.blocks['B1']=Block('B1','B0',1,1,[],d.qcs['B0'])
        d.votes['B1']={1,2}
        try:d.form_qc('B1')
        except (ValueError,RuntimeError) as exc:
            if isinstance(exc,NotImplementedError):raise
        self.assertNotIn('B1',d.qcs)
        self.assertTrue(all(n.committed_blocks==['B0'] for n in d.nodes))
