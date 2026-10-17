"""Morton scheduling contracts; no native adaptive estimator/render validation."""
import random
import unittest
from xpu2.control import RenderGate
from xpu2.scheduling import Contribution, Result
from xpu2.morton_schedule import AdaptiveMortonSchedule, MortonPlan, morton


def make(**options):
    gate = RenderGate('reference')
    gate.start(1)
    args = dict(seed=19, frame=4, width=19, height=11, milestones=(2,4,8), block_size=31)
    args.update(options)
    return AdaptiveMortonSchedule(gate, **args)


def payload(lease):
    return tuple(Result(s, (Contribution((0,), (s.index + 1, s.pixel / 256, 0.5)),)) for s in lease.samples)


def run(seed, tile_size=8, block_size=31, window=4):
    schedule = make(tile_size=tile_size, block_size=block_size, window=window)
    rng = random.Random(seed)
    working, samples = [], set()
    while not schedule.finished:
        while (lease := schedule.claim(rng.choice(('cpu', 'gpu')))) is not None:
            working.append(lease)
        if working:
            lease = working.pop(rng.randrange(len(working)))
            if rng.random() < .15:
                assert schedule.retry(lease)
                assert not schedule.complete(lease, payload(lease))
            else:
                assert not samples.intersection(lease.samples)
                assert schedule.complete(lease, payload(lease))
                samples.update(lease.samples)
        checkpoint = schedule.checkpoint()
        if checkpoint:
            assert not working
            # Deliberately simple external decision, NOT a variance estimator.
            converged = {p for p in checkpoint.active_pixels if (p % 3 + 1) * 2 <= checkpoint.samples}
            assert schedule.advance(checkpoint, converged)
    return schedule.image(), schedule.queue.counts, samples


class MortonTests(unittest.TestCase):
    def test_morton_known_order(self):
        self.assertEqual(sorted(((x,y) for x in range(2) for y in range(2)), key=lambda p:morton(*p)),
                         [(0,0),(1,0),(0,1),(1,1)])
        self.assertEqual(morton(2,0), 4)
        self.assertEqual(morton(0,2), 8)

    def test_edges_and_sparse_mask_cover_each_sample_once(self):
        active = frozenset(p for p in range(19*11) if p % 7)
        plan = MortonPlan(3,-2,19,11,2,7,active,block_size=17)
        samples = [s for block in range(plan.blocks) for s in plan.samples(block)]
        self.assertEqual(len(samples), len(set(samples)))
        self.assertEqual({(s.pixel,s.index) for s in samples}, {(p,s) for p in active for s in range(2,7)})
        self.assertTrue(all(len(plan.samples(b)) <= 17 for b in range(plan.blocks)))

    def test_device_completion_order_retry_and_window_invariance(self):
        reference = run(0)
        for seed in range(1,20):
            self.assertEqual(run(seed, window=seed%5+1), reference)
        self.assertEqual(reference[1], [2 if p%3==0 else 4 if p%3==1 else 8 for p in range(19*11)])

    def test_batch_and_tile_size_do_not_change_results(self):
        self.assertEqual(run(1), run(12, tile_size=4, block_size=7, window=8))
        self.assertEqual(run(1), run(25, tile_size=16, block_size=256, window=2))

    def test_slow_job_prevents_early_convergence_and_more_samples(self):
        schedule = make(width=2, height=1, milestones=(1,2), block_size=1, window=2)
        slow, fast = schedule.claim('cpu'), schedule.claim('gpu')
        self.assertTrue(schedule.complete(fast, payload(fast)))
        self.assertIsNone(schedule.checkpoint())
        self.assertIsNone(schedule.claim('gpu'))
        self.assertFalse(schedule.advance(None, {0,1}))
        self.assertTrue(schedule.complete(slow,payload(slow)))
        checkpoint = schedule.checkpoint()
        self.assertEqual(checkpoint.counts, (1,1))
        self.assertTrue(schedule.advance(checkpoint, {0}))
        self.assertFalse(schedule.advance(checkpoint, {1}))
        later = schedule.claim('gpu')
        self.assertTrue(all(s.pixel==1 and s.index==1 for s in later.samples))
        self.assertFalse(schedule.complete(slow,payload(slow)))

    def test_scene_change_invalidates_checkpoint_and_results(self):
        schedule = make(width=1, height=1, milestones=(1,2))
        lease = schedule.claim('cpu')
        schedule.complete(lease,payload(lease))
        checkpoint = schedule.checkpoint()
        schedule.gate.start(2)
        self.assertFalse(schedule.advance(checkpoint,{0}))
        self.assertIsNone(schedule.claim('gpu'))
        with self.assertRaises(ValueError): schedule.image()

    def test_max_cap_stops_unconverged_pixels(self):
        schedule = make(width=1,height=1,milestones=(1,))
        lease = schedule.claim('cpu')
        schedule.complete(lease,payload(lease))
        self.assertTrue(schedule.advance(schedule.checkpoint(),set()))
        self.assertTrue(schedule.finished)
        self.assertIsNone(schedule.claim('gpu'))

    def test_early_all_converged_stops(self):
        schedule = make(width=1,height=1)
        lease = schedule.claim('gpu')
        schedule.complete(lease,payload(lease))
        self.assertTrue(schedule.advance(schedule.checkpoint(),{0}))
        self.assertTrue(schedule.finished)
        self.assertEqual(schedule.queue.counts,[2])

    def test_invalid_decisions_do_not_consume_checkpoint(self):
        schedule = make(width=1,height=1)
        lease = schedule.claim('cpu');schedule.complete(lease,payload(lease))
        checkpoint = schedule.checkpoint()
        for bad in ({1},{True},{-1}):
            with self.assertRaises(ValueError): schedule.advance(checkpoint,bad)
            self.assertIs(checkpoint,schedule.checkpoint())
        self.assertTrue(schedule.advance(checkpoint,{0}))

    def test_missing_sample_cannot_be_counted_as_converged(self):
        schedule = make(width=2,height=1,milestones=(2,4))
        lease = schedule.claim('gpu')
        with self.assertRaises(ValueError): schedule.complete(lease, payload(lease)[:-1])
        self.assertIsNone(schedule.checkpoint())
        self.assertEqual(schedule.queue.counts, [0,0])
        self.assertTrue(schedule.retry(lease))
        fallback = schedule.claim('cpu')
        self.assertEqual(fallback.samples, lease.samples)
        self.assertTrue(schedule.complete(fallback, payload(fallback)))

    def test_weighted_device_contributions_not_averaged_equally(self):
        schedule = make(width=1,height=1,milestones=(1,3),block_size=1)
        cpu = schedule.claim('cpu')
        schedule.complete(cpu, (Result(cpu.samples[0], (Contribution((0,),(2,0,0)),), weight=2, alpha=2),))
        self.assertTrue(schedule.advance(schedule.checkpoint(), set()))
        for _ in range(2):
            gpu = schedule.claim('gpu')
            schedule.complete(gpu, (Result(gpu.samples[0], (Contribution((0,),(1,1,0)),)),))
        self.assertTrue(schedule.advance(schedule.checkpoint(), set()))
        self.assertEqual(schedule.image(), ((1.0,0.5,0.0,1.0),))

    def test_invalid_parameters(self):
        for milestones in ((),(0,),(2,1),(1,1),(True,)):
            with self.assertRaises(ValueError): make(milestones=milestones)
        for active in ({-1},{4},{True}):
            with self.assertRaises(ValueError): MortonPlan(0,0,2,2,0,1,active)
        with self.assertRaises(ValueError): MortonPlan(0,0,0,2,0,1)
        with self.assertRaises(ValueError): MortonPlan(0,0,2,2,1,1)


if __name__ == '__main__':
    unittest.main()
