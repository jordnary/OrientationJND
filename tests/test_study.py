"""Check monotone fitting and its effect on exploratory threshold estimation."""

import unittest

from summarize_study import isotonic_threshold


def points(hits, counts, control=1.0):
    return [{"delta_deg": float(2 ** i), "n_correct_different": h,
             "n_different": n, "n_same_pooled": 72, "same_accuracy_pooled": control,
             "different_accuracy": h / n, "balanced_accuracy": (h / n + control) / 2}
            for i, (h, n) in enumerate(zip(hits, counts))]


class MonotoneThresholdTests(unittest.TestCase):
    def test_weighted_pooling_preserves_counts_and_input(self):
        observed = points([6, 2, 10], [10, 20, 10])
        _, fitted = isotonic_threshold(observed)
        self.assertAlmostEqual(fitted[0]["different_accuracy"], 8 / 30)
        self.assertAlmostEqual(fitted[1]["different_accuracy"], 8 / 30)
        self.assertEqual(observed[0]["different_accuracy"], .6)
        self.assertEqual(observed[1]["n_correct_different"], 2)

    def test_monotone_input_and_linear_crossing(self):
        estimate, fitted = isotonic_threshold(points([2, 8, 10], [10, 10, 10]))
        self.assertAlmostEqual(estimate["estimate_deg"], 1.5)
        self.assertEqual([p["different_accuracy"] for p in fitted], [.2, .8, 1.0])

    def test_boundary_thresholds_are_not_extrapolated(self):
        estimate, _ = isotonic_threshold(points([0, 1], [12, 12], .8))
        self.assertIsNone(estimate["estimate_deg"])
        estimate, _ = isotonic_threshold(points([8, 12], [12, 12]))
        self.assertIsNone(estimate["estimate_deg"])


if __name__ == "__main__":
    unittest.main()
