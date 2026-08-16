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


# ===========================================================================
#  The status rail
# ===========================================================================

def test_the_memory_gauge_is_read_against_the_thrash_point(bm):
    """Not against installed RAM. A 4-chain complex took ~65GB on a 64GB Mac and
    swap-thrashed for 20 minutes with no progress; measured against total memory
    that run would have looked merely "quite full" right up until it died. The
    ceiling is the same fraction the thrash warning already uses, so the gauge
    turns red where the log starts complaining."""
    empty, colour = bm._memory_gauge(0.0, 69)
    assert empty == "\u2591" * 8 and colour == bm._RICH_GREEN

    # 62.1GB is 0.90 * 69, the point the run is considered to be in trouble.
    full, colour = bm._memory_gauge(62.1, 69)
    assert full == "\u2593" * 8 and colour == bm._RICH_RED

    # Past the ceiling the gauge stays full rather than overflowing its column.
    over, _ = bm._memory_gauge(200.0, 69)
    assert len(over) == 8


def test_the_gauge_changes_colour_before_it_is_too_late(bm):
    green = bm._memory_gauge(21, 69)[1]
    amber = bm._memory_gauge(40, 69)[1]
    red = bm._memory_gauge(55, 69)[1]
    assert (green, amber, red) == (bm._RICH_GREEN, bm._RICH_AMBER, bm._RICH_RED)


def test_a_machine_with_no_reported_memory_does_not_divide_by_zero(bm):
    assert bm._memory_gauge(4.0, 0) == ("", bm._RICH_GREEN)


def test_compact_durations_fit_a_fixed_column(bm):
    """The estimate lives in a 13-character column. _format_duration renders
    "1h 13m 31s" -- eleven characters of which the last three are noise on an
    hour-long estimate, and enough to shift the column as it ticks."""
    assert bm._compact_duration(4411) == "1h13m"
    assert bm._compact_duration(605) == "10m05s"
    assert bm._compact_duration(45) == "45s"
    assert all(len(bm._compact_duration(s)) <= 7
               for s in (0, 59, 60, 3599, 3600, 86399, 359999))


def test_every_state_has_its_own_mark(bm):
    """One glyph in a fixed position, replacing the second spinner: two spinners
    turning in step for a single process said nothing the first had not."""
    assert set(bm._STATE_GLYPHS) == {"running", "paused", "stopping"}
    marks = [g for g in bm._STATE_GLYPHS.values()]
    assert len(set(marks)) == 3, "the states must be distinguishable at a glance"


def test_long_phase_names_are_shortened_rather_than_truncated(bm):
    """Truncating "structure prediction" and "affinity prediction" to ten
    characters yields "structure " and "affinity p" -- the word that tells them
    apart is the one that gets cut."""
    for full, short in bm._PHASE_SHORT.items():
        assert len(short) <= bm._LABEL_WIDTH, f"{short} does not fit the label column"
    assert bm._PHASE_SHORT["structure prediction"] != bm._PHASE_SHORT["affinity prediction"]


# ---------------------------------------------------------------------------
#  Measured per-target memory
# ---------------------------------------------------------------------------
#  Preflight's size check is a hand-set token threshold, and on a real campaign
#  it separated nothing: every target sat between 1307 and 1333 tokens, and both
#  the ones that completed and the ones that OOM'd were inside that band. These
#  records are what a size check should eventually be derived from.

def test_target_memory_is_recorded_one_json_line_per_target(bm, tmp_path):
    bm._record_target_memory(tmp_path, "GLP1R_LIG1", 41.372, tokens=1307)
    bm._record_target_memory(tmp_path, "GIPR_LIG4", 58.9, tokens=1310)

    lines = (tmp_path / bm.TARGET_MEMORY_FILE).read_text().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(l) for l in lines)
    assert first["target"] == "GLP1R_LIG1"
    assert first["peak_rss_gb"] == 41.37          # rounded, not truncated
    assert first["tokens"] == 1307
    assert first["total_ram_gb"] > 0              # so a record is comparable across machines
    assert second["target"] == "GIPR_LIG4"


def test_recording_memory_never_fails_a_run(bm, tmp_path):
    """A measurement is diagnostics, not the product. An unwritable path must not
    take down a campaign that is otherwise succeeding."""
    unwritable = tmp_path / "does" / "not" / "exist"
    bm._record_target_memory(unwritable, "GLP1R_LIG1", 41.0)   # must not raise
