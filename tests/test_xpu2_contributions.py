import copy
import json
import unittest
from xpu2.contributions import parse,accumulate,multiset_comparison,summarize,shadow_changes


def row(rgba,weight=0):
    return {'pixel':(77<<16)|96,'sample':0,'rgba':rgba,'weight':weight,'tile_pass':0}


class ContributionTests(unittest.TestCase):
    def test_shadow_change_keeps_identical_ray_direction(self):
        ray={'pixel':(77<<16)|96,'sample':0,'sequence':0,'depth':1,'type':0,'direction':[0,0,1],'cpu':1,'gpu':1}
        other=dict(ray,cpu=0,gpu=0)
        result=shadow_changes({'shadow':[ray],'queued':[ray]},{'shadow':[other],'queued':[other]})
        self.assertEqual(result['unique_identical_direction_matches'],1)
        self.assertEqual(len(result['visibility_changes']),1)

    def test_shadow_change_does_not_pair_ambiguous_rays(self):
        ray={'pixel':(77<<16)|96,'sample':0,'sequence':0,'depth':1,'type':0,'direction':[0,0,1],'cpu':1,'gpu':1}
        result=shadow_changes({'shadow':[ray,ray],'queued':[ray]},{'shadow':[ray],'queued':[ray]})
        self.assertEqual(result['unique_identical_direction_matches'],0)

    def test_order_changes_float_sum_not_multiset(self):
        a=[row([1e8,0,0,0],1),row([-1e8,0,0,0]),row([1,0,0,0])]
        b=list(reversed(a))
        self.assertNotEqual(accumulate(a,False),accumulate(b,False))
        self.assertEqual(accumulate(a,True),accumulate(b,True))
        self.assertTrue(multiset_comparison({'radiance':a},{'radiance':b})[0]['identical_radiance_multiset'])

    def test_duplicates_are_not_lost(self):
        a=[row([1,0,0,0],1)]
        result=multiset_comparison({'radiance':a},{'radiance':a+a})[0]
        self.assertFalse(result['identical_radiance_multiset'])
        self.assertEqual(result['added_count'],1)

    def test_weight_is_part_of_contribution(self):
        a=row([1,0,0,0],1);b=copy.deepcopy(a);b['weight']=2
        self.assertFalse(multiset_comparison({'radiance':[a]},{'radiance':[b]})[0]['identical_radiance_multiset'])

    def test_zero_weight_rejected(self):
        with self.assertRaises(ValueError):accumulate([row([1,0,0,0])],True)

    def test_interrupted_native_record_is_rejected(self):
        with self.assertRaises(ValueError):parse('XPU2_SHADOW_RESULT {"pixel":6291588,"sample":00:00:01 Rendering')

    def test_parse_rejects_nonfinite(self):
        a=row([float('nan'),0,0,0],1)
        with self.assertRaises(ValueError):parse('XPU2_RADIANCE '+json.dumps(a))

    def test_parse_requires_camera_sample_zero(self):
        a=row([1,0,0,0],1);a['sample']=1
        with self.assertRaises(ValueError):parse('XPU2_RADIANCE '+json.dumps(a))

    def test_parse_restores_float32(self):
        a=row([0.100000001,0,0,0],1)
        self.assertEqual(parse('XPU2_RADIANCE '+json.dumps(a))['radiance'][0]['rgba'][0],0.10000000149011612)

    def test_summarize_requires_both_pixels(self):
        image={'dimensions':(256,144),'channels':{k:[0.]*(256*144) for k in 'RGBA'}}
        with self.assertRaises(ValueError):summarize({'radiance':[row([0,0,0,0],1)],'queued':[],'shadow':[]},image)

if __name__=='__main__':unittest.main()
