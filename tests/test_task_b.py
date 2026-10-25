"""Isolated Task B checks: fixture commitment is NOT a consensus implementation."""
import unittest
from backend.hotstuff import HotStuffDemo
from backend.models import Transaction, Block
from backend.blockchain import StateMachine

class TaskBTests(unittest.TestCase):
    def test_admission_does_not_execute(self):
        d=HotStuffDemo();tx=d.submit('Alice','Bob',10)
        self.assertIn(tx.id,d.mempool)
        self.assertTrue(all(n.machine.accounts['Alice']==100 for n in d.nodes))

    def test_pool_excludes_only_selected_ancestry(self):
        d=HotStuffDemo()
        txs=[d.submit('Alice','Bob',1) for _ in range(7)]
        parent=d.blocks['B0'];first=d.select_transactions(parent)
        self.assertEqual([t.id for t in first],[t.id for t in txs[:5]])
        b=Block('X',parent.id,1,1,first,d.qcs['B0']);d.blocks[b.id]=b
        for n in d.nodes:n.blocks[b.id]=b
        self.assertEqual([t.id for t in d.select_transactions(b)],[t.id for t in txs[5:]])
        self.assertEqual([t.id for t in d.select_transactions(parent)],[t.id for t in txs[:5]])
        self.assertEqual(len(d.mempool),7)

    def test_insufficient_balance_and_same_id_retry(self):
        m=StateMachine();tx=Transaction('T1','Alice','Bob',80)
        a=m.apply(tx);b=m.apply(Transaction('T2','Alice','Charlie',80))
        self.assertEqual(a['status'],'committed');self.assertEqual(b['status'],'rejected')
        self.assertEqual(m.apply(tx),a)
        self.assertEqual(m.accounts,{'Alice':20,'Bob':180,'Charlie':100})

    def test_committed_execution_and_cleanup(self):
        d=HotStuffDemo();tx=d.submit('Alice','Bob',10)
        b=Block('TBlock','B0',1,1,[tx],d.qcs['B0']);d.blocks[b.id]=b
        for n in d.nodes:
            n.blocks[b.id]=b
            n.committed_blocks.append(b.id)  # Test fixture bypasses Task A only.
            n.execute_committed([b.id]);n.execute_committed([b.id])
            self.assertEqual(n.machine.accounts['Alice'],90)
            self.assertIn(tx.id,n.machine.receipts)
        d.finalize_transactions([b.id]);d.finalize_transactions([b.id])
        self.assertNotIn(tx.id,d.mempool)

    def test_uncommitted_payload_not_executed(self):
        d=HotStuffDemo();n=d.nodes[0]
        n.blocks['X']=Block('X','B0',1,1,[Transaction('T','Alice','Bob',10)],d.qcs['B0'])
        try:n.execute_committed(['X'])
        except ValueError:pass
        self.assertEqual(n.machine.accounts['Alice'],100)
        self.assertFalse(n.machine.receipts)
