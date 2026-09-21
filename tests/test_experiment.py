import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from analyze_results import analyze, estimate_threshold, summarize
from experiment_core import SessionWriter, build_trials, frames_for, load_config
from run_experiment import ExperimentAborted, Presenter


ROOT = Path(__file__).resolve().parents[1]


class TrialDesignTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")

    def test_formal_balance_and_correct_key(self):
        trials = build_trials(self.config, "formal", 19)
        self.assertEqual(len(trials), 144)
        counts = Counter((t.condition_delta_deg, t.signed_delta_deg) for t in trials)
        for delta in self.config["orientation_differences_deg"]:
            self.assertEqual(counts[delta, 0], 12)
            self.assertEqual(counts[delta, delta], 6)
            self.assertEqual(counts[delta, -delta], 6)
        for trial in trials:
            self.assertEqual(trial.expected_key, "f" if trial.signed_delta_deg == 0 else "j")
            self.assertAlmostEqual((trial.comparison_orientation_deg - trial.reference_orientation_deg) % 180,
                                   trial.signed_delta_deg % 180)

    def test_reproducible_seed_and_independent_phases(self):
        trials = build_trials(self.config, "demo", 19)
        self.assertEqual(trials, build_trials(self.config, "demo", 19))
        self.assertNotEqual(trials, build_trials(self.config, "demo", 20))
        self.assertTrue(all(t.first_phase != t.second_phase for t in trials))

    def test_practice_count_and_balance(self):
        trials = build_trials(self.config, "demo", 19, practice=True)
        self.assertEqual(len(trials), 8)
        self.assertEqual(sum(t.is_same for t in trials), 4)

    def test_invalid_counterbalance_is_rejected(self):
        self.config["repeats_per_condition"]["formal"] = 3
        with self.assertRaises(ValueError):
            build_trials(self.config, "formal", 19)

    def test_frame_rounding(self):
        self.assertEqual(frames_for(0.5, 60), 30)
        self.assertEqual(frames_for(1, 144), 144)
        self.assertEqual(frames_for(0.5, 59.94), 30)
        self.assertEqual(frames_for(0.001, 60), 1)

    def test_interrupted_session_preserves_flushed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = SessionWriter(directory, "test", {})
            trial = build_trials(self.config, "demo", 19)[0]
            writer.append(trial, phase="main", correct=1)
            with writer.csv_path.open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)
            writer.close("aborted")
            metadata = json.loads(writer.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "aborted")
            self.assertEqual(metadata["completed_trials"], 1)


def row(same, key, phase="main", delta=1):
    return {"phase": phase, "is_same": str(int(same)), "response_key": key,
            "correct": str(int(key == ("f" if same else "j"))),
            "signed_delta_deg": 0 if same else delta, "rt_s": "0.4" if key else "",
            "timed_out": str(int(not key)), "long_frame_count": "0", "timing_valid": "1"}


class AnalysisTests(unittest.TestCase):
    def test_always_different_is_chance_balanced_accuracy(self):
        points, totals = summarize([row(True, "j"), row(False, "j"), row(True, "f", phase="practice")])
        self.assertEqual(points[0]["balanced_accuracy"], 0.5)
        self.assertEqual(totals["main_trials"], 2)
        self.assertEqual(totals["false_alarm_rate"], 1)

    def test_timeouts_are_errors_not_false_alarms_or_rts(self):
        points, totals = summarize([row(True, ""), row(False, ""), row(False, "j")])
        self.assertEqual(totals["timeouts"], 2)
        self.assertEqual(totals["false_alarm_rate"], 0)
        self.assertEqual(points[0]["different_accuracy"], 0.5)
        self.assertEqual(points[0]["mean_rt_different_s"], 0.4)

    def test_threshold_interpolation_and_safeguards(self):
        points = [{"delta_deg": x, "balanced_accuracy": y, "n_different": 12, "n_same_pooled": 24}
                  for x, y in [(1, 0.6), (3, 0.9)]]
        self.assertAlmostEqual(estimate_threshold(points)["estimate_deg"], 2)
        self.assertIsNone(estimate_threshold(points, eligible=False)["estimate_deg"])
        points[1]["balanced_accuracy"] = 0.55
        self.assertEqual(estimate_threshold(points)["status"], "nonmonotonic_requires_fitting")
        points[1]["balanced_accuracy"] = 0.7
        self.assertIsNone(estimate_threshold(points)["estimate_deg"])
        points[0]["n_different"] = 1
        self.assertEqual(estimate_threshold(points)["status"], "insufficient_trials")

    def test_synthetic_sessions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "test_session.json"
            target.write_text(json.dumps({"synthetic": True}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Synthetic"):
                analyze(Path(directory) / "test_trials.csv")


class ResponseTests(unittest.TestCase):
    def presenter(self, keys, elapsed=0):
        presenter = Presenter.__new__(Presenter)
        presenter.automated = False
        presenter.config = {"timing": {"response_timeout_s": 5}}
        presenter.message = SimpleNamespace(text="", draw=lambda: None)
        presenter.kb = SimpleNamespace(
            clearEvents=lambda: None,
            clock=SimpleNamespace(reset=lambda: None, getTime=lambda: elapsed),
            getKeys=lambda **kwargs: keys,
        )
        presenter.win = SimpleNamespace(callOnFlip=lambda *args: None, flip=lambda: 10.0)
        return presenter

    def test_early_keys_are_ignored_and_earliest_valid_key_wins(self):
        keys = [SimpleNamespace(name="f", rt=-0.1), SimpleNamespace(name="j", rt=0.4), SimpleNamespace(name="f", rt=0.2)]
        self.assertEqual(self.presenter(keys).response("f"), ("f", 0.2, 10.0))

    def test_late_key_is_a_timeout(self):
        keys = [SimpleNamespace(name="f", rt=5.1)]
        self.assertEqual(self.presenter(keys, elapsed=5.2).response("f"), ("", None, 10.0))

    def test_escape_aborts(self):
        with self.assertRaises(ExperimentAborted):
            self.presenter([SimpleNamespace(name="escape", rt=0.1)]).response("f")

    def test_unstable_refresh_uses_elapsed_time_not_assumed_frame_count(self):
        presenter = Presenter.__new__(Presenter)
        presenter.refresh_hz = 60
        presenter.frame_timing = False
        presenter.check_escape = lambda: None
        presenter.fixation = SimpleNamespace(draw=lambda: None)
        times = iter(index / 144 for index in range(200))
        drawn = []
        def flip():
            drawn.append(next(times))
            return drawn[-1]
        presenter.win = SimpleNamespace(flip=flip)
        presenter.show_frames(0.5)
        self.assertGreaterEqual(drawn[-1] - drawn[0], 0.5)
        self.assertLessEqual(drawn[-1] - drawn[0], 0.5 + 1 / 144)


if __name__ == "__main__":
    unittest.main()
