"""Selected-ray diagnostics must distinguish routing, miss and precision changes."""
import copy
import json
import unittest
from tools.xpu2_ray_probe import parse_rays, summarize, replay_result


def record():
    hit={'geom':1,'prim':3,'inst':4294967295,'t':2.0,'uv':[0.2,0.4],'Ng':[0,0,1]}
    return {'pixel':(77<<16)|96,'sample':0,'sequence':12,'depth':0,'batch':2048,
            'cpu':hit,'gpu':copy.deepcopy(hit)}


class RayProbeTests(unittest.TestCase):
    def test_decimal_values_recover_original_float32(self):
        row=record();row['cpu']['t']=3.05119586;row['gpu']['t']=3.05119634
        restored=parse_rays('XPU2_RAY '+json.dumps(row))
        self.assertEqual(summarize(restored)['max_t_error'],4.76837158203125e-7)

    def test_replay_requires_two_primary_hits(self):
        image={'dimensions':(1,1),'metadata':{},'channels':{k:[0] for k in 'RGBA'}}
        with self.assertRaises(ValueError):replay_result(image,image,image,[])

    def test_exact(self):
        report=summarize([record()])
        self.assertEqual(report['rays'],1)
        self.assertEqual(report['different_hit_attributes'],0)

    def test_hit_miss_is_not_a_precision_error(self):
        row=record();row['gpu']={'geom':4294967295,'prim':0,'inst':4294967295,'t':1e30}
        report=summarize([row])
        self.assertEqual(report['hit_miss_mismatches'],1)
        self.assertEqual(report['max_t_error'],0)

    def test_different_primitives(self):
        row=record();row['gpu']['prim']=4
        self.assertEqual(summarize([row])['primitive_mismatches'],1)

    def test_precision(self):
        row=record();row['gpu']['t']=2.0001;row['gpu']['uv'][0]=0.25
        report=summarize([row])
        self.assertEqual(report['different_hit_attributes'],1)
        self.assertAlmostEqual(report['max_uv_error'],0.05)

    def test_miss_attributes_are_not_required(self):
        row=record()
        for key in ('cpu','gpu'):row[key]={'geom':4294967295,'prim':0,'inst':4294967295,'t':1e30}
        self.assertEqual(summarize([row])['different_hit_attributes'],0)

    def test_parse_and_pixel_coordinates(self):
        rows=parse_rays('unrelated log\nXPU2_RAY '+json.dumps(record()))
        self.assertEqual((rows[0]['x'],rows[0]['y_from_bottom']),(96,77))

    def test_nonfinite_rejected(self):
        row=record();row['cpu']['t']=float('nan')
        with self.assertRaises(ValueError):parse_rays('XPU2_RAY '+json.dumps(row))

    def test_wrong_routing_rejected(self):
        row=record();row['batch']=10
        with self.assertRaises(ValueError):parse_rays('XPU2_RAY '+json.dumps(row))

    def test_wrong_pixel_rejected(self):
        row=record();row['pixel']=0
        with self.assertRaises(ValueError):parse_rays('XPU2_RAY '+json.dumps(row))

if __name__=='__main__':unittest.main()
