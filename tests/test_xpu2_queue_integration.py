import json
import unittest
from xpu2.queue_integration import verify

class QueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.counts=dict(calls=2,submitted=1,delivered=1,cpu_batches=1,queue_full=0,timeouts=0,late_discarded=0,
                         worker_failures=0,worker_batches=1,max_batch_samples=8,max_queue=1,
                         cpu_completed_while_gpu_pending=1,kernel_window_cpu_observations=1,kernel_microseconds=4)
        self.delivery={'delivered_id':1,'samples':8}
    def log(self,counts=None,deliveries=None):
        return '\n'.join(json.dumps(x) for x in (([self.delivery] if deliveries is None else deliveries)+[counts or self.counts]))
    def test_unique_publication_and_samples(self):
        r=verify(self.log(),8)
        self.assertTrue(r['passed']);self.assertEqual(r['unique_deliveries'],1)
        with self.assertRaises(ValueError):verify(self.log(),7)
    def test_duplicates_missing_or_invalid_ids(self):
        for deliveries in ([],[self.delivery,self.delivery],[dict(self.delivery,delivered_id=2)],[dict(self.delivery,samples=9)]):
            with self.assertRaises(ValueError):verify(self.log(deliveries=deliveries),8)
    def test_missing_or_incomplete_request_accounting(self):
        for field,value in (('calls',3),('submitted',2),('timeouts',1),('late_discarded',1),('worker_failures',1),('max_queue',65),('max_batch_samples',513),('worker_batches',2)):
            with self.assertRaises(ValueError):verify(self.log(dict(self.counts,**{field:value})),8)
    def test_zero_capacity_requires_no_gpu_publication(self):
        c={k:0 for k in self.counts};c.update(calls=4,queue_full=4)
        self.assertTrue(verify(self.log(c,[]),0,full=True)['passed'])
        with self.assertRaises(ValueError):verify(self.log(c,[]),0)
        with self.assertRaises(ValueError):verify(self.log(),8,full=True)
    def test_no_invented_overlap_requirement(self):
        c=dict(self.counts,cpu_completed_while_gpu_pending=0,kernel_window_cpu_observations=0)
        self.assertEqual(verify(self.log(c),8)['kernel_window_cpu_observations'],0)
    def test_bad_counter_types_and_absent_summary(self):
        for value in (-1,True,1.5):
            with self.assertRaises(ValueError):verify(self.log(dict(self.counts,calls=value)),8)
        with self.assertRaises(ValueError):verify('{}',0)

if __name__=='__main__':unittest.main()
