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

import pandas as pd
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


# ---------------------------------------------------------------------------
#  Per-ligand pocket override
# ---------------------------------------------------------------------------
#  A pocket is not purely a property of the receptor. Measured on GLP1R/GIPR: the
#  site where orforglipron binds GLP1R (7E14) and the site where LSN1 binds GIPR
#  (7RBT) share 3 residues out of ~60 once projected onto each other, so one
#  pocket per protein would force one of those chemotypes into the wrong site.

MD_WITH_OVERRIDE = """Settings:
Output folder: ./boltz_yamls
Predict affinity: yes
Pocket distance: 8

Protein: REC
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKR
Pocket contact: REC residue 10
Pocket contact: REC residue 11

Ligand: DEFAULTS
SMILES: c1ccccc1

Ligand: OVERRIDE
SMILES: CCO
Pocket contact: REC residue 40 for OVERRIDE
Pocket contact: REC residue 41 for OVERRIDE
"""


def test_a_ligand_pocket_overrides_the_proteins(bm, tmp_path):
    md = tmp_path / "campaign.md"
    md.write_text(MD_WITH_OVERRIDE)
    campaign = bm.parse_md(md)
    out = tmp_path / "yamls"; out.mkdir()
    bm.generate_yamls(campaign, out)

    import yaml as _yaml
    defaults = _yaml.safe_load((out / "REC_DEFAULTS.yaml").read_text())
    override = _yaml.safe_load((out / "REC_OVERRIDE.yaml").read_text())

    def pocket_of(doc):
        return next(c["pocket"] for c in doc["constraints"] if "pocket" in c)

    assert pocket_of(defaults)["contacts"] == [["REC", 10], ["REC", 11]]
    assert pocket_of(override)["contacts"] == [["REC", 40], ["REC", 41]]
    # and the campaign-level distance reaches both
    assert pocket_of(defaults)["max_distance"] == 8
    assert pocket_of(override)["max_distance"] == 8


def test_the_distance_is_omitted_when_it_matches_boltzs_own_default(bm, tmp_path):
    """So an existing campaign's YAML is byte-identical to what it was before this
    setting existed."""
    md = tmp_path / "c.md"
    md.write_text(MD_WITH_OVERRIDE.replace("Pocket distance: 8\n", ""))
    campaign = bm.parse_md(md)
    out = tmp_path / "y"; out.mkdir()
    bm.generate_yamls(campaign, out)
    import yaml as _yaml
    doc = _yaml.safe_load((out / "REC_DEFAULTS.yaml").read_text())
    pocket = next(c["pocket"] for c in doc["constraints"] if "pocket" in c)
    assert "max_distance" not in pocket


def test_a_pocket_for_an_unknown_ligand_is_an_error_not_a_silent_no_op(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text(MD_WITH_OVERRIDE.replace("for OVERRIDE", "for TYPO"))
    with pytest.raises(bm.MDParseError, match="no 'Ligand: TYPO' block exists"):
        bm.parse_md(md)


# ---------------------------------------------------------------------------
#  The pocket matrix
# ---------------------------------------------------------------------------
#  A protein may define several pockets, and every ligand is run against each of
#  them plus once unconstrained. That is what answers "where does this compound
#  actually want to sit" -- 7E14's site and 7RBT's site share 3 residues out of
#  ~60, so running a ligand against both is a real experiment, not a duplicate.

MD_MATRIX = """Settings:
Output folder: ./boltz_yamls
Predict affinity: yes
Pocket distance: 8

Protein: RECA
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKR
Pocket contact: RECA residue 10 as V6G
Pocket contact: RECA residue 11 as V6G
Pocket contact: RECA residue 40 as 41Y

Protein: RECB
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKR
Pocket contact: RECB residue 12 as V6G
Pocket contact: RECB residue 42 as 41Y

Ligand: orfo
SMILES: c1ccccc1
"""


def test_every_ligand_runs_against_every_pocket_plus_a_baseline(bm, tmp_path):
    md = tmp_path / "m.md"; md.write_text(MD_MATRIX)
    campaign = bm.parse_md(md)
    out = tmp_path / "y"; out.mkdir()
    manifest = bm.generate_yamls(campaign, out)
    stems = sorted(t.stem for t in manifest)
    assert stems == [
        "RECA_orfo", "RECA_orfo_41Y", "RECA_orfo_V6G",
        "RECB_orfo", "RECB_orfo_41Y", "RECB_orfo_V6G",
    ], stems


def test_each_matrix_target_carries_its_own_pocket(bm, tmp_path):
    import yaml as _yaml
    md = tmp_path / "m.md"; md.write_text(MD_MATRIX)
    campaign = bm.parse_md(md)
    out = tmp_path / "y"; out.mkdir()
    bm.generate_yamls(campaign, out)

    def pocket_of(stem):
        doc = _yaml.safe_load((out / f"{stem}.yaml").read_text())
        found = [c["pocket"] for c in doc.get("constraints", []) if "pocket" in c]
        return found[0] if found else None

    assert pocket_of("RECA_orfo_V6G")["contacts"] == [["RECA", 10], ["RECA", 11]]
    assert pocket_of("RECA_orfo_41Y")["contacts"] == [["RECA", 40]]
    assert pocket_of("RECB_orfo_V6G")["contacts"] == [["RECB", 12]]
    # the baseline is genuinely unconstrained
    assert pocket_of("RECA_orfo") is None
    assert pocket_of("RECB_orfo") is None


def test_a_campaign_without_named_pockets_is_unchanged(bm, tmp_path):
    """No baseline is invented for campaigns that predate the matrix: an unnamed
    pocket still means exactly one constrained target."""
    md = tmp_path / "c.md"; md.write_text(MD_WITH_OVERRIDE)
    campaign = bm.parse_md(md)
    out = tmp_path / "y"; out.mkdir()
    manifest = bm.generate_yamls(campaign, out)
    assert sorted(t.stem for t in manifest) == ["REC_DEFAULTS", "REC_OVERRIDE"]


# ---------------------------------------------------------------------------
#  Process recycling for MPS memory
# ---------------------------------------------------------------------------
#  Apple's MPS allocator only returns everything on process exit. Measured on a
#  live campaign: driver-held memory floored at ~20GB after one target and grew
#  ~1.9GB per target after that, while a single target in a fresh process peaked
#  at 47.6GB of a 55.7GB ceiling. That run had 0 out-of-memory skips in its first
#  four targets and 3 in its last four.

def test_targets_per_invocation_defaults_to_recycling(bm, tmp_path):
    md = tmp_path / "c.md"; md.write_text(MD_MATRIX)
    assert bm.parse_md(md).settings.targets_per_invocation == 4


def test_targets_per_invocation_is_settable(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text(MD_MATRIX.replace("Pocket distance: 8",
                                    "Pocket distance: 8\nTargets per invocation: 2"))
    assert bm.parse_md(md).settings.targets_per_invocation == 2


def test_zero_disables_recycling(bm, tmp_path):
    """0 restores the single-invocation behaviour campaigns had before this."""
    md = tmp_path / "c.md"
    md.write_text(MD_MATRIX.replace("Pocket distance: 8",
                                    "Pocket distance: 8\nTargets per invocation: 0"))
    assert bm.parse_md(md).settings.targets_per_invocation == 0


def test_a_bad_value_is_refused_rather_than_ignored(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text(MD_MATRIX.replace("Pocket distance: 8",
                                    "Pocket distance: 8\nTargets per invocation: lots"))
    with pytest.raises(bm.MDParseError, match="not a whole number"):
        bm.parse_md(md)


def test_the_batch_is_split_into_invocations_of_that_size(bm, tmp_path, monkeypatch):
    """The whole point: several processes, each starting with a clean allocator."""
    calls = []

    def fake_batch(pending, *a, **kw):
        calls.append([t.stem for t in pending])

    monkeypatch.setattr(bm, "_run_boltz_batch", fake_batch)
    monkeypatch.setattr(bm, "_target_complete", lambda *a, **kw: True)

    class T:
        def __init__(self, stem): self.stem, self.needs_affinity = stem, True
    batch = [T(f"T{i}") for i in range(9)]
    bm._run_boltz_batch_with_retry(
        batch, 9, 9, 0, tmp_path, tmp_path, tmp_path, tmp_path, 0, "gpu", tmp_path,
        1.0, 1, None, None, 1, None, None, 4096, 2, True, 4)

    assert [len(c) for c in calls] == [4, 4, 1], calls
    assert sum(len(c) for c in calls) == 9, "every target must still run exactly once"


def test_zero_runs_them_all_in_one_invocation(bm, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bm, "_run_boltz_batch", lambda pending, *a, **kw: calls.append(len(pending)))
    monkeypatch.setattr(bm, "_target_complete", lambda *a, **kw: True)

    class T:
        def __init__(self, stem): self.stem, self.needs_affinity = stem, True
    bm._run_boltz_batch_with_retry(
        [T(f"T{i}") for i in range(9)], 9, 9, 0, tmp_path, tmp_path, tmp_path, tmp_path,
        0, "gpu", tmp_path, 1.0, 1, None, None, 1, None, None, 4096, 2, True, 0)
    assert calls == [9]


def test_run_boltz_reaches_the_batch_runner(bm, tmp_path, monkeypatch):
    """Cover the real call path, not just the inner function.

    The first version of process recycling read `campaign.settings` inside
    run_boltz, where no `campaign` exists -- a NameError that every test above
    missed, because they all called _run_boltz_batch_with_retry directly. It
    surfaced on a live campaign instead. This test enters through run_boltz.
    """
    seen = {}

    def fake_retry(batch, *a, **kw):
        seen["invocation_size"] = a[-1]

    monkeypatch.setattr(bm, "_run_boltz_batch_with_retry", fake_retry)

    class T:
        stem, needs_affinity = "T0", True
    monkeypatch.setattr(bm, "_partition_targets", lambda manifest, pred_dir: ([], [T()]))

    bm.run_boltz(tmp_path / "yaml", tmp_path / "out", [T()], 0, "gpu", tmp_path,
                 targets_per_invocation=3)
    assert seen["invocation_size"] == 3


# ---------------------------------------------------------------------------
#  Unattended-run guards
# ---------------------------------------------------------------------------

def test_stall_timeout_is_between_a_slow_start_and_a_wasted_night(bm):
    """Model load + MSA setup is a few minutes; a wedged run costs the whole night."""
    assert 15 * 60 < bm._STALL_TIMEOUT_SECONDS <= 90 * 60


def test_patch_check_applies_before_it_verifies(bm, monkeypatch, tmp_path):
    """Patches used to be applied only by run_campaign.sh.

    A campaign started directly with `BoltzMaker.py all`, or one whose environment
    had been rebuilt (installing boltz reverts every patch), ran unpatched behind a
    WARN nobody was awake to read.
    """
    bm._PATCH_STATE["result"] = None
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "  applied  nan-guard\n", ""

    def fake_run(cmd, **kw):
        calls.append("--check" if "--check" in cmd else "apply")
        return Done()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    monkeypatch.setattr(bm, "SCRIPT_DIR", tmp_path)
    (tmp_path / "patches").mkdir()
    (tmp_path / "patches" / "apply_boltz_patches.py").write_text("")

    result = bm.check_boltz_patches()
    assert calls == ["apply", "--check"], "must apply first, then verify"
    assert result.status == "PASS"
    assert "repaired 1" in result.message, "a silent repair is worth saying out loud"


def test_patch_check_runs_once_per_process(bm, monkeypatch, tmp_path):
    """`all` calls it from preflight and again from run_boltz."""
    bm._PATCH_STATE["result"] = None
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(bm.subprocess, "run", lambda cmd, **kw: (calls.append(1), Done())[1])
    monkeypatch.setattr(bm, "SCRIPT_DIR", tmp_path)
    (tmp_path / "patches").mkdir()
    (tmp_path / "patches" / "apply_boltz_patches.py").write_text("")

    bm.check_boltz_patches()
    first = len(calls)
    bm.check_boltz_patches()
    assert len(calls) == first, "second call must be memoised, not re-scan every file"
    bm._PATCH_STATE["result"] = None


# ---------------------------------------------------------------------------
#  Summary table and the Pockets panel
# ---------------------------------------------------------------------------

def _frame(rows):
    import pandas as pd
    return pd.DataFrame(rows)


def test_affinity_group_comes_before_confidence(bm):
    """The table is read to answer "does it bind"; confidence qualifies that answer."""
    order = bm._FULL_TABLE_GROUP_ORDER
    assert order.index("Affinity") < order.index("Confidence")


def test_rows_rank_by_binder_probability(bm):
    df = _frame([{"family_id": "A", "ligand_id": "L1", "affinity_probability_binary": 0.2},
                 {"family_id": "A", "ligand_id": "L2", "affinity_probability_binary": 0.9},
                 {"family_id": "B", "ligand_id": "L3", "affinity_probability_binary": 0.5}])
    ordered, applied = bm._summary_table_order(df)
    assert applied
    assert list(ordered["ligand_id"]) == ["L2", "L3", "L1"]


def test_apo_rows_sink_rather_than_lead(bm):
    """An apo row has no binder probability at all; it must not head the ranking."""
    df = _frame([{"ligand_id": None, "affinity_probability_binary": float("nan")},
                 {"ligand_id": "L1", "affinity_probability_binary": 0.4}])
    ordered, _ = bm._summary_table_order(df)
    ids = list(ordered["ligand_id"])
    # pandas stores the missing ligand as NaN, not None, so compare on presence.
    assert ids[0] == "L1" and pd.isna(ids[1])


def test_ties_keep_generation_order(bm):
    """Many campaigns pin a lot of rows at 0.00 -- two runs must render identically."""
    df = _frame([{"ligand_id": f"L{i}", "affinity_probability_binary": 0.0} for i in range(5)])
    ordered, _ = bm._summary_table_order(df)
    assert list(ordered["ligand_id"]) == [f"L{i}" for i in range(5)]


def test_a_campaign_without_affinity_keeps_its_order(bm):
    df = _frame([{"ligand_id": "L1"}, {"ligand_id": "L2"}])
    ordered, applied = bm._summary_table_order(df)
    assert not applied and list(ordered["ligand_id"]) == ["L1", "L2"]


def test_family_dividers_are_dropped_once_ranked(bm):
    """They mean "a new family starts here", which is false once rows interleave."""
    df = _frame([{"family_id": "A", "family_group": "A", "ligand_id": "L1",
                  "affinity_probability_binary": 0.1},
                 {"family_id": "B", "family_group": "B", "ligand_id": "L2",
                  "affinity_probability_binary": 0.9}])
    assert "row-group-start" not in bm._build_full_table_html(df)


def test_sortable_headers_carry_the_indicator_styles(bm):
    """The glyph is fixed-width so switching it cannot rewrap the header row."""
    assert ".full-table thead tr:last-child th::after" in bm._BRAND_CSS
    assert "ft-sorted-asc" in bm._BRAND_CSS and "ft-sorted-desc" in bm._BRAND_CSS


POCKET_MD = """Settings:
Output folder: ./out
Predict affinity: yes
Pocket distance: 8

Protein: RECP
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ
Pocket contact: RECP residue 12 as V6G
Pocket contact: RECP residue 15 as V6G
Pocket contact: RECP residue 20 as 41Y

Ligand: LIG1
SMILES: CCO

Ligand: LIG2
SMILES: CCC
"""


def test_pockets_panel_groups_by_pocket_including_the_baseline(bm, tmp_path):
    """A matrix run is only legible if you can see what each stem suffix meant."""
    md = tmp_path / "c.md"; md.write_text(POCKET_MD)
    html = bm._build_pockets_panel_html(bm.parse_md(md))
    assert "<h2>Pockets</h2>" in html
    import re
    rows = re.findall(r"<tr><td>(.*?)</td>", html)
    assert rows == ["41Y", "V6G", "Unconstrained"], rows
    assert "2 named pocket(s) (41Y, V6G)" in html
    assert "within 8 A" in html, "the enforced distance is part of what the pocket means"


def test_every_ligand_appears_under_every_pocket(bm, tmp_path):
    md = tmp_path / "c.md"; md.write_text(POCKET_MD)
    html = bm._build_pockets_panel_html(bm.parse_md(md))
    assert html.count("LIG1, LIG2") == 3, "two named pockets plus the unconstrained baseline"


def test_contact_counts_are_per_pocket(bm, tmp_path):
    md = tmp_path / "c.md"; md.write_text(POCKET_MD)
    html = bm._build_pockets_panel_html(bm.parse_md(md))
    assert "1 residue(s)" in html and "2 residue(s)" in html


def test_unconstrained_is_named_as_a_choice_not_an_absence(bm, tmp_path):
    md = tmp_path / "c.md"; md.write_text(POCKET_MD)
    html = bm._build_pockets_panel_html(bm.parse_md(md))
    assert "ligand placed freely" in html


def test_a_campaign_with_no_pockets_still_describes_itself(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text("\n".join(l for l in POCKET_MD.splitlines()
                                if not l.startswith("Pocket contact:")))
    html = bm._build_pockets_panel_html(bm.parse_md(md))
    assert "No named pockets" in html


def test_apo_targets_are_not_listed_as_binding_a_pocket(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text(POCKET_MD.replace("Protein: RECP\n", "Protein: RECP\nLigands: none\n"))
    html = bm._build_pockets_panel_html(bm.parse_md(md))
    assert html == "", "a ligand-free campaign has nothing to place in a pocket"


def test_compare_sse_unpacks_the_pocket_code(bm):
    """_expand_targets yields three-tuples since pockets arrived.

    compare-sse still unpacked two, so `analyze` died with "too many values to
    unpack" on the first matrix campaign -- after all 26 predictions had been
    computed, which is the worst moment to find out.
    """
    import pathlib
    src = (pathlib.Path(bm.__file__).parent / "sse_comparison" / "cli.py").read_text()
    assert "for fam2, lig, code in fam_targets:" in src
    assert "for f, lig in all_targets" not in src


def test_compare_sse_builds_stems_with_the_shared_helper(bm):
    """A pocket-constrained target's file is named with its pocket code."""
    import pathlib
    src = (pathlib.Path(bm.__file__).parent / "sse_comparison" / "cli.py").read_text()
    assert "_target_stem(fam2, lig, code)" in src
    assert 'stem = f"{fam2.id}_{lig.id}"' not in src


# ---------------------------------------------------------------------------
#  A diverged ligand still scores well, so something has to notice
# ---------------------------------------------------------------------------

def _ligand_cif(tmp_path, points):
    """Minimal HETATM block in the column order BoltzMaker's own outputs use."""
    lines = []
    for i, (x, y, z) in enumerate(points):
        lines.append(f"HETATM {i} C C{i} . LIG . 1 ? A {x} {y} {z} 1 5 LIG LIG 7.0 1")
    path = tmp_path / f"t{len(points)}_{abs(hash(tuple(points))) % 9999}.cif"
    path.write_text("data_model\nloop_\n" + "\n".join(lines) + "\n")
    return path


def test_an_intact_ligand_is_not_flagged(bm, tmp_path):
    chain = [(1.5 * i, 0.0, 0.0) for i in range(12)]      # a 16A chain, bonds at 1.5A
    assert not bm._ligand_geometry_broken(_ligand_cif(tmp_path, chain))


def test_an_atom_flung_far_away_is_caught(bm, tmp_path):
    """The real failure: 65 atoms, of which several sit hundreds of Angstroms out."""
    chain = [(1.5 * i, 0.0, 0.0) for i in range(12)] + [(1453.0, 0.0, 0.0)]
    assert bm._ligand_geometry_broken(_ligand_cif(tmp_path, chain))


def test_an_atom_bonded_to_nothing_is_caught(bm, tmp_path):
    """Within the span limit, but not attached: 9A from its nearest neighbour."""
    chain = [(1.5 * i, 0.0, 0.0) for i in range(12)] + [(25.0, 0.0, 0.0)]
    assert bm._ligand_geometry_broken(_ligand_cif(tmp_path, chain))


def test_a_single_atom_ligand_is_not_a_failure(bm, tmp_path):
    """An ion has no bonds to check and is not evidence of divergence."""
    assert not bm._ligand_geometry_broken(_ligand_cif(tmp_path, [(0.0, 0.0, 0.0)]))


def test_a_missing_file_is_not_reported_as_broken_geometry(bm, tmp_path):
    """Absent outputs are MISSING_OUTPUTS' job; two flags for one cause help nobody."""
    assert not bm._ligand_geometry_broken(tmp_path / "not-here.cif")


def test_the_flag_explains_why_the_scores_cannot_be_trusted(bm):
    text = bm._FLAG_TEMPLATES["BROKEN_LIGAND_GEOMETRY"]
    assert "meaningless" in text and "confident" in text


def test_the_span_limit_sits_between_real_and_diverged(bm):
    """Measured: intact ligands spanned 11-17A, diverged ones 2154-2199A."""
    assert 20 < bm._LIGAND_SPAN_LIMIT_A < 100
