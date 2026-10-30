"""Contract tests only; these never launch Modo, MoonRay, CUDA or a renderer."""
import json
import math
from pathlib import Path
import random
import unittest
from protocol_model import Epoch, Sample, Ledger, checker_grid


class Contracts(unittest.TestCase):
    def make(self, **kwargs):
        return Ledger(Epoch(1,1,1,1), **kwargs)

    def started(self, ledger, pixel=0, owner="cpu"):
        key=ledger.issue(Sample(pixel,0),owner)
        self.assertTrue(ledger.start(key,owner))
        return key

    def test_checkerboard_and_clipped_bottom(self):
        grid=checker_grid()
        self.assertEqual(len(grid),510)
        self.assertEqual(sum(c.owner=="gpu" for c in grid),255)
        self.assertEqual(sum(c.width*c.height for c in grid),1920*1080)
        self.assertEqual(grid[-1].height,56)
        for size in (32,64,128):
            cells=checker_grid(193,107,size)
            pixels={(x,y) for c in cells for y in range(c.y,c.y+c.height)
                    for x in range(c.x,c.x+c.width)}
            self.assertEqual(len(pixels),193*107)
            self.assertEqual(sum(c.width*c.height for c in cells),len(pixels))

    def test_full_mailbox_retains_sender_ownership(self):
        ledger=self.make(mailbox_capacity=1)
        first=ledger.issue(Sample(0,0),"cpu")
        second=ledger.issue(Sample(1,0),"cpu")
        ledger.transfer(first,"cpu","gpu")
        self.assertIsNone(ledger.transfer(second,"cpu","gpu"))
        self.assertTrue(ledger.start(second,"cpu"))
        with self.assertRaises(ValueError):
            ledger.start(first,"cpu")
        ledger.receive()
        self.assertTrue(ledger.start(first,"gpu"))

    def test_replayed_grant_and_duplicate_completion(self):
        ledger=self.make()
        key=ledger.issue(Sample(0,0),"cpu")
        packet=ledger.transfer(key,"cpu","gpu")
        ledger.receive()
        self.assertTrue(ledger.start(key,"gpu"))
        ledger.mailbox.append(packet)  # Inject a duplicate from transport.
        self.assertIsNone(ledger.receive())
        ledger.stage(key,"gpu",rgba=(1.,2.,3.,1.))
        with self.assertRaises(ValueError):
            ledger.stage(key,"gpu",rgba=(1.,2.,3.,1.))
        self.assertEqual(ledger.audit()["completed"],1)
        self.assertEqual(ledger.film[0],(1.,2.,3.,1.))

    def test_sample_tree_counts_only_after_all_children(self):
        ledger=self.make()
        key=self.started(ledger)
        ledger.stage(key,"cpu",children=2,rgba=(.25,0.,0.,0.))
        ledger.stage(key,"cpu",branch=(1,),rgba=(.5,0.,0.,.5))
        self.assertFalse(ledger.quiescent())
        self.assertFalse(ledger.counts)
        self.assertEqual(ledger.audit()["outstanding"],1)
        ledger.stage(key,"cpu",branch=(0,),rgba=(.25,0.,0.,.5))
        self.assertTrue(ledger.quiescent())
        self.assertEqual(ledger.counts[0],1)
        self.assertEqual(ledger.film[0],(1.,0.,0.,1.))

    def test_texture_retry_is_transactional(self):
        ledger=self.make()
        key=self.started(ledger,owner="gpu")
        self.assertFalse(ledger.stage(key,"gpu",children=2,rgba=(7.,0.,0.,1.),
                                      texture_miss=True))
        self.assertEqual(ledger.records[key].pending,{()})
        self.assertEqual(ledger.records[key].rgba,(0.,0.,0.,0.))
        ledger.transfer(key,"gpu","cpu",migration=True)
        ledger.receive()
        ledger.stage(key,"cpu",rgba=(2.,0.,0.,1.))
        self.assertEqual(ledger.film[0],(2.,0.,0.,1.))
        ledger.audit()

    def test_deadline_cannot_discard_started_sample(self):
        ledger=self.make()
        key=self.started(ledger)
        unused=ledger.issue(Sample(1,0),"cpu")
        ledger.cutoff()
        self.assertFalse(ledger.start(unused,"cpu"))
        with self.assertRaises(ValueError):
            ledger.cancel_unstarted(key,"cpu")
        self.assertTrue(ledger.cancel_unstarted(unused,"cpu"))
        ledger.next_frame()
        self.assertTrue(ledger.stage(key,"cpu",rgba=(3.,0.,0.,1.)))
        self.assertEqual(ledger.audit()["completed"],1)

    def test_settings_change_rejects_old_results_and_grants(self):
        ledger=self.make()
        key=self.started(ledger)
        ledger.transfer(key,"cpu","gpu",migration=True)
        ledger.invalidate(Epoch(1,1,1,2))
        self.assertIsNone(ledger.receive())
        self.assertFalse(ledger.stage(key,"gpu",rgba=(9.,0.,0.,1.)))
        key=self.started(ledger)
        ledger.stage(key,"cpu",rgba=(1.,0.,0.,1.))
        self.assertEqual(ledger.film[0],(1.,0.,0.,1.))
        self.assertEqual(ledger.audit()["completed"],1)

    def test_low_bit_wrap_and_session_restart_do_not_alias(self):
        ledger=self.make()
        old=self.started(ledger)
        ledger.invalidate(Epoch(1,65537,1,1))
        self.assertFalse(ledger.stage(old,"cpu"))
        with self.assertRaises(ValueError):
            ledger.invalidate(Epoch(1,1,1,1))
        ledger.invalidate(Epoch(2,1,1,1))
        self.assertFalse(ledger.stage(old,"cpu"))
        self.assertEqual(ledger.audit()["started"],0)

    def test_invalid_contributions_and_budget_refusal_are_atomic(self):
        ledger=self.make(max_records=1,max_leaves=2)
        key=self.started(ledger)
        self.assertIsNone(ledger.issue(Sample(1,0),"gpu"))
        with self.assertRaises(ValueError):
            ledger.stage(key,"cpu",rgba=(math.nan,0.,0.,0.))
        self.assertEqual(ledger.records[key].pending,{()})
        ledger.stage(key,"cpu",children=2)
        self.assertFalse(ledger.stage(key,"cpu",branch=(0,),children=2))
        self.assertEqual(ledger.records[key].pending,{(0,),(1,)})
        ledger.stage(key,"cpu",branch=(0,))
        ledger.stage(key,"cpu",branch=(1,))
        ledger.audit()

    def test_adversarial_completion_order_preserves_sample_count(self):
        # Deterministic fuzz of delay, capacity backpressure, miss, replay, and
        # migration. It is not a native concurrency/memory-ordering stress test.
        for seed in range(20):
            rng=random.Random(seed)
            ledger=self.make(max_records=256,mailbox_capacity=3)
            keys=[ledger.issue(Sample(i,0),"cpu" if i%2 else "gpu")
                  for i in range(128)]
            pending=[]
            for key in keys:
                owner=ledger.records[key].owner
                if rng.randrange(3)==0:
                    packet=ledger.transfer(key,owner,"gpu" if owner=="cpu" else "cpu")
                    if packet:
                        pending.append(packet)
                if rng.randrange(2):
                    ledger.receive()
            while ledger.mailbox:
                ledger.receive()
            for key in keys:
                ledger.start(key,ledger.records[key].owner)
            ledger.cutoff()
            rng.shuffle(keys)
            for key in keys:
                owner=ledger.records[key].owner
                if rng.randrange(2):
                    self.assertFalse(ledger.stage(key,owner,texture_miss=True))
                    packet=ledger.transfer(key,owner,"gpu" if owner=="cpu" else "cpu",
                                           migration=True)
                    self.assertIsNotNone(packet)
                    ledger.receive()
                    owner=ledger.records[key].owner
                ledger.stage(key,owner,rgba=(1.,0.,0.,1.))
                ledger.audit()
            for packet in pending:
                ledger.mailbox.append(packet)
                self.assertIsNone(ledger.receive())
            self.assertTrue(ledger.quiescent())
            self.assertEqual(sum(ledger.counts.values()),128)

    def test_no_unearned_renderer_or_feature_qualification(self):
        root=Path(__file__).parent
        project=json.loads((root/"project.json").read_text())
        support=json.loads((root/"support_matrix.json").read_text())
        self.assertEqual(project["decisions"]["platform"],"native-windows")
        self.assertEqual(project["decisions"]["native_fidelity"],
                         "statistical-equivalence")
        self.assertFalse(project["qualification"]["renderer_implemented"])
        self.assertFalse(project["qualification"]["speed_measurement_allowed"])
        self.assertEqual(support["default"],"FALLBACK_ONLY")
        self.assertEqual(support["rules"],[])


if __name__=="__main__":
    unittest.main(verbosity=2)
