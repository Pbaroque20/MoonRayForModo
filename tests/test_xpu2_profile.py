"""Reject invalid performance evidence; no GPU needed for these checks."""
import importlib.util
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("profile_probe",ROOT/"tools/xpu2_profile_probe.py")
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class ProfileEvidenceTests(unittest.TestCase):
    def sample(self):
        values={key:1 for key in ("device_total_ns initialization_ns htod_ns launch_ns device_wait_ns dtoh_ns validation_ns diagnostic_io_ns worker_pack_ns queue_residence_ns collect_ns collect_wait_ns cpu_light_ns kernel_gpu_ns").split()}
        values.update(submitted=2,collected=2,batches=1,samples=16,accepted=16,replaced=16,unsupported=0,invalid=0,mismatch=0,errors=0)
        return values
    def test_exact_replacement(self):
        probe.validate_profile(self.sample(),"quiet_1")
    def test_pending_or_mismatched_results_rejected(self):
        for key,value in (("collected",1),("accepted",15),("replaced",15),("mismatch",1),("errors",1),("samples",0),("kernel_gpu_ns",0)):
            with self.subTest(key=key):
                p=self.sample();p[key]=value
                with self.assertRaises(ValueError):probe.validate_profile(p,"quiet_1")
    def test_missing_negative_and_noninteger_measurements_rejected(self):
        for value in (-1,1.5,True,None):
            with self.subTest(value=value):
                p=self.sample();p["htod_ns"]=value
                with self.assertRaises(ValueError):probe.validate_profile(p,"quiet_1")
        p=self.sample();del p["htod_ns"]
        with self.assertRaises(ValueError):probe.validate_profile(p,"quiet_1")
    def test_fallback_requires_evidence(self):
        p=self.sample()
        with self.assertRaises(ValueError):probe.validate_profile(p,"queue_full")
        p.update(submitted=0,collected=0,samples=0,accepted=0,replaced=0,batches=0)
        probe.validate_profile(p,"queue_full")
        p=self.sample()
        with self.assertRaises(ValueError):probe.validate_profile(p,"missing_ptx")
        p.update(errors=1,accepted=0,replaced=0)
        probe.validate_profile(p,"missing_ptx")
    def test_window_patch_composes_and_rejects_anchor_drift(self):
        from xpu2 import profile_patch,window_dispatch_patch
        code=profile_patch.apply((ROOT/"xpu2/native_lambert_queue.cc").read_text(),(ROOT/"xpu2/batched_bridge.cc").read_text(),(ROOT/"xpu2/profile_metrics.h").read_text())
        window_dispatch_patch.apply(code)
        with self.assertRaises(ValueError):window_dispatch_patch.apply(code.replace("bool mixed=false,split=false;","bool mixed=false;"))
    def test_window_patch_requires_unmodified_queue_signature(self):
        from xpu2 import window_dispatch_patch
        with self.assertRaises(ValueError):window_dispatch_patch.apply("")
    def test_patch_rejects_changed_native_anchors(self):
        from xpu2 import profile_patch
        q=(ROOT/"xpu2/native_lambert_queue.cc").read_text()
        b=(ROOT/"xpu2/batched_bridge.cc").read_text()
        h=(ROOT/"xpu2/profile_metrics.h").read_text()
        profile_patch.apply(q,b,h)
        with self.assertRaises(ValueError):profile_patch.apply(q.replace("void initialize() {", "void changed() {"),b,h)

if __name__=="__main__":unittest.main()
