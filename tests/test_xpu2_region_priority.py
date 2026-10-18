"""Priority hierarchy/cost contracts. Simulated workers, not native GPU rendering."""
import unittest
from xpu2.region_priority import Attention, DeviceCost, RegionHierarchy, choose_device
from xpu2.morton_schedule import MortonPlan, AdaptiveMortonSchedule, morton
from xpu2.control import RenderGate
from xpu2.scheduling import Contribution, Result


def render(priority):
    gate=RenderGate('reference');gate.start(1)
    order=RegionHierarchy(19,11,attention={(2,1):Attention(changed=True)}).order if priority else None
    schedule=AdaptiveMortonSchedule(gate,19,4,19,11,(2,4,8),block_size=17,tile_order=order)
    seen=set()
    while not schedule.finished:
        cpu,gpu=schedule.claim('cpu'),schedule.claim('gpu')
        for lease in (gpu,cpu):  # Both devices can own work; complete out of order.
            if lease:
                values=tuple(Result(s,(Contribution((0,),(s.index+1,s.pixel/256,.5)),)) for s in lease.samples)
                assert not seen.intersection(lease.samples)
                assert schedule.complete(lease,values)
                seen.update(lease.samples)
        checkpoint=schedule.checkpoint()
        if checkpoint:
            converged={p for p in checkpoint.active_pixels if (p%3+1)*2 <= checkpoint.samples}
            next_order=RegionHierarchy(19,11,attention={(0,0):Attention(noise=1)}).order if priority else None
            assert schedule.advance(checkpoint,converged,tile_order=next_order)
    return schedule.image(),schedule.queue.counts,seen


class RegionPriorityTests(unittest.TestCase):
    def test_equal_priorities_preserve_morton(self):
        tree=RegionHierarchy(19,11)
        self.assertEqual(tree.order,tuple(sorted(((x,y) for y in range(2) for x in range(3)),key=lambda p:morton(*p))))
    def test_sparse_edges_priority_and_complete_coverage(self):
        active={(0,0),(1,0),(2,1)}
        tree=RegionHierarchy(19,11,active_tiles=active,attention={(2,1):Attention(changed=True)})
        self.assertEqual(tree.order[0],(2,1));self.assertEqual(set(tree.order),active)
        self.assertEqual(len(tree.order),len(active))
        self.assertEqual(RegionHierarchy(19,11,active_tiles=()).order,())
    def test_signals_do_not_mutate_published_tree(self):
        signals={(0,0):Attention(contrast=1)};tree=RegionHierarchy(16,16,attention=signals)
        signals[(1,1)]=Attention(changed=True)
        self.assertEqual(tree.order[0],(0,0))
    def test_aging_outweighs_bounded_visual_scores(self):
        tree=RegionHierarchy(16,8,attention={(0,0):Attention(1,1,True),(1,0):Attention(waiting_epochs=8)})
        self.assertEqual(tree.order[0],(1,0))
    def test_noisy_flat_region_can_outrank_clean_edge(self):
        tree=RegionHierarchy(16,8,attention={(0,0):Attention(contrast=1),(1,0):Attention(noise=1)})
        self.assertEqual(tree.order[0],(1,0))
    def test_priority_keeps_exact_samples_and_accumulation(self):
        self.assertEqual(render(False),render(True))
    def test_omitted_or_duplicate_tiles_rejected(self):
        for order in ([(0,0)],[(0,0),(0,0)],[(0,0),(2,0)],[(0,0),(-1,0)]):
            with self.assertRaises(ValueError):MortonPlan(1,1,16,8,0,2,tile_order=order)
    def test_inactive_tiles_allowed_but_no_samples_added(self):
        plan=MortonPlan(1,1,16,8,0,2,active={0},tile_order=((1,0),(0,0)))
        self.assertEqual({s.pixel for b in range(plan.blocks) for s in plan.samples(b)},{0})
    def test_invalid_priority_values(self):
        for value in (-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):Attention(noise=value)
        with self.assertRaises(ValueError):RegionHierarchy(1,1,attention={(1,0):Attention()})
    def test_capability_first_then_measured_cost(self):
        cpu=DeviceCost('cpu',frozenset({'diffuse','glass'}),.1)
        gpu=DeviceCost('gpu',frozenset({'diffuse'}),.01,transfer_seconds=.5)
        self.assertEqual(choose_device(100,frozenset({'diffuse'}),(cpu,gpu)),'gpu')
        self.assertEqual(choose_device(1,frozenset({'diffuse'}),(cpu,gpu)),'cpu')
        self.assertEqual(choose_device(100,frozenset({'glass'}),(cpu,gpu)),'cpu')
        busy=DeviceCost('gpu',gpu.capabilities,.01,queued_seconds=20)
        self.assertEqual(choose_device(100,frozenset({'diffuse'}),(cpu,busy)),'cpu')
    def test_missing_resources_or_capabilities_defer(self):
        cpu=DeviceCost('cpu',frozenset({'diffuse'}),.1)
        self.assertIsNone(choose_device(1,frozenset({'volume'}),(cpu,)))
        self.assertIsNone(choose_device(1,frozenset({'diffuse'}),(cpu,),resources_ready=False))
    def test_invalid_costs_rejected(self):
        with self.assertRaises(ValueError):DeviceCost('gpu',frozenset(),-.1)
        cpu=DeviceCost('cpu',frozenset(),.1)
        with self.assertRaises(ValueError):choose_device(1,frozenset(),(cpu,cpu))
        with self.assertRaises(ValueError):choose_device(float('nan'),frozenset(),(cpu,))
    def test_bad_reprioritization_does_not_advance(self):
        gate=RenderGate('reference');gate.start(1)
        schedule=AdaptiveMortonSchedule(gate,1,1,16,8,(1,2))
        while (lease:=schedule.claim('cpu')) is not None:
            schedule.complete(lease,tuple(Result(s,()) for s in lease.samples))
        checkpoint=schedule.checkpoint()
        with self.assertRaises(ValueError):schedule.advance(checkpoint,set(),tile_order=((0,0),))
        self.assertIs(schedule.checkpoint(),checkpoint);self.assertEqual(schedule.phase,0)
        self.assertTrue(schedule.advance(checkpoint,set(),tile_order=((1,0),(0,0))))


if __name__=='__main__':unittest.main()
