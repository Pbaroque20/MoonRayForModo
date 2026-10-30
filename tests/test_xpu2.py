"""Control-plane invariants only. These do not validate a GPU renderer."""
import tempfile
import unittest
from pathlib import Path
from xpu2.control import Change, SceneIndex, RenderGate, Resource, DemandQueue
from xpu2.reference import inventory, verify, identity, log_metrics, compare_values


class RevisionTests(unittest.TestCase):
    def initial(self):
        scene = SceneIndex()
        scene.apply({"material": ({Change.SHADING}, ()),
                     "mesh": ({Change.TOPOLOGY}, ("material",)),
                     "unrelated": ({Change.TOPOLOGY}, ())})
        return scene

    def test_transform_does_not_touch_unrelated_geometry(self):
        scene = self.initial()
        previous = scene.objects["unrelated"]
        delta = scene.apply({"mesh": ({Change.TRANSFORM}, ("material",))})
        self.assertEqual([o.identity for o in delta.changed], ["mesh"])
        self.assertEqual(delta.changed[0].changes, {Change.TRANSFORM})
        self.assertIs(scene.objects["unrelated"], previous)

    def test_rebinding_dependencies_forces_conservative_update(self):
        scene = self.initial()
        delta = scene.apply({"mesh": ({Change.TRANSFORM}, ())})
        self.assertEqual(delta.changed[0].changes, frozenset(Change))

    def test_new_geometry_cannot_be_transform_only(self):
        scene = SceneIndex()
        delta = scene.apply({"new": ({Change.TRANSFORM}, ())})
        self.assertIn(Change.TOPOLOGY, delta.changed[0].changes)

    def test_dependency_changes_invalidate_consumers(self):
        scene = self.initial()
        delta = scene.apply({"material": ({Change.SHADING}, ())})
        self.assertEqual({o.identity for o in delta.changed}, {"material", "mesh"})
        self.assertIn(Change.TOPOLOGY, scene.objects["mesh"].changes)

    def test_failed_transaction_does_not_publish(self):
        scene = self.initial()
        previous = scene.objects
        with self.assertRaises(ValueError):
            scene.apply({"mesh": ({Change.TRANSFORM}, ("missing",))})
        self.assertIs(scene.objects, previous)
        self.assertEqual(scene.revision, 1)

    def test_deleting_used_dependency_requires_reassignment(self):
        scene = self.initial()
        with self.assertRaises(ValueError):
            scene.apply({}, ("material",))
        delta = scene.apply({"mesh": ({Change.SHADING}, ())}, ("material",))
        self.assertEqual(delta.removed, ("material",))

    def test_no_change_does_not_advance_revision(self):
        scene = self.initial()
        self.assertEqual(scene.apply({}).revision, 1)

    def test_unknown_changes_rejected(self):
        with self.assertRaises(ValueError):
            SceneIndex().apply({"mesh": ({"new-magic-type"}, ())})

    def test_dependency_cycle_terminates_and_invalidates(self):
        scene = SceneIndex()
        scene.apply({"a": ({Change.SHADING}, ("b",)),
                     "b": ({Change.SHADING}, ("a",))})
        self.assertEqual(len(scene.apply({"a": ({Change.SHADING}, ("b",))}).changed), 2)


class GateTests(unittest.TestCase):
    def test_no_candidate_is_accidentally_enabled(self):
        gate = RenderGate("reference")
        self.assertEqual(gate.start(1).engine, "xpu")
        self.assertIn("no validated", gate.fallback_reason)

    def test_old_scene_result_and_duplicate_rejected(self):
        gate = RenderGate("reference")
        old = gate.start(1)
        self.assertTrue(gate.accept(old, "pixel-0/sample-0"))
        self.assertFalse(gate.accept(old, "pixel-0/sample-0"))
        new = gate.start(2)
        self.assertFalse(gate.accept(old, "pixel-1/sample-0"))
        self.assertTrue(gate.accept(new, "pixel-0/sample-0"))

    def test_fallback_is_new_empty_attempt_even_same_scene(self):
        gate = RenderGate("reference")
        first = gate.start(3)
        gate.accept(first, "0")
        fallback = gate.restart_reference("device lost")
        self.assertNotEqual(first, fallback)
        self.assertFalse(gate.completed)
        self.assertFalse(gate.accept(first, "1"))
        self.assertTrue(gate.accept(fallback, "0"))

    def test_cancel_rejects_late_results(self):
        gate = RenderGate("reference")
        first = gate.start(1)
        gate.cancel()
        self.assertFalse(gate.accept(first, "0"))


class DemandTests(unittest.TestCase):
    def setUp(self):
        self.gate = RenderGate("reference")
        self.attempt = self.gate.start(1)
        self.queue = DemandQueue(self.attempt)
        self.mesh = Resource("geometry", "mesh", 1)
        self.tile = Resource("texture", "albedo", 1, "mip2/0/0")

    def test_requests_deduplicated_across_paths(self):
        self.queue.defer(self.attempt, "shadow", [self.mesh])
        self.queue.defer(self.attempt, "reflection", [self.mesh])
        self.assertEqual(self.queue.requests(), (self.mesh,))
        self.assertFalse(self.queue.requests())
        self.assertEqual(set(self.queue.available(self.attempt, self.mesh)), {"shadow", "reflection"})

    def test_all_dependencies_required_before_resuming(self):
        self.queue.defer(self.attempt, "path", [self.mesh, self.tile])
        self.queue.requests()
        self.assertFalse(self.queue.available(self.attempt, self.mesh))
        self.assertEqual(self.queue.available(self.attempt, self.tile), ("path",))

    def test_old_revision_upload_does_not_release_path(self):
        self.queue.defer(self.attempt, "path", [self.mesh])
        self.queue.requests()
        self.assertFalse(self.queue.available(self.attempt, Resource("geometry", "mesh", 0)))
        self.assertIn("path", self.queue.waiting)

    def test_wrong_mip_does_not_release_path(self):
        self.queue.defer(self.attempt, "path", [self.tile])
        self.queue.requests()
        self.assertFalse(self.queue.available(self.attempt, Resource("texture", "albedo", 1, "mip3/0/0")))

    def test_canceled_attempt_upload_rejected(self):
        old = self.attempt
        self.queue.defer(old, "path", [self.mesh])
        self.queue.requests()
        new = self.gate.start(2)
        self.queue.reset(new)
        self.assertFalse(self.queue.available(old, self.mesh))
        self.assertFalse(self.queue.resident)

    def test_evicted_resource_can_be_requested_again(self):
        self.queue.defer(self.attempt, "a", [self.mesh])
        self.queue.requests()
        self.queue.available(self.attempt, self.mesh)
        self.queue.evict(self.mesh)
        self.queue.defer(self.attempt, "b", [self.mesh])
        self.assertEqual(self.queue.requests(), (self.mesh,))


class ReferenceTests(unittest.TestCase):
    def test_runtime_drift_and_added_plugin_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"moonray.exe").write_bytes(b"original")
            expected = inventory(root)
            verify(root, expected)
            (root/"new.dll").write_bytes(b"new")
            with self.assertRaises(ValueError):
                verify(root, expected)
            (root/"new.dll").unlink()
            (root/"moonray.exe").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify(root, expected)

    def test_runtime_inventory_includes_nested_ptx(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"moonray.exe").write_bytes(b"exe")
            (root/"shaders").mkdir()
            (root/"shaders/a.ptx").write_bytes(b"ptx")
            self.assertIn("shaders/a.ptx", inventory(root))

    def test_reference_environment_drops_renderer_overrides(self):
        from tools.xpu2_baseline import environment
        from unittest.mock import patch
        with patch.dict("os.environ", {"MOONRAY_MODO_SESSION": "stale", "OCIO": "other",
                                       "RDL2_DSO_PATH": "untracked", "SystemRoot": "C:/Windows"}):
            env = environment(Path("runtime"), Path("scratch"))
        self.assertNotIn("MOONRAY_MODO_SESSION", env)
        self.assertNotIn("OCIO", env)
        self.assertNotIn("untracked", env["RDL2_DSO_PATH"])

    def test_committed_reference_fixture_matches_its_lock(self):
        import json
        from xpu2.reference import digest_file
        root = Path(__file__).resolve().parents[1]/"xpu2/reference"
        lock = json.loads((root/"reference.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["identity"], identity(lock["contract"]))
        self.assertEqual(lock["contract"]["scene_sha256"], digest_file(root/"scene.rdla"))

    def test_contract_identity_is_order_independent(self):
        self.assertEqual(identity({"a": 1, "b": 2}), identity({"b": 2, "a": 1}))

    def test_renderer_timings_are_not_zero_when_unknown(self):
        self.assertEqual(log_metrics("")["renderer_timings_seconds"], {})
        self.assertIsNone(log_metrics("")["gpu_intersection_percent"])

    def test_stats_time_and_fallback(self):
        result = log_metrics("Loading scene = 00:01:02.345\nTotal render prep = 00:01:03.000\n"
                             "GPU: Setup complete\nfalling back to CPU\n")
        self.assertAlmostEqual(result["renderer_timings_seconds"]["Loading scene"], 62.345)
        self.assertTrue(result["cpu_fallback"])

    def test_parity_checks_dark_and_bright_values(self):
        self.assertTrue(compare_values([0, 100], [0.000001, 100.0001], .00001, .00001)["passed"])
        self.assertFalse(compare_values([0, 100], [.01, 100.0001], .00001, .00001)["passed"])

    def test_nan_infinity_and_missing_channels_rejected(self):
        for actual in ([float("nan")], [float("inf")], []):
            with self.assertRaises(ValueError):
                compare_values([0], actual, 0, 0)

    def test_negative_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            compare_values([0], [0], -1, 0)


if __name__ == "__main__":
    unittest.main()
