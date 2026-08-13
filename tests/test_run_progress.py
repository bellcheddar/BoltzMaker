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
