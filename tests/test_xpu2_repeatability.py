import unittest
from xpu2.images import compare_rgba
from tools.xpu2_repeatability import cases, successful


def image(values):
    return {"dimensions": (2, 2), "channels": {c: list(values) for c in "RGBA"}, "metadata": {}}


class ImageTests(unittest.TestCase):
    def test_coordinates_and_largest_difference(self):
        a, b = image([0, 0, 0, 0]), image([0, 1, 2, 0])
        result = compare_rgba(a, b)
        self.assertEqual(result["exactly_different_pixels"], 2)
        self.assertEqual(result["first_difference"]["x"], 1)
        self.assertEqual(result["first_difference"]["y_from_bottom"], 0)
        self.assertEqual(result["largest_differences"][0]["x"], 0)
        self.assertEqual(result["largest_differences"][0]["y_from_bottom"], 1)

    def test_same_image(self):
        self.assertEqual(compare_rgba(image([0, 1, 2, 3]), image([0, 1, 2, 3]))["status"], "passed")

    def test_alpha_is_not_ignored(self):
        a, b = image([0]*4), image([0]*4)
        b["channels"]["A"][0] = 1
        self.assertEqual(compare_rgba(a, b)["channels"]["A"]["failed_values"], 1)

    def test_nonfinite_values_rejected(self):
        with self.assertRaises(ValueError):
            compare_rgba(image([0]*4), image([float("nan")]*4))

    def test_metadata_mismatch(self):
        a, b = image([0]*4), image([0]*4)
        b["metadata"]["colorInteropID"] = "other"
        with self.assertRaises(ValueError):
            compare_rgba(a, b)

    def test_missing_channel(self):
        a, b = image([0]*4), image([0]*4)
        del b["channels"]["A"]
        with self.assertRaises(ValueError):
            compare_rgba(a, b)

    def test_wrong_channel_size(self):
        a, b = image([0]*4), image([0]*4)
        b["channels"]["R"] = [0]
        with self.assertRaises(ValueError):
            compare_rgba(a, b)


class StateTests(unittest.TestCase):
    def test_identical_state_has_no_fake_difference(self):
        from tools.xpu2_surface_probe import summarize_state
        result = summarize_state((1,1), [0,0,0], [0,0,0], {"first_difference":None,"largest_differences":[]})
        self.assertIsNone(result["largest_difference"])

    def test_state_is_sampled_at_beauty_target(self):
        from tools.xpu2_surface_probe import summarize_state
        row = {"x":1,"y_from_bottom":0}
        result = summarize_state((2,1), [0,0,0,1,2,3], [0,0,0,1,2,4],
                                 {"first_difference":row,"largest_differences":[row]})
        self.assertEqual(result["at_largest_beauty_difference"]["xpu"], [1,2,4])


class MatrixTests(unittest.TestCase):
    def test_fixed_case_order(self):
        self.assertEqual([case[2] for case in cases(12)], [1, 12, 1, 12])
        with self.assertRaises(ValueError):
            cases(1)

    def test_thread_mismatch_is_invalid(self):
        self.assertFalse(successful("vectorized", 12, 0, "Executing a vectorized render",
                                    "Thread(s),1\n", True)["passed"])

    def test_gpu_setup_is_not_evidence_of_work(self):
        self.assertFalse(successful("xpu", 1, 0, "Executing an XPU render\nGPU: Setup complete",
                                    "Thread(s),1\n", True)["passed"])

    def test_cpu_fallback_is_invalid(self):
        log = "Executing an XPU render\nGPU: Setup complete\nGPU bundled intersection ray utilization = 50%\nfalling back"
        self.assertFalse(successful("xpu", 1, 0, log, "Thread(s),1\n", True)["passed"])

    def test_valid_vector_run(self):
        self.assertTrue(successful("vectorized", 1, 0, "Executing a vectorized render",
                                   "Thread(s),1\n", True)["passed"])


if __name__ == "__main__":
    unittest.main()
