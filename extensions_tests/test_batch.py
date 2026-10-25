import unittest
from backend.hotstuff import HotStuffDemo

class BatchExtensionTests(unittest.TestCase):
    def test_limits(self):
        for limit in [1,2,5]:
            d=HotStuffDemo();d.configure_batch(limit)
            for _ in range(7):d.submit('Alice','Bob',1)
            self.assertEqual(len(d.select_transactions(d.blocks['B0'])),limit)

    def test_reject_invalid(self):
        d=HotStuffDemo()
        for invalid in [0,-1,True,1.5,'2']:
            with self.assertRaises(ValueError):d.configure_batch(invalid)
            self.assertEqual(d.max_txs_per_block,5)
