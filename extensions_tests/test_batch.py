import unittest
from backend.hotstuff import HotStuffDemo
from tests.helpers import submit_signed

class BatchExtensionTests(unittest.TestCase):
    def test_limits(self):
        for limit in [1,2,5]:
            d=HotStuffDemo();d.configure_batch(limit)
            for _ in range(7):submit_signed(d, 'Alice','Bob',1)
            self.assertEqual(len(d.select_transactions(d.blocks['B0'])),limit)

    def test_reject_invalid(self):
        d=HotStuffDemo()
        for invalid in [0,-1,True,1.5,'2']:
            with self.assertRaises(ValueError):d.configure_batch(invalid)
            self.assertEqual(d.max_txs_per_block,5)

    def test_limits_through_real_consensus_and_final_receipts(self):
        for limit in (1, 2, 5):
            with self.subTest(limit=limit):
                d = HotStuffDemo()
                d.configure_batch(limit)
                txs = [submit_signed(d, 'Alice', 'Bob', 1) for _ in range(7)]
                for _ in range(300):
                    if not d.mempool:
                        break
                    d.step()
                else:
                    self.fail('Transactions did not commit')
                self.assertTrue(all(len(b.transactions) <= limit for b in d.blocks.values()))
                for node in d.nodes:
                    self.assertEqual(node.machine.accounts, {'Alice': 93, 'Bob': 107, 'Charlie': 100})
                    self.assertTrue(all(node.machine.receipts[tx.id]['status'] == 'committed' for tx in txs))
