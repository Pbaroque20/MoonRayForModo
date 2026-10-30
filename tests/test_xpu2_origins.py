import copy
import unittest
from xpu2.origins import plane_hit,summarize,blocker,POLICIES,validate_fixture,blocker_activity,validate_source_hits

PLANE=[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]]

def queries():
    return [{'pixel':(77<<16)|96,'sample':0,'source_index':0,'policy':p,'cpu':1,'gpu':1,'original_gpu':1,
             'origin':[0,0,-.1],'direction':[0,0,1],'normal':[0,0,1],'near':.01} for p in POLICIES]

class OriginTests(unittest.TestCase):
    def test_missing_primary_surface_rejected(self):
        with self.assertRaises(ValueError):validate_source_hits('')
    def test_camera_miss_rejected(self):
        import json
        hits=[{'pixel':(y<<16)|x,'sample':0,'depth':0,'gpu':{'geom':0xffffffff,'Ng':[0,0,1]}} for x,y in [(96,77),(132,96)]]
        with self.assertRaises(ValueError):validate_source_hits('\n'.join('XPU2_RAY '+json.dumps(r) for r in hits))
    def test_empty_blocker_rejected(self):
        with self.assertRaises(ValueError):validate_fixture('', '/xpu2/near_blocker,0,0,0,0,0',True)
    def test_unknown_native_attribute_rejected(self):
        with self.assertRaises(ValueError):validate_fixture('No Attribute named bad','',False)
    def test_expected_blocker_topology(self):
        validate_fixture('', '/xpu2/near_blocker,2,4,0,0,0',True)
    def test_blocker_activity_requires_new_native_occlusion(self):
        a=queries();b=copy.deepcopy(a)
        for row in a:row.update(cpu=0,gpu=0)
        result=blocker_activity(a,b)
        self.assertEqual(result['newly_blocked_on_both_backends'],6)
        self.assertEqual(blocker_activity(b,b)['newly_blocked_on_both_backends'],0)
    def test_triangle_distance(self):
        self.assertAlmostEqual(plane_hit([0,0,-.1],[0,0,1],PLANE),.1)
    def test_plane_behind_ray_keeps_signed_distance(self):
        self.assertAlmostEqual(plane_hit([0,0,.1],[0,0,1],PLANE),-.1)
    def test_outside_patch_is_not_an_infinite_plane(self):
        self.assertIsNone(plane_hit([2,0,-.1],[0,0,1],PLANE))
    def test_parallel_ray(self):
        self.assertIsNone(plane_hit([0,0,-.1],[1,0,0],PLANE))
    def test_missing_policy_is_invalid(self):
        with self.assertRaises(ValueError):summarize(queries()[:-1])
    def test_baseline_gpu_query_must_match_render_query(self):
        rows=queries();rows[0]['gpu']=0
        with self.assertRaises(ValueError):summarize(rows)
    def test_blocker_skip_is_detected(self):
        rows=queries();rows[3].update(origin=[0,0,.1],gpu=0,cpu=0)
        result=summarize(rows,PLANE)
        self.assertEqual(result['policies'][POLICIES[3]]['skipped_blocker'],1)
    def test_blocker_inside_existing_near_limit_is_not_new_skip(self):
        rows=queries();rows[0]['near']=.2;rows[3].update(origin=[0,0,.1],gpu=0,cpu=0)
        self.assertEqual(len(summarize(rows,PLANE)['blocker_failures']),0)
    def test_cpu_gpu_disagreement_is_reported(self):
        rows=queries();rows[1]['cpu']=0
        self.assertEqual(summarize(rows)['policies'][POLICIES[1]]['cpu_gpu_disagreements'],1)
    def test_duplicate_ray_policy_is_rejected(self):
        rows=queries();rows.append(copy.deepcopy(rows[0]))
        with self.assertRaises(ValueError):summarize(rows)
    def test_fixture_vertices_are_finite_float32(self):
        from xpu2.contributions import f32
        vertices=blocker(1e-6,[0,0,1],[0,0,1])
        self.assertTrue(all(x==f32(x) for p in vertices for x in p))
        self.assertEqual(len(vertices),4)

if __name__=='__main__':unittest.main()
