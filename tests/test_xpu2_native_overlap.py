"""Reject unsupported patch layouts and unproven native overlap claims."""
import importlib.util
from pathlib import Path
import unittest
from xpu2 import profile_patch, window_dispatch_patch, async_transfer_patch, packed_readback_patch, native_overlap_patch
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('overlap_profile', ROOT/'tools/xpu2_profile_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class NativeOverlapTests(unittest.TestCase):
    def test_guarded_bridge_composition(self):
        code = profile_patch.apply((ROOT/'xpu2/native_lambert_queue.cc').read_text(),
                                   (ROOT/'xpu2/batched_bridge.cc').read_text(),
                                   (ROOT/'xpu2/profile_metrics.h').read_text())
        code = packed_readback_patch.apply(async_transfer_patch.apply(window_dispatch_patch.apply(code)))
        native_overlap_patch.bridge(code)
        with self.assertRaises(ValueError):
            native_overlap_patch.bridge(code.replace('    if(windowPending) {', '    if(false) {'))
        with self.assertRaises(ValueError):
            native_overlap_patch.sampler('void drawBsdfSamples() {}')

    def sample(self):
        return dict(native_overlap_windows=3, native_light_pending_checks=27,
                    native_light_pending_observations=20, batches=3)

    def test_actual_publication_and_pending_observations_required(self):
        probe.validate_native_overlap(self.sample(), 'overlap_1', True)
        for key, value in [('native_overlap_windows', 2), ('native_light_pending_checks', 0),
                           ('native_light_pending_observations', 0), ('native_light_pending_observations', 28),
                           ('native_overlap_windows', True)]:
            row = self.sample(); row[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                probe.validate_native_overlap(row, 'overlap_1', True)

    def test_controls_cannot_use_early_publication(self):
        for label, overlap in [('packed_1', False), ('queue_full', True)]:
            with self.assertRaises(ValueError):
                probe.validate_native_overlap(self.sample(), label, overlap)
            row = {key: 0 for key in self.sample()}
            probe.validate_native_overlap(row, label, overlap)
