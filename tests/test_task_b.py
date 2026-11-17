"""Isolated Task B checks: fixture commitment is NOT a consensus implementation."""
import unittest
from backend.hotstuff import HotStuffDemo
from tests.helpers import signed_transaction, submit_signed
from backend.models import Transaction, Block
from backend.blockchain import StateMachine

class TaskBTests(unittest.TestCase):
    def test_admission_does_not_execute(self):
        d=HotStuffDemo();tx=submit_signed(d, 'Alice','Bob',10)
        self.assertIn(tx.id,d.mempool)
        self.assertTrue(all(n.machine.accounts['Alice']==100 for n in d.nodes))

    def test_pool_excludes_only_selected_ancestry(self):
        d=HotStuffDemo()
        txs=[submit_signed(d, 'Alice','Bob',1) for _ in range(7)]
        parent=d.blocks['B0'];first=d.select_transactions(parent)
        self.assertEqual([t.id for t in first],[t.id for t in txs[:5]])
        b=Block('X',parent.id,1,1,first,d.qcs['B0']);d.blocks[b.id]=b
        for n in d.nodes:n.blocks[b.id]=b
        self.assertEqual([t.id for t in d.select_transactions(b)],[t.id for t in txs[5:]])
        self.assertEqual([t.id for t in d.select_transactions(parent)],[t.id for t in txs[:5]])
        self.assertEqual(len(d.mempool),7)

    def test_insufficient_balance_and_same_id_retry(self):
        m=StateMachine();tx=signed_transaction('Alice','Bob',80)
        a=m.apply(tx);b=m.apply(signed_transaction('Alice','Charlie',80,1))
        self.assertEqual(a['status'],'committed');self.assertEqual(b['status'],'rejected')
        self.assertEqual(m.apply(tx),a)
        self.assertEqual(m.accounts,{'Alice':20,'Bob':180,'Charlie':100})

    def test_committed_execution_and_cleanup(self):
        d=HotStuffDemo();tx=submit_signed(d, 'Alice','Bob',10)
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

    def test_mixed_committed_and_uncommitted_ids_reject_before_any_execution(self):
        d = HotStuffDemo()
        node = d.nodes[0]
        tx = submit_signed(d, 'Alice', 'Bob', 10)
        node.blocks['Committed'] = Block('Committed', 'B0', 1, 1, [tx], d.qcs['B0'])
        node.committed_blocks.append('Committed')
        with self.assertRaises(ValueError):
            node.execute_committed(['Committed', 'Uncommitted'])
        self.assertEqual(node.machine.accounts['Alice'], 100)
        self.assertEqual(node.machine.receipts, {})

    def test_dependent_transfers_follow_block_and_payload_order(self):
        for limit in (1, 5):
            with self.subTest(limit=limit):
                d = HotStuffDemo()
                d.configure_batch(limit)
                submit_signed(d, 'Alice', 'Bob', 100)
                second = submit_signed(d, 'Bob', 'Charlie', 200)
                for _ in range(100):
                    if not d.mempool:
                        break
                    d.step()
                else:
                    self.fail('Dependent transfers did not commit')
                for node in d.nodes:
                    self.assertEqual(node.machine.accounts, {'Alice': 0, 'Bob': 0, 'Charlie': 300})
                    self.assertEqual(node.machine.receipts[second.id]['status'], 'committed')

    def test_out_of_order_or_skipped_commits_reject_before_execution(self):
        for requested in (['Second', 'First'], ['Second']):
            with self.subTest(requested=requested):
                d = HotStuffDemo()
                node = d.nodes[0]
                first = signed_transaction('Alice', 'Bob', 100)
                second = signed_transaction('Bob', 'Charlie', 200)
                node.blocks['First'] = Block('First', 'B0', 1, 1, [first], d.qcs['B0'])
                node.blocks['Second'] = Block('Second', 'First', 2, 2, [second])
                node.committed_blocks.extend(['First', 'Second'])
                with self.assertRaises(ValueError):
                    node.execute_committed(requested)
                self.assertEqual(node.machine.accounts, {'Alice': 100, 'Bob': 100, 'Charlie': 100})
                self.assertEqual(node.machine.receipts, {})
                self.assertEqual(node.machine.execution_receipts, {})
                node.execute_committed(['First', 'Second'])
                self.assertEqual(node.machine.accounts, {'Alice': 0, 'Bob': 0, 'Charlie': 300})
