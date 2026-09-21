"""Summarize observed same/different responses; never invent participant data."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parent
TARGET_ACCURACY = 0.75


def summarize(rows):
    """Timeouts count as errors. Practice is excluded from every statistic."""
    main_rows = [row for row in rows if row["phase"] == "main"]
    if not main_rows:
        raise ValueError("No completed main trials.")
    same_rows = [row for row in main_rows if int(row["is_same"]) == 1]
    if not same_rows:
        raise ValueError("No same-orientation control trials.")
    correct_rejection = mean(int(row["correct"]) for row in same_rows)
    different = defaultdict(list)
    for row in main_rows:
        if not int(row["is_same"]):
            different[abs(float(row["signed_delta_deg"]))].append(row)
    points = []
    for delta, group in sorted(different.items()):
        hit_rate = mean(int(row["correct"]) for row in group)
        reaction_times = [float(row["rt_s"]) for row in group if row["rt_s"] != ""]
        points.append({
            "delta_deg": delta, "n_different": len(group),
            "n_correct_different": sum(int(row["correct"]) for row in group),
            "different_accuracy": hit_rate,
            "n_same_pooled": len(same_rows), "same_accuracy_pooled": correct_rejection,
            "balanced_accuracy": (hit_rate + correct_rejection) / 2,
            "timeouts_different": sum(int(row["timed_out"]) for row in group),
            "mean_rt_different_s": mean(reaction_times) if reaction_times else None,
        })
    if not points:
        raise ValueError("No different-orientation trials.")
    totals = {
        "main_trials": len(main_rows), "same_trials": len(same_rows),
        "same_accuracy": correct_rejection,
        "false_alarm_rate": mean(row["response_key"] == "j" for row in same_rows),
        "same_timeout_rate": mean(int(row["timed_out"]) for row in same_rows),
        "overall_accuracy": mean(int(row["correct"]) for row in main_rows),
        "timeouts": sum(int(row["timed_out"]) for row in main_rows),
        "trials_with_long_frames": sum(int(row["long_frame_count"]) > 0 for row in main_rows),
        "trials_with_invalid_timing": sum(int(row["timing_valid"]) == 0 for row in main_rows),
    }
    return points, totals


def estimate_threshold(points, eligible=True):
    """An exploratory interpolation, not a fitted or bias-free sensory JND."""
    result = {"criterion": TARGET_ACCURACY, "estimate_deg": None, "status": "not_eligible"}
    if not eligible:
        return result
    if len(points) < 2 or any(p["n_different"] < 10 or p["n_same_pooled"] < 10 for p in points):
        return dict(result, status="insufficient_trials")
    scores = [point["balanced_accuracy"] for point in points]
    if any(right < left for left, right in zip(scores, scores[1:])):
        return dict(result, status="nonmonotonic_requires_fitting")
    if scores[0] >= TARGET_ACCURACY:
        return dict(result, status="at_or_below_smallest_delta")
    if scores[-1] < TARGET_ACCURACY:
        return dict(result, status="above_largest_delta_or_low_accuracy")
    for left, right in zip(points, points[1:]):
        low, high = left["balanced_accuracy"], right["balanced_accuracy"]
        if low < TARGET_ACCURACY <= high:
            estimate = left["delta_deg"] + (right["delta_deg"] - left["delta_deg"]) * (TARGET_ACCURACY - low) / (high - low)
            return dict(result, estimate_deg=estimate, status="exploratory_interpolation")
    return dict(result, status="no_bracket")


def analyze(csv_path, output_directory=None):
    csv_path = Path(csv_path)
    if not csv_path.name.endswith("_trials.csv"):
        raise ValueError("Select a *_trials.csv session file.")
    session_id = csv_path.name.removesuffix("_trials.csv")
    metadata_path = csv_path.with_name(session_id + "_session.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("synthetic"):
        raise ValueError("Synthetic smoke-test sessions are excluded from participant analysis.")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    points, totals = summarize(rows)
    eligible = (metadata["mode"] == "formal" and metadata["status"] == "completed"
                and metadata.get("refresh_measured", False)
                and totals["main_trials"] == metadata["planned_main_trials"]
                and totals["trials_with_long_frames"] == 0
                and totals["trials_with_invalid_timing"] == 0)
    threshold = estimate_threshold(points, eligible)
    output = Path(output_directory) if output_directory is not None else ROOT / "results" / session_id
    output.mkdir(parents=True, exist_ok=True)
    with (output / "accuracy_by_delta.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)
    summary = {
        "session_id": session_id, "mode": metadata["mode"], "session_status": metadata["status"],
        "definition": "balanced_accuracy = (different_accuracy + pooled_same_accuracy) / 2",
        "threshold": threshold, "totals": totals,
        "limitations": [
            "Same/different judgments depend on response criterion.",
            "Threshold is exploratory, not a fitted 2AFC or staircase JND.",
            "Stimulus size uses window-height units without visual-angle calibration.",
            "Timeouts count as errors; practice trials are excluded.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    plot_results(points, totals, threshold, metadata["mode"], output / "accuracy.png")
    return summary


def plot_results(points, totals, threshold, mode, target):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    deltas = [point["delta_deg"] for point in points]
    ax.plot(deltas, [point["different_accuracy"] for point in points], "o-", label="Different-trial accuracy")
    ax.plot(deltas, [point["balanced_accuracy"] for point in points], "s-", label="Balanced accuracy")
    ax.axhline(totals["same_accuracy"], color="gray", linestyle=":", label="Same-trial accuracy (pooled)")
    ax.axhline(TARGET_ACCURACY, color="black", linestyle="--", alpha=0.45, label="Exploratory 75% criterion")
    if threshold["estimate_deg"] is not None:
        ax.axvline(threshold["estimate_deg"], color="tab:red", linestyle=":", label="Interpolated threshold")
    ax.set(xlabel="Orientation difference (degrees)", ylabel="Accuracy", ylim=(-0.03, 1.03),
           title=f"Orientation discrimination ({mode}) | n = {totals['main_trials']}")
    ax.set_xticks(deltas, labels=[f"{delta:g}" for delta in deltas])
    ax.grid(alpha=0.15)
    ax.legend(loc="best", fontsize=9)
    fig.savefig(target, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Analyze an orientation experiment session.")
    parser.add_argument("csv_file", nargs="?")
    args = parser.parse_args()
    csv_file = args.csv_file
    try:
        if csv_file is None:
            from psychopy import gui
            selection = gui.fileOpenDlg(tryFilePath=str(ROOT / "data"), prompt="选择实验数据", allowed="CSV (*.csv)|*.csv")
            if not selection:
                return 0
            csv_file = selection[0]
        result = analyze(csv_file)
        print("Analysis complete. Outputs are in results/<session_id>/.")
        print("Main trials:", result["totals"]["main_trials"])
        print("Threshold status:", result["threshold"]["status"])
        if result["threshold"]["estimate_deg"] is not None:
            print("Exploratory threshold (deg):", round(result["threshold"]["estimate_deg"], 3))
        return 0
    except Exception as error:
        print("Analysis stopped:", type(error).__name__)
        print("Select a real *_trials.csv file with its matching *_session.json and completed main trials.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
