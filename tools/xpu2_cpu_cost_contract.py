"""Evidence gates for sampled timing normalization and observer-effect comparison."""
import copy,csv,json,tempfile,unittest
from pathlib import Path
import xpu2_cpu_cost_probe as probe
from xpu2_cpu_cost_analyze import analyze
ROOT=Path(__file__).resolve().parents[1]
class Contract(unittest.TestCase):
 def test_weighted_active_lanes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'cpu.csv'
   p.write_text('thread,stage,calls,lanes,sampled_calls,sampled_lanes,exclusive_ns,errors,active,rate,seed,empty_pair_ns\n0,diffuse_sample,4,32,2,16,800,0,0,2,1,20\n1,diffuse_sample,4,16,2,8,800,0,0,2,1,20\n')
   r=probe.cost_rows(p)['diffuse_sample'];self.assertEqual(r['lanes'],48);self.assertAlmostEqual(r['ns_per_active_lane'],1600/24)
 def test_reject_overlap(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'cpu.csv';p.write_text('thread,stage,calls,lanes,sampled_calls,sampled_lanes,exclusive_ns,errors,active,rate,seed,empty_pair_ns\n0,diffuse_sample,4,32,2,16,800,1,0,2,1,20\n')
   with self.assertRaises(ValueError):probe.cost_rows(p)
 def fixture(self):
  cpu={'diffuse_sample':dict(calls=100,lanes=800,sampled_calls=50,sampled_lanes=400,exclusive_ns=12800,ns_per_active_lane=32.,estimated_total_seconds=.0000256)}
  rows=[]
  for label,rate,duration in [('reference',0,8.),('off_before',0,8.3),('sample64',64,8.4),('sample16',16,8.4),('off_after',0,8.3)]:
   rows.append(dict(fixture='diffuse',label=label,rate=rate,execution={'renderer_timings_seconds':{'Mcrt time':duration}},cpu=copy.deepcopy(cpu)))
  return {'status':'passed','runs':rows},json.loads((ROOT/'xpu2/exclusive-profile-20261019.json').read_text())
 def test_planning_cost_not_frame_time(self):
  r,b=self.fixture();a=analyze(r,b);v=a['bridge']
  self.assertAlmostEqual(v['sampler_queue_host_us_per_used_lane'],.54588,places=4)
  self.assertGreater(v['light_queue_host_us_per_used_lane'],28)
  self.assertFalse(a['fixtures']['diffuse']['stages']['diffuse_sample']['above_1_5us_in_both_samples'])
 def test_work_count_mismatch(self):
  r,b=self.fixture();next(x for x in r['runs'] if x['label']=='sample16')['cpu']['diffuse_sample']['lanes']+=1
  with self.assertRaises(ValueError):analyze(r,b)
 def test_incomplete(self):
  r,b=self.fixture();r['status']='incomplete'
  with self.assertRaises(ValueError):analyze(r,b)
if __name__=='__main__':unittest.main()
