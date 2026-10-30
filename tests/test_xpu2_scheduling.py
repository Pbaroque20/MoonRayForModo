"""Synthetic protocol checks; no native sampler/GPU parity is claimed."""
import random
import unittest
from dataclasses import replace

from xpu2.control import RenderGate, DemandQueue, Resource
from xpu2.scheduling import Contribution, Plan, Result, Sample, Scheduler


def scheduler(**kwargs):
    gate = RenderGate("pinned-reference")
    gate.start(7)
    return Scheduler(gate, Plan(19, 3, 3, 7, 4), **kwargs)


def results(lease):
    # Cancellation-sensitive HDR summation exercises order, not just exact ints.
    return tuple(Result(s, (
        Contribution((0,), (1e8, 0.25, 0.5)),
        Contribution((1,), (-1e8, 0.125, 0.25)),
        Contribution((2,), (s.index + 1.0, 0.0625, 0.125)),
    )) for s in lease.samples)


def shuffled_run(seed, window=4):
    queue = scheduler(window=window)
    rng, working = random.Random(seed), []
    samples, retries, peak = [], 0, 0
    while not queue.finished:
        while True:
            lease = queue.claim(rng.choice(("cpu", "gpu")))
            if lease is None:
                break
            working.append(lease)
        peak = max(peak, len(queue.leases) + len(queue.ready))
        lease = working.pop(rng.randrange(len(working)))
        if rng.random() < 0.2:
            assert queue.retry(lease)
            assert not queue.complete(lease, results(lease))
            retries += 1
            continue
        payload = list(results(lease))
        rng.shuffle(payload)
        payload = [replace(row, contributions=tuple(rng.sample(row.contributions, len(row.contributions))))
                   for row in payload]
        assert queue.complete(lease, tuple(payload))
        samples.extend(lease.samples)
    return queue.image(), queue.counts, sorted(samples), retries, peak


class ScheduleTests(unittest.TestCase):
    def test_shuffled_workers_retries_and_payloads_match(self):
        reference = shuffled_run(0)
        for seed in range(1, 100):
            actual = shuffled_run(seed)
            self.assertEqual(actual[:3], reference[:3])
            self.assertLessEqual(actual[4], 4)
        self.assertEqual(reference[1], [7, 7, 7])
        self.assertEqual(len(set(reference[2])), 21)

    def test_window_size_does_not_change_image(self):
        self.assertEqual(shuffled_run(4, 1)[:3], shuffled_run(81, 7)[:3])

    def test_slow_first_block_bounds_completed_backlog(self):
        queue = scheduler(window=2)
        first, second = queue.claim("cpu"), queue.claim("gpu")
        self.assertTrue(queue.complete(second, results(second)))
        self.assertEqual(queue.cursor, 0)
        self.assertEqual(queue.image(), (None, None, None))
        self.assertIsNone(queue.claim("gpu"))
        self.assertTrue(queue.complete(first, results(first)))
        self.assertEqual(queue.cursor, 2)
        self.assertFalse(queue.ready)
        self.assertIsNotNone(queue.claim("gpu"))

    def test_retry_preserves_samples_but_revokes_old_owner(self):
        queue = scheduler()
        old = queue.claim("gpu")
        self.assertTrue(queue.retry(old))
        new = queue.claim("cpu")
        self.assertEqual(old.samples, new.samples)
        self.assertNotEqual(old.serial, new.serial)
        self.assertFalse(queue.complete(old, results(old)))
        self.assertTrue(queue.complete(new, results(new)))

    def test_duplicate_completion_rejected(self):
        queue = scheduler()
        lease = queue.claim("cpu")
        self.assertTrue(queue.complete(lease, results(lease)))
        before = queue.image()
        self.assertFalse(queue.complete(lease, results(lease)))
        self.assertEqual(queue.image(), before)

    def test_fallback_discards_ready_and_pending_results(self):
        queue = scheduler()
        first, second = queue.claim("cpu"), queue.claim("gpu")
        queue.complete(second, results(second))
        queue.gate.restart_reference("unsupported shading")
        self.assertFalse(queue.complete(first, results(first)))
        self.assertIsNone(queue.claim("cpu"))
        self.assertFalse(queue.finished)
        with self.assertRaises(ValueError):
            queue.image()
        replacement = Scheduler(queue.gate, queue.plan)
        self.assertEqual(replacement.image(), (None, None, None))
        self.assertEqual(replacement.claim("cpu").samples, first.samples)

    def test_cancel_rejects_retry_and_completion(self):
        queue = scheduler()
        lease = queue.claim("cpu")
        queue.gate.cancel()
        self.assertFalse(queue.retry(lease))
        self.assertFalse(queue.complete(lease, results(lease)))

    def test_wrong_worker_cannot_complete_lease(self):
        queue = scheduler()
        lease = queue.claim("cpu")
        self.assertFalse(queue.complete(replace(lease, device="gpu"), results(lease)))

    def test_partial_or_wrong_block_does_not_publish(self):
        queue = scheduler()
        lease = queue.claim("cpu")
        valid = results(lease)
        wrong = replace(valid[0], sample=replace(valid[0].sample, seed=20))
        for payload in (valid[:-1], (wrong,) + valid[1:], (valid[0],) * len(valid)):
            with self.assertRaises(ValueError):
                queue.complete(lease, payload)
            self.assertTrue(queue.owns(lease))
            self.assertEqual(queue.cursor, 0)

    def test_duplicate_branch_not_silently_counted(self):
        queue = scheduler()
        lease = queue.claim("cpu")
        valid = results(lease)
        row = replace(valid[0], contributions=(valid[0].contributions[0],) * 2)
        with self.assertRaises(ValueError):
            queue.complete(lease, (row,) + valid[1:])
        self.assertEqual(queue.image(), (None, None, None))

    def test_bad_numeric_and_weight_payloads_rejected(self):
        for value in (float("nan"), float("inf"), 1e100, True):
            queue = scheduler()
            lease = queue.claim("cpu")
            valid = results(lease)
            row = replace(valid[0], contributions=(Contribution((0,), (value, 0, 0)),))
            with self.assertRaises(ValueError):
                queue.complete(lease, (row,) + valid[1:])
        queue = scheduler()
        lease = queue.claim("cpu")
        for weight in (0, -1, float("nan")):
            payload = tuple(replace(row, weight=weight) for row in results(lease))
            with self.assertRaises(ValueError):
                queue.complete(lease, payload)

    def test_sample_and_film_overflow_are_transactional(self):
        queue = scheduler()
        lease = queue.claim("cpu")
        payload = tuple(Result(s, (Contribution((0,), (3e38, 0, 0)),)) for s in lease.samples)
        # Pixel zero occurs twice in this block; finite samples overflow the film.
        with self.assertRaises(ValueError):
            queue.complete(lease, payload)
        self.assertEqual(queue.image(), (None, None, None))
        self.assertTrue(queue.owns(lease))
        self.assertFalse(queue.ready)
        self.assertTrue(queue.complete(lease, results(lease)))

    def test_cap_bounds_per_sample_contributions(self):
        queue = scheduler(max_contributions=2)
        lease = queue.claim("cpu")
        with self.assertRaises(ValueError):
            queue.complete(lease, results(lease))
        self.assertTrue(queue.owns(lease))

    def test_missing_resources_keep_sample_identity(self):
        queue = scheduler(window=1)
        lease = queue.claim("gpu")
        pages = DemandQueue(queue.attempt)
        mesh = Resource("geometry", "mesh", 1)
        mip = Resource("texture", "albedo", 1, "mip2/tile0")
        for sample in lease.samples:
            self.assertTrue(pages.defer(queue.attempt, sample, (mesh, mip)))
        pages.requests()
        self.assertFalse(pages.available(queue.attempt, mip))
        self.assertIsNone(queue.claim("cpu"))
        ready = pages.available(queue.attempt, mesh)
        self.assertEqual(set(ready), set(lease.samples))
        self.assertTrue(queue.complete(lease, results(lease)))

    def test_weight_is_counted_once_per_sample(self):
        gate = RenderGate("reference")
        gate.start(0)
        queue = Scheduler(gate, Plan(0, 0, 1, 1, 1))
        lease = queue.claim("cpu")
        payload = (Result(lease.samples[0], (Contribution((0,), (2, 0, 0)),
                     Contribution((1,), (0, 2, 0))), alpha=2, weight=2),)
        queue.complete(lease, payload)
        self.assertEqual(queue.image(), ((1.0, 1.0, 0.0, 1.0),))

    def test_black_sample_has_alpha_without_rgb_contributions(self):
        queue = scheduler()
        lease = queue.claim("cpu")
        queue.complete(lease, tuple(Result(s, ()) for s in lease.samples))
        self.assertEqual(queue.image(), ((0.0, 0.0, 0.0, 1.0),) * 3)

    def test_plan_keys_independent_of_attempt_id(self):
        queue = scheduler()
        first = queue.claim("cpu")
        queue.gate.start(8)
        other = Scheduler(queue.gate, queue.plan)
        second = other.claim("gpu")
        self.assertNotEqual(first.attempt, second.attempt)
        self.assertEqual(first.samples, second.samples)

    def test_last_block_and_invalid_settings(self):
        plan = Plan(0, -2, 3, 7, 4)
        self.assertEqual(len(plan.samples(plan.blocks - 1)), 1)
        with self.assertRaises(ValueError):
            plan.samples(plan.blocks)
        for args in ((0, 0, 0, 1, 1), (0, 0, 1, True, 1), (-1, 0, 1, 1, 1)):
            with self.assertRaises(ValueError):
                Plan(*args)
        with self.assertRaises(ValueError):
            scheduler(window=0)
        with self.assertRaises(ValueError):
            scheduler().claim("unvalidated-backend")


if __name__ == "__main__":
    unittest.main()
