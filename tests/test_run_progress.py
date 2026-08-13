"""The run display: the ETA model, and what it does when it has nothing to go on.

Boltz gives no usable signal inside a single target -- its progress bar counts
dataloader items and one target is one item -- so a single-target campaign shows
0/1 from start to finish with a tqdm rate string that was written once and never
refreshed. These cover the estimate that replaced rich's TimeRemainingColumn,
which could only ever render "-:--:--" for exactly the same reason.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bm():
    source = (REPO_ROOT / "BoltzMaker.py").read_text()
    source = source.replace("_bootstrap_or_relaunch(sys.argv)", "pass  # neutralised for tests")
    module = types.ModuleType("boltzmaker_progress_under_test")
    module.__file__ = str(REPO_ROOT / "BoltzMaker.py")
    module.__spec__ = importlib.util.spec_from_loader(module.__name__, loader=None)
    sys.modules[module.__name__] = module
    exec(compile(source, str(REPO_ROOT / "BoltzMaker.py"), "exec"), module.__dict__)
    return module


def _history(tmp_path: pathlib.Path, records: list) -> pathlib.Path:
    path = tmp_path / ".boltzmaker_run_history.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return tmp_path


def test_no_history_yields_no_estimate(bm, tmp_path):
    assert bm._historical_seconds_per_target(tmp_path, "gpu") == (None, 0)


def test_seconds_per_target_comes_from_completed_targets(bm, tmp_path):
    campaign = _history(tmp_path, [
        {"targets_completed": 2, "duration_seconds": 200, "accelerator": "gpu"},
    ])
    assert bm._historical_seconds_per_target(campaign, "gpu") == (100.0, 1)


def test_runs_that_completed_nothing_are_ignored(bm, tmp_path):
    """A run that died in the first minute would otherwise drag the estimate to zero
    and promise an ETA of moments for an hours-long campaign."""
    campaign = _history(tmp_path, [
        {"targets_completed": 0, "duration_seconds": 30, "accelerator": "gpu"},
        {"targets_completed": 1, "duration_seconds": 600, "accelerator": "gpu"},
    ])
    assert bm._historical_seconds_per_target(campaign, "gpu") == (600.0, 1)


def test_the_estimate_is_a_median_not_a_mean(bm, tmp_path):
    """One swap-thrashing run took 11342s where its neighbours took ~3000s. A mean
    would let that single outlier set the expectation for every run afterwards."""
    campaign = _history(tmp_path, [
        {"targets_completed": 1, "duration_seconds": 100, "accelerator": "gpu"},
        {"targets_completed": 1, "duration_seconds": 120, "accelerator": "gpu"},
        {"targets_completed": 1, "duration_seconds": 12000, "accelerator": "gpu"},
    ])
    seconds, runs = bm._historical_seconds_per_target(campaign, "gpu")
    assert seconds == 120.0 and runs == 3


def test_a_different_accelerator_is_not_comparable(bm, tmp_path):
    campaign = _history(tmp_path, [
        {"targets_completed": 1, "duration_seconds": 60, "accelerator": "cpu"},
    ])
    assert bm._historical_seconds_per_target(campaign, "gpu") == (None, 0)
    assert bm._historical_seconds_per_target(campaign, "cpu") == (60.0, 1)


def test_a_corrupt_line_does_not_break_the_estimate(bm, tmp_path):
    campaign = tmp_path
    (campaign / ".boltzmaker_run_history.jsonl").write_text(
        "not json at all\n"
        + json.dumps({"targets_completed": 1, "duration_seconds": 300, "accelerator": "gpu"}) + "\n"
        + "\n"
    )
    assert bm._historical_seconds_per_target(campaign, "gpu") == (300.0, 1)


def test_it_reads_a_real_campaign_history(bm):
    """Against the run history a real campaign actually wrote, if it is present."""
    example = REPO_ROOT / "examples" / "5ht2_gq_panel" / ".boltzmaker_run_history.jsonl"
    if not example.is_file():
        pytest.skip("example run history not present in this worktree")
    seconds, runs = bm._historical_seconds_per_target(example.parent, "gpu")
    assert runs >= 1
    assert 60 < seconds < 24 * 3600, f"implausible seconds/target: {seconds}"


def test_duration_formatting_is_readable(bm):
    assert bm._format_duration(45) == "45s"
    assert bm._format_duration(605).startswith("10m")
    assert bm._format_duration(4411).startswith("1h")


# ===========================================================================
#  Run controls: quit, pause, resume
# ===========================================================================

@pytest.fixture
def tree(tmp_path):
    """A parent with two children, standing in for boltz and its dataloader workers."""
    import subprocess, sys as _sys, textwrap, time
    child = tmp_path / "child.py"
    child.write_text("import time\nwhile True: time.sleep(0.05)\n")
    parent = tmp_path / "parent.py"
    parent.write_text(textwrap.dedent(f"""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, r"{child}"])
        subprocess.Popen([sys.executable, r"{child}"])
        while True: time.sleep(0.05)
    """))
    proc = subprocess.Popen([_sys.executable, str(parent)], stdin=subprocess.DEVNULL)
    time.sleep(0.8)
    yield proc, child
    import psutil
    for process in psutil.process_iter(["cmdline"]):
        line = " ".join(process.info["cmdline"] or [])
        if str(child) in line or str(parent) in line:
            try:
                process.kill()
            except psutil.Error:
                pass


def _living_children(child_path) -> int:
    import psutil
    return sum(1 for p in psutil.process_iter(["cmdline"])
               if p.info["cmdline"] and str(child_path) in " ".join(p.info["cmdline"]))


def test_quit_leaves_no_worker_processes_behind(bm, tree):
    """proc.terminate() signals only the process Popen started. Boltz's dataloader
    workers are children, and terminating just the parent left them alive holding
    their share of RAM and the GPU -- measured, not assumed."""
    proc, child = tree
    assert _living_children(child) == 2, "fixture did not start its workers"

    controls = bm._RunControls(proc)
    survivors = controls.terminate_tree(timeout=10)

    import time
    time.sleep(0.4)
    assert survivors == []
    assert _living_children(child) == 0


def test_pause_freezes_the_tree_and_resume_continues_it(bm, tree, tmp_path):
    """Pause must be a real SIGSTOP, not a flag: the point is that an hour of
    diffusion is not thrown away and not recomputed."""
    import time
    proc, child = tree
    controls = bm._RunControls(proc)

    import psutil
    processes = [psutil.Process(proc.pid)] + psutil.Process(proc.pid).children(recursive=True)

    controls.pause()
    time.sleep(0.4)
    statuses = []
    for process in processes:
        try:
            statuses.append(process.status())
        except psutil.NoSuchProcess:
            pass
    assert statuses, "no processes to inspect"
    assert all(s == psutil.STATUS_STOPPED for s in statuses), statuses
    assert controls.paused

    controls.resume()
    time.sleep(0.3)
    resumed = []
    for process in processes:
        try:
            resumed.append(process.status())
        except psutil.NoSuchProcess:
            pass
    assert all(s != psutil.STATUS_STOPPED for s in resumed), resumed
    assert not controls.paused
    assert controls.paused_seconds > 0


def test_quitting_while_paused_still_shuts_down(bm, tree):
    """A stopped process cannot act on SIGTERM. Without resuming first, quitting a
    paused run would stall until the timeout escalated to SIGKILL."""
    import time
    proc, child = tree
    controls = bm._RunControls(proc)
    controls.pause()
    time.sleep(0.3)

    survivors = controls.terminate_tree(timeout=10)
    time.sleep(0.4)
    assert survivors == []
    assert _living_children(child) == 0


def test_paused_time_is_excluded_from_the_measured_rate(bm, tree):
    """A run paused over lunch is not evidence that targets take an extra hour --
    and the run history feeds every later ETA."""
    import time
    proc, _ = tree
    controls = bm._RunControls(proc)
    controls.pause()
    time.sleep(0.5)
    assert controls.paused_for() >= 0.4      # counted while still paused
    controls.resume()
    assert controls.paused_seconds >= 0.4
    assert controls.paused_for() == 0.0      # and not double-counted afterwards


def test_controls_are_unavailable_without_a_terminal(bm, tree):
    """Under nohup, a pipe or CI there is no keyboard, and putting a non-tty into
    cbreak mode fails -- so the run says so instead of appearing to offer keys."""
    proc, _ = tree
    controls = bm._RunControls(proc)
    assert controls.available is False       # pytest captures stdin
    controls.start()                          # must be a no-op, not an error
    controls.stop()
