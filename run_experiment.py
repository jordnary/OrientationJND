"""Open this file in PsychoPy Standalone Coder and press Run."""

import argparse
import re
import secrets
from datetime import datetime
from pathlib import Path

from experiment_core import SessionWriter, build_trials, frames_for, load_config


ROOT = Path(__file__).resolve().parent


class ExperimentAborted(Exception):
    pass


class Presenter:
    def __init__(self, win, config, refresh_hz, automated=False, frame_timing=True):
        from psychopy import core, visual
        from psychopy.hardware import keyboard

        self.win = win
        self.config = config
        self.refresh_hz = refresh_hz
        self.automated = automated
        self.frame_timing = frame_timing
        self.clock = core.Clock()
        self.kb = keyboard.Keyboard()
        self.fixation = visual.TextStim(win, text="+", height=0.025, color="white", autoLog=False)
        self.message = visual.TextStim(
            win, text="", font=config["display"]["font"], height=0.032,
            wrapWidth=1.45, color="white", autoLog=False,
        )
        gabor = config["gabor"]
        self.grating = visual.GratingStim(
            win, tex="sin", mask="gauss", size=gabor["size_height"],
            sf=gabor["spatial_frequency_cycles_per_stimulus"], contrast=gabor["contrast"],
            texRes=256, interpolate=True, autoLog=False,
        )

    def check_escape(self):
        if self.kb.getKeys(keyList=["escape"], waitRelease=False):
            raise ExperimentAborted()

    def instructions(self, text):
        self.message.text = text
        self.message.draw()
        self.win.callOnFlip(self.kb.clearEvents)
        self.win.flip()
        if self.automated:
            return
        while True:
            keys = self.kb.getKeys(keyList=["space", "escape"], waitRelease=False)
            if any(key.name == "escape" for key in keys):
                raise ExperimentAborted()
            if any(key.name == "space" for key in keys):
                return
            self.message.draw()
            self.win.flip()

    def show_frames(self, seconds, stimulus=False, message=None):
        if message is not None:
            self.message.text = message
        first_flip = None
        frame_count = 0
        while True:
            self.check_escape()
            if stimulus:
                self.grating.draw()
            if message is not None:
                self.message.draw()
            else:
                self.fixation.draw()
            flip_time = self.win.flip()
            if first_flip is None:
                first_flip = flip_time
            frame_count += 1
            if self.frame_timing:
                if frame_count >= frames_for(seconds, self.refresh_hz):
                    break
            elif flip_time - first_flip >= seconds:
                # Without a stable refresh estimate, use elapsed flip time.
                # The next scene starts roughly one refresh after this deadline.
                break
        return first_flip

    def response(self, expected_key):
        self.message.text = "方位相同：F        方位不同：J\n\n请只比较条纹的倾斜方向"
        self.message.draw()
        self.win.callOnFlip(self.kb.clock.reset)
        self.win.callOnFlip(self.kb.clearEvents)
        onset = self.win.flip()
        self.win.recordFrameIntervals = False
        # Automated runs are explicitly labelled and excluded from analysis.
        if self.automated:
            return expected_key, 0.0, onset
        deadline = self.config["timing"]["response_timeout_s"]
        while True:
            keys = self.kb.getKeys(keyList=["f", "j", "escape"], waitRelease=False)
            if any(key.name == "escape" for key in keys):
                raise ExperimentAborted()
            valid = [key for key in keys if key.rt is not None and 0 <= key.rt <= deadline]
            if valid:
                key = min(valid, key=lambda item: item.rt)
                return key.name, key.rt, onset
            if self.kb.clock.getTime() >= deadline:
                return "", None, onset
            self.message.draw()
            self.win.flip()

    def trial(self, trial):
        timing = self.config["timing"]
        # Configure the first stimulus before the fixation period.
        self.grating.ori = trial.reference_orientation_deg
        self.grating.phase = trial.first_phase
        self.show_frames(timing["fixation_s"])
        self.win.recordFrameIntervals = True
        start_index = len(self.win.frameIntervals)
        try:
            first_onset = self.show_frames(timing["first_stimulus_s"], stimulus=True)
            # Change the hidden grating during the blank interval, away from onset.
            self.grating.ori = trial.comparison_orientation_deg
            self.grating.phase = trial.second_phase
            first_offset = self.show_frames(timing["interval_s"])
            second_onset = self.show_frames(timing["second_stimulus_s"], stimulus=True)
            response_key, rt, second_offset = self.response(trial.expected_key)
        finally:
            self.win.recordFrameIntervals = False
        # Only score stimulus/interval timing, excluding the response wait.
        intervals = self.win.frameIntervals[start_index:]
        long_frames = sum(dt > 1.5 / self.refresh_hz for dt in intervals)
        durations = (first_offset - first_onset, second_onset - first_offset, second_offset - second_onset)
        expected = tuple(frames_for(timing[key], self.refresh_hz) / self.refresh_hz for key in (
            "first_stimulus_s", "interval_s", "second_stimulus_s"))
        timing_valid = self.frame_timing and all(
            abs(actual - target) <= 1.5 / self.refresh_hz for actual, target in zip(durations, expected))
        return {
            "response_key": response_key,
            "correct": int(response_key == trial.expected_key),
            "rt_s": "" if rt is None else round(rt, 6),
            "timed_out": int(not response_key),
            "first_onset_s": first_onset,
            "first_offset_s": first_offset,
            "second_onset_s": second_onset,
            "second_offset_s": second_offset,
            "first_duration_s": first_offset - first_onset,
            "interval_duration_s": second_onset - first_offset,
            "second_duration_s": second_offset - second_onset,
            "long_frame_count": long_frames,
            "timing_valid": int(timing_valid),
        }


def run(automated=False):
    from psychopy import gui, logging, visual, __version__

    logging.console.setLevel(logging.ERROR)
    config = load_config(ROOT / "config.json")
    info = {"participant": "P001", "mode": ["demo", "formal"]}
    if automated:
        info = {"participant": "TEST", "mode": "demo"}
    else:
        dialog = gui.DlgFromDict(
            info, title="方位差辨别实验", order=["participant", "mode"],
            labels={"participant": "匿名编号（例如 P001）", "mode": "模式（demo 演示 / formal 正式）"},
        )
        if not dialog.OK:
            return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", info["participant"]):
        raise ValueError("Use an anonymous participant code: 1-24 letters, digits, _ or -.")
    mode = info["mode"]
    seed = secrets.randbits(32)
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(4)
    practice = build_trials(config, mode, seed + 1, practice=True)
    trials = build_trials(config, mode, seed)
    if automated:
        practice, trials = practice[:2], trials[:4]
    metadata = {
        "session_id": session_id, "participant": info["participant"], "mode": mode,
        "synthetic": automated, "seed": seed, "psychopy_version": __version__,
        "task": "sequential_same_different", "config": config,
        "stimulus_units": "height", "spatially_calibrated": False,
        "planned_practice_trials": len(practice), "planned_main_trials": len(trials),
        "rt_origin": "response_prompt_onset_after_second_stimulus",
    }
    writer = SessionWriter(ROOT / ("tmp/smoke" if automated else "data"), session_id, metadata)
    win = None
    status = "error"
    try:
        win = visual.Window(
            size=config["display"]["window_size_px"],
            fullscr=mode == "formal" and config["display"]["full_screen_formal"],
            units="height", color=0, colorSpace="rgb", allowGUI=False,
            checkTiming=False, waitBlanking=True, autoLog=False,
        )
        win.mouseVisible = False
        measured_hz = win.getActualFrameRate(nIdentical=10, nMaxFrames=120, nWarmUpFrames=10)
        refresh_hz = measured_hz or config["display"]["fallback_refresh_hz"]
        writer.metadata.update({
            "refresh_hz": refresh_hz, "refresh_measured": measured_hz is not None,
            "timing_mode": "frames" if measured_hz else "elapsed_time_fallback",
            "window_size_px": [int(x) for x in win.size],
            "planned_frames": ({key: frames_for(value, refresh_hz) for key, value in config["timing"].items()
                                if key != "response_timeout_s"} if measured_hz else None),
        })
        presenter = Presenter(win, config, refresh_hz, automated, frame_timing=measured_hz is not None)
        writer.metadata["keyboard_backend"] = presenter.kb.getBackend()
        writer.save_metadata()
        if automated:
            # Preview capture occurs before timed trials.
            presenter.message.text = "方位差辨别实验\n\nF = 方位相同    J = 方位不同\n\n空格继续；Esc 退出"
            presenter.message.draw()
            win.flip()
            win.getMovieFrame(buffer="front")
            win.saveMovieFrames(str(ROOT / "tmp/smoke/instructions.png"))
            presenter.grating.draw()
            presenter.fixation.draw()
            win.flip()
            win.getMovieFrame(buffer="front")
            win.saveMovieFrames(str(ROOT / "tmp/smoke/gabor.png"))
        if not measured_hz:
            presenter.instructions("未测得稳定刷新率，当前使用经过时间控制呈现。\n\n本次仅用于检查流程，请先检查显示设置再采集正式数据。\n\n空格继续，Esc 退出")
        presenter.instructions(
            "方位差辨别实验\n\n"
            "每次先后出现两幅光栅，中间为空屏。\n"
            "请注视中央，只比较条纹的倾斜方向。\n"
            "条纹位置可能变化，位置变化不算方位变化。\n\n"
            "提示出现后：F = 方位相同，J = 方位不同。\n"
            f"请在 {config['timing']['response_timeout_s']:g} 秒内选择；不确定时也请尽量作答。\n\n"
            "先练习，再正式开始。空格继续；Esc 随时退出。"
        )
        for phase, block in (("practice", practice), ("main", trials)):
            if phase == "main":
                presenter.instructions(f"练习结束，接下来有 {len(block)} 个试次。\n\n本阶段不显示对错。\n\n空格开始；Esc 退出。")
            for index, trial in enumerate(block, 1):
                result = presenter.trial(trial)
                writer.append(
                    trial, session_id=session_id, participant=info["participant"], mode=mode,
                    phase=phase, trial_index=index, **result,
                )
                if phase == "practice":
                    feedback = "超时，请及时作答" if result["timed_out"] else ("正确" if result["correct"] else "错误")
                    presenter.show_frames(config["timing"]["feedback_s"], message=feedback)
                presenter.show_frames(config["timing"]["iti_s"])
                if phase == "main" and index % config["break_every"] == 0 and index < len(block):
                    presenter.instructions(f"已完成 {index} / {len(block)}\n\n可以稍作休息。空格继续。")
        status = "completed"
        presenter.instructions("实验完成，数据已保存。\n\n谢谢参与！按空格退出。")
    except ExperimentAborted:
        if status != "completed":
            status = "aborted"
    finally:
        try:
            writer.close(status)
        finally:
            if win is not None:
                win.close()
    print("Session status:", status)
    print("Saved completed trials:", writer.metadata["completed_trials"])


def main():
    parser = argparse.ArgumentParser(description="Orientation discrimination experiment")
    parser.add_argument("--smoke-test", action="store_true", help="Run 6 automated GUI trials with synthetic responses.")
    args = parser.parse_args()
    try:
        run(automated=args.smoke_test)
    except ImportError:
        print("Please run this script with PsychoPy Standalone Coder.")
        return 1
    except Exception as error:
        # Keep local environment details out of logs and console output.
        print("Experiment stopped:", type(error).__name__)
        print("Check config.json and the PsychoPy display setup. Completed rows are retained.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
