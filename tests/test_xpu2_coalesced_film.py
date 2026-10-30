import unittest
import test_xpu2_fused_film as fixture
from xpu2.coalesced_film_evidence import validate_queue

class CoalescedFilmTests(unittest.TestCase):
 def profiles(self):
  p=fixture.FusedFilmTests().profile();p['max_slots']=9
  q=dict(submitted=4,returned=4,declined=0,batches=2,combined=1,max_jobs=3,max_slots=9,max_outstanding=4,during_service=2,exceptions=0)
  return q,p
 def test_combines_completed_native_work(self):
  q,p=self.profiles();self.assertEqual(validate_queue(q,p,'fast',4)['status'],'passed')
 def test_missing_return_rejected(self):
  q,p=self.profiles();q['returned']=3
  with self.assertRaises(ValueError):validate_queue(q,p,'fast',4)
 def test_overflow_cannot_be_called_full_gpu_validation(self):
  q,p=self.profiles();q['declined']=1
  with self.assertRaises(ValueError):validate_queue(q,p,'fast',4)
 def test_uncombined_work_is_not_coalescing(self):
  q,p=self.profiles();q.update(combined=0,max_jobs=1)
  with self.assertRaises(ValueError):validate_queue(q,p,'fast',4)
 def test_capacity_enforced(self):
  q,p=self.profiles();q['max_outstanding']=17
  with self.assertRaises(ValueError):validate_queue(q,p,'fast',4)
 def test_device_batch_accounting(self):
  q,p=self.profiles();q['batches']=3
  with self.assertRaises(ValueError):validate_queue(q,p,'fast',4)
 def test_single_caller_cannot_claim_combining(self):
  q,p=self.profiles()
  with self.assertRaises(ValueError):validate_queue(q,p,'fast',1)
  q.update(submitted=2,returned=2,combined=0,max_jobs=1)
  self.assertEqual(validate_queue(q,p,'fast',1)['status'],'passed')
