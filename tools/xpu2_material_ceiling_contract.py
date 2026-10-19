"""Fail-closed tests for fixed material-job image gates and frame-time estimates."""
import copy,csv,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from xpu2.material_job_metrics import compare,envelope,qualified,cpu_totals

def image(x):
    return dict(dimensions=[1,1],metadata={},channels={c:[x] for c in 'RGBA'})

class Contract(unittest.TestCase):
    def test_signed_zero_is_not_bit_exact(self):
        self.assertFalse(qualified([compare(image(0.),image(-0.))]))
    def test_nonfinite_rejected(self):
        for x in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):compare(image(x),image(x))
    def test_frozen_zero_envelope(self):
        bound=envelope([image(1.) for _ in range(5)])
        self.assertTrue(qualified([compare(image(1.),image(1.))],bound))
        self.assertFalse(qualified([compare(image(1.),image(1.0000001192092896))],bound))
    def test_reference_envelope_does_not_fit_candidate(self):
        refs=[image(1.+i*.0001) for i in range(5)];bound=envelope(refs)
        self.assertTrue(qualified([compare(r,refs[2]) for r in refs],bound))
        self.assertFalse(qualified([compare(r,image(1.001)) for r in refs],bound))
        with self.assertRaises(ValueError):envelope(refs[:4])
    def test_worker_time_is_not_wall_time(self):
        fields='thread stage calls lanes sampled_calls sampled_lanes exclusive_ns errors active rate'.split()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'cpu.csv'
            rows=[dict(zip(fields,[t,s,64,256,1,4,1000000,0,0,64])) for t in range(12) for s in ('material_construct_maps','all_lobes_mis','light_sample_eval','light_tree')]
            def write():
                with path.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            write();result=cpu_totals(path)
            self.assertAlmostEqual(result['material_maps_worker_seconds'],.768)
            self.assertAlmostEqual(result['selected_lighting_worker_seconds'],2.304)
            rows[0]['active']=1;write()
            with self.assertRaises(ValueError):cpu_totals(path)
    def test_no_empty_gate(self):
        with self.assertRaises(ValueError):qualified([])

if __name__=='__main__':unittest.main()
