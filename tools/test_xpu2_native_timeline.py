import csv,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from xpu2_native_timeline_analyze import merge,duration,overlap,analyze
class Intervals(unittest.TestCase):
    def test_nested(self):
        self.assertEqual(duration([(0,10),(2,5),(8,12)]),12)
    def test_disjoint(self):
        self.assertEqual(duration([(0,2),(4,7)]),5)
    def test_overlap(self):
        self.assertEqual(overlap([(0,10),(5,12)],[(2,4),(8,15)]),6)
    def test_empty(self):self.assertEqual(overlap([],[(0,10)]),0)
    def test_invalid(self):
        with self.assertRaises(ValueError):merge([(3,2)])
class Trace(unittest.TestCase):
    def rows(self):
        return [[0,20,100,120,0,0],[1,21,210,310,1,1],[1,22,310,410,1,1],
                [1,23,410,510,1,1],[1,16,620,620,1,0],[1,25,1200,1220,1110,0],
                [0,99,0,1300,0,0]]
    def run_trace(self,rows):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'trace.csv'
            with p.open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['thread','phase','begin_ns','end_ns','id','track']);w.writerows(rows)
            return analyze(p)
    def test_calibration_and_union(self):
        r=self.run_trace(self.rows())
        self.assertAlmostEqual(r['clock_calibration']['gpu_to_host_scale'],1.1)
        self.assertAlmostEqual(r['gpu_shading_interval_union_seconds'],330/1e9)
    def test_missing_end_calibration(self):
        with self.assertRaises(ValueError):self.run_trace([r for r in self.rows() if r[1]!=25])
    def test_dropped_events(self):
        rows=self.rows();rows[-1][4]=1
        with self.assertRaises(ValueError):self.run_trace(rows)
    def test_duplicate_phase(self):
        rows=self.rows();rows.append(rows[1])
        with self.assertRaises(ValueError):self.run_trace(rows)

if __name__=='__main__':unittest.main()
