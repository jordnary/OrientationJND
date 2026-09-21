"""Trial design and incremental storage, independent of PsychoPy."""

import csv
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path


TRIAL_FIELDS = [
    "session_id", "participant", "mode", "phase", "trial_index",
    "condition_delta_deg", "signed_delta_deg", "reference_orientation_deg",
    "comparison_orientation_deg", "is_same", "first_phase", "second_phase",
    "expected_key", "response_key", "correct", "rt_s", "timed_out",
    "first_onset_s", "first_offset_s", "second_onset_s", "second_offset_s",
    "first_duration_s", "interval_duration_s", "second_duration_s",
    "long_frame_count", "timing_valid",
]


def load_config(path):
    with Path(path).open(encoding="utf-8") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def validate_config(config):
    def positive(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0

    levels = config["orientation_differences_deg"]
    if not levels or any(not positive(x) or x >= 90 for x in levels):
        raise ValueError("Orientation differences must be between 0 and 90 degrees.")
    if len(levels) != len(set(levels)):
        raise ValueError("Orientation differences must be unique.")
    if not math.isfinite(config["reference_orientation_deg"]):
        raise ValueError("Reference orientation must be finite.")
    for mode in ("demo", "formal"):
        count = config["repeats_per_condition"][mode]
        if type(count) is not int or count < 2 or count % 2:
            raise ValueError("Repeats must be positive even integers, at least 2.")
    if type(config["practice_trials"]) is not int or config["practice_trials"] < 0 or config["practice_trials"] % 4:
        raise ValueError("Practice trials must be a nonnegative multiple of 4.")
    if type(config["break_every"]) is not int or config["break_every"] < 1:
        raise ValueError("Break interval must be a positive integer.")
    if any(not positive(value) for value in config["timing"].values()):
        raise ValueError("Durations must be finite and positive.")
    display = config["display"]
    if len(display["window_size_px"]) != 2 or any(type(x) is not int or x < 200 for x in display["window_size_px"]):
        raise ValueError("Window size must contain two pixel dimensions.")
    if not positive(display["fallback_refresh_hz"]):
        raise ValueError("Refresh rate must be finite and positive.")
    gabor = config["gabor"]
    if not positive(gabor["size_height"]) or gabor["size_height"] > 0.8:
        raise ValueError("Gabor size must be in (0, 0.8] height units.")
    if not positive(gabor["spatial_frequency_cycles_per_stimulus"]):
        raise ValueError("Spatial frequency must be positive.")
    if not positive(gabor["contrast"]) or gabor["contrast"] > 1:
        raise ValueError("Contrast must be in (0, 1].")


@dataclass(frozen=True)
class Trial:
    condition_delta_deg: float
    signed_delta_deg: float
    reference_orientation_deg: float
    comparison_orientation_deg: float
    is_same: bool
    first_phase: float
    second_phase: float

    @property
    def expected_key(self):
        return "f" if self.is_same else "j"


def build_trials(config, mode, seed, practice=False):
    """Pair each nonzero difficulty with equally many zero-difference trials."""
    validate_config(config)
    rng = random.Random(seed)
    levels = config["orientation_differences_deg"]
    repeats = config["repeats_per_condition"][mode]
    if practice:
        levels = [max(levels)]
        repeats = config["practice_trials"] // 2
    reference = float(config["reference_orientation_deg"]) % 180
    trials = []
    for delta in levels:
        for is_same in (True, False):
            for repeat in range(repeats):
                signed_delta = 0.0 if is_same else float(delta) * (1 if repeat % 2 else -1)
                trials.append(Trial(
                    condition_delta_deg=float(delta),
                    signed_delta_deg=signed_delta,
                    reference_orientation_deg=reference,
                    comparison_orientation_deg=(reference + signed_delta) % 180,
                    is_same=is_same,
                    first_phase=rng.random(),
                    second_phase=rng.random(),
                ))
    rng.shuffle(trials)
    return trials


def frames_for(seconds, refresh_hz):
    return max(1, int(seconds * refresh_hz + 0.5))


class SessionWriter:
    """Flush completed trials immediately; never collect machine information."""

    def __init__(self, directory, session_id, metadata):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.directory / (session_id + "_trials.csv")
        self.metadata_path = self.directory / (session_id + "_session.json")
        self.metadata = dict(metadata, status="running", completed_trials=0)
        self.handle = self.csv_path.open("x", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(self.handle, fieldnames=TRIAL_FIELDS)
        self.writer.writeheader()
        self.handle.flush()
        self.save_metadata()

    def save_metadata(self):
        temporary = self.metadata_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.metadata_path)

    def append(self, trial, **response):
        row = asdict(trial)
        row["is_same"] = int(trial.is_same)
        row["expected_key"] = trial.expected_key
        row.update(response)
        self.writer.writerow(row)
        self.handle.flush()
        self.metadata["completed_trials"] += 1

    def close(self, status):
        self.metadata["status"] = status
        self.handle.close()
        self.save_metadata()
