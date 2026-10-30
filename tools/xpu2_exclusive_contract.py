"""Reject invalid exclusive-profile evidence without launching a renderer."""
import csv
import tempfile
import unittest
from pathlib import Path
from xpu2_exclusive_analyze import analyze

class ExclusiveEvidence(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
  self.rows=[dict(thread=t,stage=stage,exclusive_ns=ns,calls=1,covered_ns=covered,depth=0,errors=0,frame_ns=1000000)
   for t,covered,stages in [(0,300000,[("packing",100000),("upload_api",200000)]),(1,500000,[("native_shading",400000),("wait",100000)])]
   for stage,ns in stages]
  self.gpu=[dict(thread=0,track=0,upload_ms=.1,kernel_ms=.2,readback_ms=.3,trips=1)]
  self.clock=[dict(clock="invariant_tsc",ns_per_tick=.3,frame_ns=1000000,steady_frame_ns=1000000)]
  self.profiles={"flight":{"retired":1},"light":{"batches":0}}
 def tearDown(self):self.temp.cleanup()
 def write(self):
  for name,rows in [("exclusive.csv",self.rows),("exclusive.csv.gpu.csv",self.gpu),("exclusive.csv.clock.csv",self.clock)]:
   with (self.folder/name).open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 def run_analysis(self):self.write();return analyze(self.folder,self.profiles)
 def test_exclusive_partition_and_independent_gpu(self):
  r=self.run_analysis()
  self.assertAlmostEqual(r["host_threads"][0]["covered_seconds"],.0003)
  self.assertAlmostEqual(r["gpu_service_seconds_summed_across_streams"]["kernel"],.0002)
  self.assertEqual(r["host_threads"][1]["role"],"native_worker")
  self.assertAlmostEqual(r["pipelines"]["sampler_queue"]["host_plumbing_us_per_trip"],300)
 def test_overlapping_scope_totals_rejected(self):
  self.rows[0]["exclusive_ns"]+=1000
  with self.assertRaisesRegex(ValueError,"partition"):self.run_analysis()
 def test_unfinished_scope_rejected(self):
  self.rows[0]["depth"]=1
  with self.assertRaisesRegex(ValueError,"Unbalanced"):self.run_analysis()
 def test_clock_drift_rejected(self):
  self.clock[0]["steady_frame_ns"]=1010000
  with self.assertRaisesRegex(ValueError,"clock drift"):self.run_analysis()
 def test_missing_gpu_trip_rejected(self):
  self.profiles["flight"]["retired"]=2
  with self.assertRaisesRegex(ValueError,"Unaccounted GPU"):self.run_analysis()
 def test_duplicate_stage_rejected(self):
  self.rows.append(dict(self.rows[0]))
  with self.assertRaisesRegex(ValueError,"Duplicate"):self.run_analysis()
 def test_duplicate_gpu_stream_rejected(self):
  self.gpu.append(dict(self.gpu[0]))
  with self.assertRaisesRegex(ValueError,"more than one submitter"):self.run_analysis()

if __name__=="__main__":unittest.main()
