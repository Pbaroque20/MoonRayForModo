"""Scheduler-only ownership/locality tests; CPU/GPU names are simulated devices."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import random
import unittest
from xpu2.local_tile_schedule import Batch, TileQueues


def batches(n=1024):
    return [Batch((1,i), (i%32,i//32), frozenset({'cpu'} if i%7==0 else {'cpu','gpu'})) for i in range(n)]


class LocalTileTests(unittest.TestCase):
    def test_identical_keyed_payloads_across_completion_orders(self):
        results=[]
        for policy in ('shared','neighbor','shared_reserved','neighbor_reserved'):
            for seed in range(8):
                q=TileQueues(batches(),policy.removesuffix('_reserved'),prefer_cpu_only=policy.endswith('_reserved'));rng=random.Random(seed)
                while q.checkpoint() is None:
                    work=[q.claim(str(i), 'cpu' if i%2==0 else 'gpu') for i in range(8)]
                    rng.shuffle(work)
                    for lease in filter(None,work):
                        self.assertIn(lease.device,lease.batch.eligible)
                        self.assertTrue(q.complete(lease,(lease.batch.key[1],.25,1.)))
                results.append(q.checkpoint())
        self.assertTrue(all(r==results[0] for r in results))

    def test_neighbor_first_and_far_fallback(self):
        jobs=[Batch((i,),p,frozenset({'cpu'})) for i,p in enumerate(((0,0),(100,100),(1,0)))]
        q=TileQueues(jobs,'neighbor')
        self.assertEqual([q.claim('w','cpu').batch.tile for _ in range(3)],[(0,0),(1,0),(100,100)])
        self.assertIsNone(q.claim('w','cpu'))

    def test_no_elimination_of_unavailable_work(self):
        q=TileQueues([Batch((0,),(0,0),frozenset())],'neighbor')
        self.assertIsNone(q.claim('c','cpu'));self.assertIsNone(q.claim('g','gpu'))
        self.assertIsNone(q.checkpoint())
        self.assertEqual(q.state[(0,)],'pending')

    def test_retry_revokes_old_and_forged_lease(self):
        q=TileQueues(batches(1),'neighbor');old=q.claim('c','cpu')
        self.assertFalse(q.complete(replace(old),(1,2,3)))
        self.assertTrue(q.retry(old));new=q.claim('c','cpu')
        self.assertEqual(new.batch.key,old.batch.key)
        self.assertFalse(q.complete(old,(1,2,3)))
        self.assertTrue(q.complete(new,(1,2,3)))
        self.assertFalse(q.complete(new,(1,2,3)))

    def test_cancel_rejects_stale_publication(self):
        q=TileQueues(batches(1),'neighbor');lease=q.claim('c','cpu');q.cancel()
        self.assertFalse(q.complete(lease,(1,2,3)))
        self.assertFalse(q.retry(lease));self.assertIsNone(q.claim('c','cpu'))
        self.assertIsNone(q.checkpoint())

    def test_concurrent_claims_have_one_owner(self):
        for policy in ('shared','neighbor','shared_reserved','neighbor_reserved'):
            q=TileQueues(batches(4096),policy.removesuffix('_reserved'),prefer_cpu_only=policy.endswith('_reserved'))
            def consume(worker):
                count=0
                while (lease:=q.claim(str(worker),'cpu' if worker%2==0 else 'gpu')) is not None:
                    self.assertIn(lease.device,lease.batch.eligible)
                    self.assertTrue(q.complete(lease,(lease.batch.key[1],.25,1.)))
                    count+=1
                return count
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(consume,range(8))),4096)
            self.assertEqual(len(q.checkpoint()),4096)

    def test_invalid_keys_policy_and_payload(self):
        with self.assertRaises(ValueError):TileQueues(batches(1)*2)
        with self.assertRaises(ValueError):TileQueues([], 'random')
        with self.assertRaises(ValueError):Batch((-1,),(0,0),frozenset())
        with self.assertRaises(ValueError):Batch((1,),(0,0),frozenset({'magic'}))
        q=TileQueues(batches(1));lease=q.claim('c','cpu')
        with self.assertRaises(ValueError):q.complete(lease,(float('nan'),0,0))
        self.assertTrue(q.complete(lease,(1,2,3)))

    def test_cpu_only_priority_preserves_gpu_eligible_work(self):
        jobs=[Batch((0,),(0,0),frozenset({'cpu','gpu'})),Batch((1,),(99,99),frozenset({'cpu'}))]
        for policy in ('shared','neighbor'):
            q=TileQueues(jobs,policy,prefer_cpu_only=True)
            self.assertEqual(q.claim('c','cpu').batch.key,(1,))
            self.assertEqual(q.claim('g','gpu').batch.key,(0,))

    def test_empty_checkpoint(self):
        self.assertEqual(TileQueues([],'neighbor').checkpoint(),())

if __name__=='__main__':unittest.main()
