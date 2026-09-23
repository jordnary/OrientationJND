"""Audit recorded sessions and reproduce the completed study's descriptive results."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median, stdev

from analyze_results import estimate_threshold, summarize
from experiment_core import frames_for


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def close(actual, expected):
    if expected is None or isinstance(expected, (str, bool)):
        assert actual == expected, "Saved result differs from raw data."
    else:
        assert math.isclose(float(actual), expected, abs_tol=1e-10), "Saved result differs from raw data."


def quantile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def descriptive(values):
    return {"n": len(values), "mean": mean(values), "sd": stdev(values) if len(values) > 1 else 0,
            "median": median(values), "q1": quantile(values, .25), "q3": quantile(values, .75),
            "minimum": min(values), "maximum": max(values)}


def eligible(meta, totals):
    return (meta["mode"] == "formal" and meta["status"] == "completed"
            and meta["refresh_measured"] and totals["main_trials"] == meta["planned_main_trials"]
            and totals["trials_with_long_frames"] == 0 and totals["trials_with_invalid_timing"] == 0)


def isotonic_threshold(points):
    """Exploratory PAVA plus linear interpolation; independent of legacy gating.

    Fit hit probabilities with trial-count weights. Keep the observed control
    accuracy unchanged. Never modify observed counts or use fitted values as data.
    """
    blocks = []
    for index, point in enumerate(points):
        blocks.append([index, index, point["n_correct_different"], point["n_different"]])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            right = blocks.pop()
            left = blocks.pop()
            blocks.append([left[0], right[1], left[2] + right[2], left[3] + right[3]])
    fitted = [dict(point) for point in points]
    for start, end, hits, n in blocks:
        for index in range(start, end + 1):
            fitted[index]["different_accuracy"] = hits / n
            fitted[index]["balanced_accuracy"] = (hits / n + fitted[index]["same_accuracy_pooled"]) / 2
    result = estimate_threshold(fitted, eligible=True)
    result["method"] = "trial_count_weighted_PAVA_then_linear_angle_interpolation"
    result["interpretation"] = "Post hoc exploratory behavioral threshold; not a legacy automatic threshold or bias-free JND."
    return result, fitted


def audit_session(meta, rows):
    assert not meta["synthetic"], "Synthetic sessions cannot enter the study."
    assert meta["status"] == "completed", "Incomplete session requires explicit review."
    assert len(rows) == meta["completed_trials"], "Row count mismatch."
    config = meta["config"]
    for phase, expected in (("practice", meta["planned_practice_trials"]), ("main", meta["planned_main_trials"])):
        phase_rows = [r for r in rows if r["phase"] == phase]
        assert len(phase_rows) == expected, "Phase count mismatch."
        assert [int(r["trial_index"]) for r in phase_rows] == list(range(1, expected + 1)), "Trial order mismatch."
    for row in rows:
        for field in ("session_id", "participant", "mode"):
            assert row[field] == meta[field], "Session identity mismatch."
        same = int(row["is_same"])
        delta = float(row["signed_delta_deg"])
        assert (delta == 0) == bool(same), "Incorrect actual orientation difference."
        assert row["expected_key"] == ("f" if same else "j"), "Incorrect response mapping."
        assert int(row["correct"]) == int(row["response_key"] == row["expected_key"]), "Incorrect scoring."
        assert int(row["timed_out"]) == int(row["response_key"] == ""), "Incorrect timeout coding."
        assert int(row["long_frame_count"]) >= 0
        assert row["response_key"] in ("f", "j", "")
        if row["rt_s"]:
            assert 0 <= float(row["rt_s"]) <= config["timing"]["response_timeout_s"]
        actual = []
        for duration, start, end in (("first_duration_s", "first_onset_s", "first_offset_s"),
                                     ("interval_duration_s", "first_offset_s", "second_onset_s"),
                                     ("second_duration_s", "second_onset_s", "second_offset_s")):
            value = float(row[end]) - float(row[start])
            close(row[duration], value)
            actual.append(value)
        planned = [frames_for(config["timing"][key], meta["refresh_hz"]) / meta["refresh_hz"]
                   for key in ("first_stimulus_s", "interval_s", "second_stimulus_s")]
        valid = meta["timing_mode"] == "frames" and all(abs(a - b) <= 1.5 / meta["refresh_hz"] for a, b in zip(actual, planned))
        assert int(row["timing_valid"]) == int(valid), "Timing flag mismatch."
    main = [r for r in rows if r["phase"] == "main"]
    repeats = config["repeats_per_condition"][meta["mode"]]
    for delta in config["orientation_differences_deg"]:
        group = [r for r in main if float(r["condition_delta_deg"]) == delta]
        assert len(group) == repeats * 2
        assert sum(int(r["is_same"]) for r in group) == repeats
        for sign in (-1, 1):
            assert sum(float(r["signed_delta_deg"]) == sign * delta for r in group) == repeats // 2


def build_study(data_dir, results_dir, figures_dir=Path("pics")):
    output = results_dir / "study"
    output.mkdir(parents=True, exist_ok=True)
    inventory, participants, individual, all_main, flagged, hashes = [], [], [], [], [], []
    formal = []
    for metadata_path in sorted(data_dir.glob("*_session.json")):
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        session_id = meta["session_id"]
        trial_path = data_dir / (session_id + "_trials.csv")
        rows = read_csv(trial_path)
        audit_session(meta, rows)
        points, totals = summarize(rows)
        threshold = estimate_threshold(points, eligible(meta, totals))
        saved = json.loads((results_dir / session_id / "summary.json").read_text(encoding="utf-8"))
        for key, value in totals.items():
            close(saved["totals"][key], value)
        for key, value in threshold.items():
            close(saved["threshold"][key], value)
        saved_points = read_csv(results_dir / session_id / "accuracy_by_delta.csv")
        assert len(saved_points) == len(points)
        for old, new in zip(saved_points, points):
            for key, value in new.items():
                close(old[key] if old[key] != "" else None, value)
        for path in (metadata_path, trial_path):
            hashes.append({"file": "data/" + path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        inventory.append({"session_id": session_id, "participant": meta["participant"], "mode": meta["mode"],
                          "practice_trials": sum(r["phase"] == "practice" for r in rows),
                          **totals, "refresh_hz": meta["refresh_hz"],
                          "threshold_status": threshold["status"], "threshold_deg": threshold["estimate_deg"]})
        if meta["mode"] != "formal":
            continue
        main = [r for r in rows if r["phase"] == "main"]
        formal.append((meta, main, points))
        all_main.extend(main)
        rts = [float(r["rt_s"]) for r in main if r["rt_s"]]
        participants.append({"participant": meta["participant"], "session_id": session_id,
                             **totals, "n_correct": sum(int(r["correct"]) for r in main),
                             "n_correct_different": sum(int(r["correct"]) for r in main if not int(r["is_same"])),
                             "n_correct_same": sum(int(r["correct"]) for r in main if int(r["is_same"])),
                             "mean_rt_s": mean(rts), "median_rt_s": median(rts),
                             "refresh_hz": meta["refresh_hz"], "long_frame_total": sum(int(r["long_frame_count"]) for r in main),
                             "threshold_status": threshold["status"], "threshold_deg": threshold["estimate_deg"]})
        individual.extend({"participant": meta["participant"], **p} for p in points)
        for row in main:
            if int(row["long_frame_count"]) or not int(row["timing_valid"]):
                flagged.append({k: row[k] for k in ("participant", "session_id", "trial_index", "signed_delta_deg", "is_same", "correct", "long_frame_count", "timing_valid", "first_duration_s", "interval_duration_s", "second_duration_s")})
    assert formal, "No formal sessions."
    assert len({m["participant"] for m, _, _ in formal}) == len(formal), "Repeated participants require a different aggregation."
    assert all(m["config"] == formal[0][0]["config"] for m, _, _ in formal), "Configuration mismatch."
    exploratory = []
    fitted_rows = []
    for meta, main, points in formal:
        estimate, fitted = isotonic_threshold(points)
        retained_main = [r for r in main if not int(r["long_frame_count"]) and int(r["timing_valid"])]
        retained_pts, _ = summarize(retained_main)
        retained_estimate, _ = isotonic_threshold(retained_pts)
        exploratory.append({"participant": meta["participant"], "criterion": .75,
                            "estimate_deg": estimate["estimate_deg"], "status": estimate["status"],
                            "sensitivity_estimate_deg": retained_estimate["estimate_deg"],
                            "method": estimate["method"]})
        fitted_rows.extend({"participant": meta["participant"], "delta_deg": original["delta_deg"],
                            "observed_hit_rate": original["different_accuracy"],
                            "fitted_hit_rate": fit["different_accuracy"],
                            "observed_balanced_accuracy": original["balanced_accuracy"],
                            "fitted_balanced_accuracy": fit["balanced_accuracy"]}
                           for original, fit in zip(points, fitted))
    pooled, totals = summarize(all_main)
    for point in pooled:
        per_person = [r for r in individual if r["delta_deg"] == point["delta_deg"]]
        point["participant_mean_balanced_accuracy"] = mean(r["balanced_accuracy"] for r in per_person)
        point["participant_sd_balanced_accuracy"] = stdev(r["balanced_accuracy"] for r in per_person)
        point["participant_mean_different_accuracy"] = mean(r["different_accuracy"] for r in per_person)
        point["participant_sd_different_accuracy"] = stdev(r["different_accuracy"] for r in per_person)
        responses = [r for r in all_main if not int(r["is_same"]) and abs(float(r["signed_delta_deg"])) == point["delta_deg"] and r["rt_s"]]
        point["median_rt_different_s"] = median(float(r["rt_s"]) for r in responses)
        point["median_rt_correct_different_s"] = median(float(r["rt_s"]) for r in responses if int(r["correct"]))
    # Sensitivity analysis is post hoc and does not revise the original eligibility rule.
    retained = [r for r in all_main if not int(r["long_frame_count"]) and int(r["timing_valid"])]
    filtered_points, filtered_totals = summarize(retained)
    sensitivity = []
    for full, clean in zip(pooled, filtered_points):
        per_person = []
        for meta, main, _ in formal:
            kept = [r for r in main if not int(r["long_frame_count"]) and int(r["timing_valid"])]
            pts, _ = summarize(kept)
            per_person.append(next(p for p in pts if p["delta_deg"] == full["delta_deg"])["balanced_accuracy"])
        sensitivity.append({"delta_deg": full["delta_deg"], "full_n_different": full["n_different"],
                            "retained_n_different": clean["n_different"], "full_balanced_accuracy": full["balanced_accuracy"],
                            "retained_balanced_accuracy_pooled": clean["balanced_accuracy"],
                            "retained_balanced_accuracy_equal_participant": mean(per_person),
                            "difference_percentage_points": 100 * (clean["balanced_accuracy"] - full["balanced_accuracy"])})
    latency = []
    for meta, main, _ in formal:
        for delta in meta["config"]["orientation_differences_deg"]:
            group = [r for r in main if abs(float(r["signed_delta_deg"])) == delta and not int(r["is_same"])]
            for correct_only in (False, True):
                values = [float(r["rt_s"]) for r in group if r["rt_s"] and (not correct_only or int(r["correct"]))]
                latency.append({"participant": meta["participant"], "delta_deg": delta,
                                "subset": "correct" if correct_only else "all_responses", "n": len(values),
                                "mean_rt_s": mean(values) if values else None,
                                "median_rt_s": median(values) if values else None})
    timing = []
    for meta, main, _ in formal:
        for column, config_key in (("first_duration_s", "first_stimulus_s"), ("interval_duration_s", "interval_s"), ("second_duration_s", "second_stimulus_s")):
            values = [1000 * float(r[column]) for r in main]
            timing.append({"participant": meta["participant"], "segment": column,
                           "planned_ms": 1000 * meta["planned_frames"][config_key] / meta["refresh_hz"],
                           **{k + ("_ms" if k != "n" else ""): v for k, v in descriptive(values).items()}})
    rt_summary = {}
    for name, subset in (("all", all_main), ("correct", [r for r in all_main if int(r["correct"])]),
                         ("incorrect", [r for r in all_main if not int(r["correct"])]),
                         ("same", [r for r in all_main if int(r["is_same"])]),
                         ("different", [r for r in all_main if not int(r["is_same"])])):
        rt_summary[name] = descriptive([float(r["rt_s"]) for r in subset if r["rt_s"]])
    timing_summary = {key: descriptive([float(r[key]) * 1000 for r in all_main])
                      for key in ("first_duration_s", "interval_duration_s", "second_duration_s")}
    result = {"study_date": "2026-09-23", "participant_codes": [r["participant"] for r in participants],
              "n_formal_sessions": len(formal), "n_recorded_rows": sum(r["main_trials"] + r["practice_trials"] for r in inventory),
              "n_demo_main_trials": sum(r["main_trials"] for r in inventory if r["mode"] == "demo"),
              "n_practice_trials": sum(r["practice_trials"] for r in inventory), "totals": totals,
              "n_correct": sum(int(r["correct"]) for r in all_main),
              "same_correct": sum(int(r["correct"]) for r in all_main if int(r["is_same"])),
              "different_correct": sum(int(r["correct"]) for r in all_main if not int(r["is_same"])),
              "false_alarms": sum(r["response_key"] == "j" for r in all_main if int(r["is_same"])),
              "participants": participants, "by_delta": pooled, "sensitivity": sensitivity,
              "exploratory_thresholds": exploratory,
              "retained_totals": filtered_totals, "rt_summary_s": rt_summary, "timing_summary_ms": timing_summary,
              "n_rt_below_100ms": sum(0 <= float(r["rt_s"]) < .1 for r in all_main if r["rt_s"]),
              "audit": {"sessions_checked": len(inventory), "existing_summaries_match": True,
                        "existing_condition_tables_match": True, "raw_integrity_checks_passed": True},
              "interpretation": "Descriptive analysis of four participants; exploratory PAVA thresholds; no group JND or population significance test.",
              "input_hashes": hashes}
    for name, table in (("session_inventory", inventory), ("participant_summary", participants),
                        ("accuracy_by_delta", pooled), ("participant_by_delta", individual),
                        ("timing_sensitivity", sensitivity), ("response_latency", latency),
                        ("exploratory_thresholds", exploratory), ("isotonic_fits", fitted_rows),
                        ("timing_quality", timing), ("flagged_trials", flagged)):
        if table:
            write_csv(output / (name + ".csv"), table)
    (output / "study_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    plot_study(figures_dir, individual, pooled, sensitivity, latency, fitted_rows, exploratory)
    print("Study audit passed: 8 sessions; existing summaries and condition tables reproduced.")
    print("Formal trials:", len(all_main), "Correct:", result["n_correct"], "Flagged:", len(flagged))
    print("Study outputs: results/study/")
    return result


def plot_study(output, individual, pooled, sensitivity, latency, fitted_rows, exploratory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.facecolor": "white"})
    levels = [p["delta_deg"] for p in pooled]
    people = sorted({r["participant"] for r in individual})
    colors = ["#0072B2", "#D55E00", "#009E73", "#7B4AB0"]
    def accuracy_axes(ax):
        ax.set_xscale("log", base=2)
        ax.set_xticks(levels, [str(x).removesuffix(".0") for x in levels])
        ax.set_xlabel("Orientation difference (deg)")
        ax.set_ylim(0, 1.025)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(alpha=.18)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    ax = axes[0]
    ax.plot(levels, [p["different_accuracy"] for p in pooled], "o-", color=colors[0], label="Different-trial accuracy")
    ax.plot(levels, [p["balanced_accuracy"] for p in pooled], "s-", color=colors[1], label="Balanced accuracy")
    ax.axhline(pooled[0]["same_accuracy_pooled"], color=".4", linestyle=":", label="Same-trial accuracy")
    ax.axhline(.75, color=".55", linestyle="--", linewidth=.8)
    ax.set_title("A  Pooled descriptive results")
    ax.set_ylabel("Accuracy")
    ax.legend(fontsize=8, loc="lower right")
    ax = axes[1]
    for person, color in zip(people, colors):
        pts = [r for r in individual if r["participant"] == person]
        ax.plot(levels, [p["balanced_accuracy"] for p in pts], "o-", color=color, label=person, linewidth=1.3, markersize=4)
    ax.axhline(.75, color=".55", linestyle="--", linewidth=.8)
    ax.set_title("B  Individual balanced accuracy")
    ax.legend(ncol=2, fontsize=8, loc="lower right")
    for ax in axes:
        accuracy_axes(ax)
    fig.savefig(output / "accuracy_overview.png", dpi=220)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), layout="constrained")
    latency_limit = max(1.0, max(r["median_rt_s"] for r in latency if r["median_rt_s"] is not None) * 1.1)
    for ax, subset, title in zip(axes, ("all_responses", "correct"), ("A  All different-trial responses", "B  Correct different-trial responses")):
        for person, color in zip(people, colors):
            pts = [r for r in latency if r["participant"] == person and r["subset"] == subset]
            ax.plot(levels, [r["median_rt_s"] for r in pts], "o-", label=person, color=color, linewidth=1.2, markersize=4)
        ax.set_xscale("log", base=2)
        ax.set_xticks(levels, [str(x).removesuffix(".0") for x in levels])
        ax.set(xlabel="Orientation difference (deg)", ylabel="Median response time (s)", title=title, ylim=(0, latency_limit))
        ax.grid(alpha=.18)
        ax.legend(ncol=2, fontsize=8)
    fig.savefig(output / "response_latency.png", dpi=220)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.5, 3.6), layout="constrained")
    ax.plot(levels, [p["full_balanced_accuracy"] for p in sensitivity], "o-", label="All formal trials (n = 576)", color=colors[0])
    ax.plot(levels, [p["retained_balanced_accuracy_pooled"] for p in sensitivity], "s--", label="Exclude flagged trials (n = 566)", color=colors[1])
    accuracy_axes(ax)
    ax.set_ylim(.5, 1)
    ax.set_ylabel("Balanced accuracy")
    ax.legend(fontsize=9, loc="lower right")
    fig.savefig(output / "timing_sensitivity.png", dpi=220)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(10, 6), layout="constrained")
    for ax, person, color in zip(axes.flat, people, colors):
        pts = [r for r in fitted_rows if r["participant"] == person]
        estimate = next(r["estimate_deg"] for r in exploratory if r["participant"] == person)
        curve_x, curve_y = [], []
        for left, right in zip(pts, pts[1:]):
            for step in range(41):
                fraction = step / 40
                curve_x.append(left["delta_deg"] + fraction * (right["delta_deg"] - left["delta_deg"]))
                curve_y.append(left["fitted_balanced_accuracy"] + fraction * (right["fitted_balanced_accuracy"] - left["fitted_balanced_accuracy"]))
        ax.plot(curve_x, curve_y, "-", color=color, label="Isotonic fit + interpolation", linewidth=1.5)
        ax.scatter(levels, [r["observed_balanced_accuracy"] for r in pts], facecolors="white", edgecolors=color, s=34, label="Observed", zorder=4)
        ax.axhline(.75, color=".5", linestyle="--", linewidth=.8)
        if estimate is not None:
            ax.axvline(estimate, color=color, linestyle=":", linewidth=1)
            ax.scatter([estimate], [.75], marker="x", color=color, s=40, zorder=5)
        accuracy_axes(ax)
        ax.set_ylim(.4, 1.025)
        ax.set_title(f"{person}  |  Exploratory threshold = {estimate:.3f} deg", fontsize=10)
        ax.set_ylabel("Balanced accuracy")
        ax.legend(loc="lower right", fontsize=8)
    fig.savefig(output / "psychometric_fits.png", dpi=220)
    plt.close(fig)
    from matplotlib.patches import FancyBboxPatch
    fig, ax = plt.subplots(figsize=(10, 1.5), layout="constrained")
    labels = ["Fixation\n0.5 s", "Reference\n0.5 s", "Interval\n1.0 s", "Comparison\n0.5 s", "Response\nup to 5.0 s", "Intertrial\n0.3 s"]
    for i, label in enumerate(labels):
        ax.add_patch(FancyBboxPatch((i * 1.7, .28), 1.45, .68, boxstyle="round,pad=0.05", facecolor="#EFF4F7", edgecolor="#607580", linewidth=.9))
        ax.text(i * 1.7 + .725, .62, label, ha="center", va="center", fontsize=10)
        if i < len(labels) - 1:
            ax.annotate("", xy=((i + 1) * 1.7 - .08, .62), xytext=(i * 1.7 + 1.52, .62), arrowprops={"arrowstyle": "->", "color": "#465860"})
    ax.text(7.525, .06, "RT starts at response prompt onset", ha="center", fontsize=8, color="#465860")
    ax.set(xlim=(-.15, 10.1), ylim=(-.12, 1.15))
    ax.axis("off")
    fig.savefig(output / "trial_timeline.png", dpi=220)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--figures-dir", type=Path, default=Path("pics"))
    args = parser.parse_args()
    build_study(args.data_dir, args.results_dir, args.figures_dir)


if __name__ == "__main__":
    main()
