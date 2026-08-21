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
    # The baseline names no site, but is still held to its own receptor: co-folded
    # with a partner, an entirely free ligand docks onto the partner instead. It is
    # every residue of that receptor with `any`, so the nearest one satisfies it.
    for stem, receptor in (("RECA_orfo", "RECA"), ("RECB_orfo", "RECB")):
        baseline = pocket_of(stem)
        assert baseline is not None, f"{stem} could dock anywhere in the complex"
        assert baseline["force"] is True
        assert {c[0] for c in baseline["contacts"]} == {receptor}


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
    assert 60 * 60 <= bm._STALL_TIMEOUT_SECONDS <= 3 * 60 * 60


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


def test_rows_rank_by_predicted_pic50(bm):
    df = _frame([{"family_id": "A", "ligand_id": "L1", "pIC50": 7.2},
                 {"family_id": "A", "ligand_id": "L2", "pIC50": 11.2},
                 {"family_id": "B", "ligand_id": "L3", "pIC50": 9.5}])
    ordered, applied = bm._summary_table_order(df)
    assert applied
    assert list(ordered["ligand_id"]) == ["L2", "L3", "L1"]


def test_binder_probability_does_not_drive_the_ranking(bm):
    """It measured the pocket setup rather than the ligand: on a real campaign it
    correlated with pIC50 at r = +0.07, and put a confirmed potent binder below
    compounds it beats experimentally by orders of magnitude."""
    df = _frame([{"ligand_id": "weak_but_confident", "pIC50": 7.0,
                  "affinity_probability_binary": 0.95},
                 {"ligand_id": "potent", "pIC50": 11.2,
                  "affinity_probability_binary": 0.20}])
    ordered, _ = bm._summary_table_order(df)
    assert list(ordered["ligand_id"])[0] == "potent"


def test_apo_rows_sink_rather_than_lead(bm):
    """An apo row has no affinity at all; it must not head the ranking."""
    df = _frame([{"ligand_id": None, "pIC50": float("nan")},
                 {"ligand_id": "L1", "pIC50": 9.4}])
    ordered, _ = bm._summary_table_order(df)
    ids = list(ordered["ligand_id"])
    # pandas stores the missing ligand as NaN, not None, so compare on presence.
    assert ids[0] == "L1" and pd.isna(ids[1])


def test_ties_keep_generation_order(bm):
    """Many campaigns pin a lot of rows at 0.00 -- two runs must render identically."""
    df = _frame([{"ligand_id": f"L{i}", "pIC50": 8.0} for i in range(5)])
    ordered, _ = bm._summary_table_order(df)
    assert list(ordered["ligand_id"]) == [f"L{i}" for i in range(5)]


def test_a_campaign_without_affinity_keeps_its_order(bm):
    df = _frame([{"ligand_id": "L1"}, {"ligand_id": "L2"}])
    ordered, applied = bm._summary_table_order(df)
    assert not applied and list(ordered["ligand_id"]) == ["L1", "L2"]


def test_family_dividers_are_dropped_once_ranked(bm):
    """They mean "a new family starts here", which is false once rows interleave."""
    df = _frame([{"family_id": "A", "family_group": "A", "ligand_id": "L1", "pIC50": 7.1},
                 {"family_id": "B", "family_group": "B", "ligand_id": "L2", "pIC50": 9.9}])
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


# ---------------------------------------------------------------------------
#  The guidance-gradient clamp
# ---------------------------------------------------------------------------
#  Sanitising non-finite values was never enough: on GLP1R+orforglipron only 144
#  entries went non-finite and were zeroed, while their finite-but-enormous
#  neighbours were applied and catapulted four atoms to 49, 58, 737 and 2147A.
#  The clamp bounds the step. These tests exercise the arithmetic the patch
#  injects, which cannot be reached from here any other way.

def _clamp(gradient, factor=100.0):
    """The patch's expression, in numpy, over an (n, 3) array."""
    import numpy as np
    g = np.asarray(gradient, dtype=float)
    norms = np.linalg.norm(g, axis=-1, keepdims=True)
    positive = norms[norms > 0]
    if positive.size == 0:
        return g
    cap = np.median(positive) * factor
    scale = np.minimum(cap / np.clip(norms, 1e-12, None), 1.0)
    return g * scale


def test_a_healthy_gradient_is_untouched(bm):
    """A clean trajectory has to come out bit-identical, or the clamp changes
    every result rather than only the broken ones."""
    import numpy as np
    g = np.array([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0], [1.0, 1.0, 1.0]])
    assert np.allclose(_clamp(g), g)


def test_a_singular_atom_is_rescaled(bm):
    import numpy as np
    g = np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [1e12, 0.0, 0.0]])
    out = _clamp(g)
    assert out[3][0] < 1e12
    assert np.allclose(out[:3], g[:3]), "the atoms that were fine must not move"


def test_the_direction_survives_the_clamp(bm):
    """Rescaled, not zeroed: the force still says which way to go, and zeroing it
    was what left the structure uncorrected in the first place."""
    import numpy as np
    g = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [3.0, 4.0, 0.0] , [3e9, 4e9, 0.0]])
    out = _clamp(g)
    before, after = g[3] / np.linalg.norm(g[3]), out[3] / np.linalg.norm(out[3])
    assert np.allclose(before, after)


def test_an_all_zero_gradient_does_not_divide_by_zero(bm):
    import numpy as np
    g = np.zeros((4, 3))
    assert np.allclose(_clamp(g), g)


def test_the_factor_is_loose_enough_not_to_fight_real_forces(bm):
    """A buried clash legitimately pulls far harder than an exposed methyl, so the
    threshold rejects only the unarguable."""
    src = (__import__("pathlib").Path(bm.__file__).parent
           / "patches" / "apply_boltz_patches.py").read_text()
    assert "_BM_GRADIENT_CLAMP = 100.0" in src


def test_reapply_exists_because_detection_is_by_marker(bm):
    """Editing a patch body and re-running without it prints 'already applied' and
    changes nothing -- which would have shipped this clamp as a no-op."""
    src = (__import__("pathlib").Path(bm.__file__).parent
           / "patches" / "apply_boltz_patches.py").read_text()
    assert "--reapply" in src and "restored" in src


# ---------------------------------------------------------------------------
#  Keeping a ligand on its own receptor
# ---------------------------------------------------------------------------
#  Co-fold a receptor with a G protein and an unconstrained ligand may dock onto
#  either. Measured: GIPR's LSN1 run unconstrained made 359 contacts with GNB1 and
#  none at all with GIPR.

CONFINE_MD = """Settings:
Output folder: ./out
Predict affinity: yes

Protein: RECP
Sequence: MKTAYIAKQRQISFVKSHFSRQ
Partners: PART

Partner: PART
Sequence: MGSSHHHHHH

Ligand: LIG
SMILES: CCO
"""


def test_confining_is_on_by_default(bm, tmp_path):
    md = tmp_path / "c.md"; md.write_text(CONFINE_MD)
    assert bm.parse_md(md).settings.confine_to_receptor is True


def test_it_can_be_turned_off(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text(CONFINE_MD.replace("Predict affinity: yes",
                                     "Predict affinity: yes\nConfine to receptor: no"))
    assert bm.parse_md(md).settings.confine_to_receptor is False


def test_a_bad_value_is_refused(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text(CONFINE_MD.replace("Predict affinity: yes",
                                     "Predict affinity: yes\nConfine to receptor: maybe"))
    with pytest.raises(bm.MDParseError, match="not yes or no"):
        bm.parse_md(md)


def _pocket_of(bm, campaign, stem_wanted):
    for fam, lig, code in bm._expand_targets(campaign):
        if lig is None:
            continue
        if bm._target_stem(fam, lig, code) != stem_wanted:
            continue
        for con in bm._build_yaml_doc(fam, lig, campaign, code).get("constraints", []):
            if "pocket" in con:
                return con["pocket"]
    return None


def test_an_unpocketed_target_is_held_to_its_receptor(bm, tmp_path):
    md = tmp_path / "c.md"; md.write_text(CONFINE_MD)
    campaign = bm.parse_md(md)
    pk = _pocket_of(bm, campaign, "RECP_LIG")
    assert pk is not None, "no constraint at all -- the ligand could dock on the partner"
    assert pk["force"] is True, "boltz skips a pocket constraint that is not forced"
    assert {c[0] for c in pk["contacts"]} == {"RECP"}, "the partner must not be listed"
    # Boltz's own summing semantics, deliberately NOT `any`. Unioning the contacts
    # into a soft-min is the right meaning and the wrong force: measured live, it
    # returned one contact's worth of gradient (max 0.18-1.07) and a ligand fifty
    # angstroms away on a G protein did not move at all.
    assert not pk.get("any"), "union semantics make the restraint far too weak to act"


def test_turning_it_off_restores_free_placement(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text(CONFINE_MD.replace("Predict affinity: yes",
                                     "Predict affinity: yes\nConfine to receptor: no"))
    assert _pocket_of(bm, bm.parse_md(md), "RECP_LIG") is None


def test_the_restraint_has_a_workable_number_of_contacts(bm, tmp_path):
    """Sized to the force regime that demonstrably works on this system.

    The V6G pocket that reliably holds a ligand in its site has 62 contacts, and
    Boltz sums a penalty over each, so contact count is force. A sparse sweep of the
    receptor at the same count puts the whole-protein restraint in the same regime;
    listing every residue instead would be several times stronger and pull the ligand
    to the centroid rather than onto the surface.
    """
    md = tmp_path / "c.md"
    md.write_text(CONFINE_MD.replace("MKTAYIAKQRQISFVKSHFSRQ", "M" * 463))
    pk = _pocket_of(bm, bm.parse_md(md), "RECP_LIG")
    assert 40 <= len(pk["contacts"]) <= 80, f"{len(pk['contacts'])} contacts is out of regime"


def test_a_named_pocket_is_now_actually_enforced(bm, tmp_path):
    """Without force, boltz's featurizer skips the constraint entirely -- the contacts
    were a hint the model could ignore."""
    md = tmp_path / "c.md"
    md.write_text(CONFINE_MD + "\nPocket contact: RECP residue 5 as SITE\n")
    pk = _pocket_of(bm, bm.parse_md(md), "RECP_LIG_SITE")
    assert pk["force"] is True
    assert not pk.get("any"), "a named site keeps boltz's all-contacts semantics"


# --- Ligand pose: the docked ligand against an experimental one -------------
#
# The panel exists because of a measured failure: a GLP1R/orforglipron prediction
# scored ligand_iptm 0.940 and confidence 0.836 while sitting 9.4 A from where the
# crystal structure puts the same molecule in the same pocket. Nothing Boltz emits
# noticed. So the case these tests protect hardest is "right site, wrong pose" --
# a comparison that reports one number, or that pairs atoms by proximity, calls
# that a success.

_POSE_RESIDUES = ["ALA", "GLY", "SER", "VAL", "LEU"]


def _write_cif(path, receptor_chain, ligand, ligand_chain="LIG",
               ligand_comp="ETH", residues=None, offset=0.0):
    """A minimal mmCIF: one receptor chain of 40 CAs plus one ligand copy.

    The receptor is a helix-ish spiral rather than a straight line so the Kabsch fit
    is determined in all three axes -- collinear points leave a rotation free, and a
    test that superposes them would pass for the wrong reason.
    """
    import math
    residues = residues or _POSE_RESIDUES
    lines = ["data_test", "loop_"]
    columns = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_comp_id",
               "auth_seq_id", "auth_asym_id", "Cartn_x", "Cartn_y", "Cartn_z"]
    lines += [f"_atom_site.{c}" for c in columns]
    n = 1
    for i in range(40):
        angle = i * 1.75
        x = 2.3 * math.cos(angle) + offset
        y = 2.3 * math.sin(angle)
        z = 1.5 * i
        lines.append(f"ATOM {n} C CA {residues[i % len(residues)]} {i + 1} "
                     f"{receptor_chain} {x:.3f} {y:.3f} {z:.3f}")
        n += 1
    for element, (x, y, z) in ligand:
        lines.append(f"HETATM {n} {element} {element}{n} {ligand_comp} 1 "
                     f"{ligand_chain} {x:.3f} {y:.3f} {z:.3f}")
        n += 1
    path.write_text("\n".join(lines) + "\n")
    return path


#: Ethanol, at real bond lengths. Small enough to read, and asymmetric, so a flipped
#: copy is genuinely a different pose rather than the same one relabelled.
_ETHANOL = [("C", (0.0, 0.0, 30.0)), ("C", (1.50, 0.0, 30.0)), ("O", (2.14, 1.28, 30.0))]
_ETHANOL_SMILES = "CCO"


def _flipped(atoms):
    """The same molecule inverted through its own centroid: same site, wrong pose."""
    cx = sum(a[1][0] for a in atoms) / len(atoms)
    cy = sum(a[1][1] for a in atoms) / len(atoms)
    cz = sum(a[1][2] for a in atoms) / len(atoms)
    return [(e, (2 * cx - x, 2 * cy - y, 2 * cz - z)) for e, (x, y, z) in atoms]


def test_mmcif_record_type_comes_from_the_token_not_a_fixed_slice(bm, tmp_path):
    """`line[:6]` reads "ATOM 2" and drops every protein atom, silently.

    HETATM survives that bug by being exactly six characters, so the failure looks
    like "the reference has no receptor" rather than like a parsing mistake.
    """
    path = _write_cif(tmp_path / "s.cif", "R", _ETHANOL)
    rows = list(bm._mmcif_atom_rows(path))
    assert sum(1 for r in rows if r["_record"] == "ATOM") == 40
    assert sum(1 for r in rows if r["_record"] == "HETATM") == 3


def test_a_reproduced_pose_measures_as_reproduced(bm, tmp_path):
    reference = _write_cif(tmp_path / "ref.cif", "A", _ETHANOL)
    predicted = _write_cif(tmp_path / "pred.cif", "RECP", _ETHANOL, ligand_chain="LIG1")
    result = bm._pose_vs_experimental(predicted, reference, "ETH", _ETHANOL_SMILES,
                                      "RECP", "LIG1")
    assert "error" not in result, result
    assert result["site"] < 0.01 and result["pose"] < 0.01
    assert result["residues"] == 40


def test_right_site_wrong_orientation_is_visible_in_the_pose_not_the_site(bm, tmp_path):
    """The exact failure mode that got past every confidence score Boltz emits."""
    reference = _write_cif(tmp_path / "ref.cif", "A", _ETHANOL)
    predicted = _write_cif(tmp_path / "pred.cif", "RECP", _flipped(_ETHANOL),
                           ligand_chain="LIG1")
    result = bm._pose_vs_experimental(predicted, reference, "ETH", _ETHANOL_SMILES,
                                      "RECP", "LIG1")
    assert "error" not in result, result
    assert result["site"] < 0.01, "inverted through its own centroid -- same site"
    assert result["pose"] > 1.0, "and a different pose, which is the whole point"
    assert result["shape"] < 0.01, "the molecule's own conformation is unchanged"


def test_a_reference_of_a_different_protein_is_refused(bm, tmp_path):
    """Measured: 7E14 matched GIPR's numbering at 0.11 identity and was reported on.

    Without this gate the panel compares a GIPR prediction against a GLP1R crystal
    structure and calls the disagreement a result.
    """
    reference = _write_cif(tmp_path / "7XYZ.cif", "A", _ETHANOL,
                           residues=["TRP", "PHE", "TYR", "HIS", "ARG"])
    predicted = _write_cif(tmp_path / "pred.cif", "RECP", _ETHANOL, ligand_chain="LIG1")
    result = bm._pose_vs_experimental(predicted, reference, "ETH", _ETHANOL_SMILES,
                                      "RECP", "LIG1")
    assert result.get("error") == "7XYZ is not a structure of RECP"


def test_the_receptors_own_chain_is_not_pooled_with_the_rest_of_the_complex(bm, tmp_path):
    """A complex numbers its G-protein chains from 1 too.

    Reading every reference chain into one dict lets the last one read overwrite the
    receptor, and the fit is then made partly against the wrong protein -- which
    still returns a plausible number.
    """
    import math
    reference = _write_cif(tmp_path / "ref.cif", "A", _ETHANOL)
    decoy = ["data_x"] + reference.read_text().splitlines()[1:]
    extra = []
    for i in range(40):
        extra.append(f"ATOM {900 + i} C CA TRP {i + 1} B "
                     f"{80.0 + i:.3f} {90.0:.3f} {100.0:.3f}")
    reference.write_text("\n".join(decoy + extra) + "\n")
    predicted = _write_cif(tmp_path / "pred.cif", "RECP", _ETHANOL, ligand_chain="LIG1")
    result = bm._pose_vs_experimental(predicted, reference, "ETH", _ETHANOL_SMILES,
                                      "RECP", "LIG1")
    assert "error" not in result, result
    assert result["residues"] == 40 and result["pose"] < 0.01


def test_an_unconstrained_target_still_finds_its_experimental_twin(bm, tmp_path):
    """The baseline is the comparison worth having, and it carries no pocket code."""
    (tmp_path / "reference").mkdir()
    _write_cif(tmp_path / "reference" / "1ABC.cif", "A", _ETHANOL)
    references = bm._reference_structures(tmp_path)
    assert set(references) == {"ETH"}
    ligand = types.SimpleNamespace(id="LIG1", smiles=_ETHANOL_SMILES)
    comp, path = bm._reference_ligand_for(ligand, None, references, tmp_path)
    assert comp == "ETH" and path.name == "1ABC.cif"


def test_a_different_molecule_of_the_same_size_is_not_mistaken_for_the_twin(bm, tmp_path):
    (tmp_path / "reference").mkdir()
    _write_cif(tmp_path / "reference" / "1ABC.cif", "A", _ETHANOL)
    references = bm._reference_structures(tmp_path)
    propane = types.SimpleNamespace(id="LIG1", smiles="CCC")   # C3 against ethanol's C2O
    comp, _path = bm._reference_ligand_for(propane, None, references, tmp_path)
    assert comp is None


def test_the_pose_panel_is_silent_without_reference_structures(bm, tmp_path):
    """An empty card would only pose a question the campaign cannot answer."""
    md = tmp_path / "c.md"
    md.write_text(POCKET_MD)
    assert bm._build_ligand_pose_panel_html(bm.parse_md(md), tmp_path) == ""


# --- the same pairs, drawn in the offline report ----------------------------
#
# The dashboard is the artefact that travels on its own, so the pair viewer is built
# twice: fetched + Mol* in the hosted explorer, inlined + 3Dmol here. Both read the
# same measured coordinates out of boltz_pose_pairs/, because a picture computed
# separately from the number beside it can disagree with it.

def _pose_pair_files(tmp_path, stem="T1", pocket="SITE1"):
    import json
    out = tmp_path / "boltz_pose_pairs"
    out.mkdir(exist_ok=True)
    for which in ("pred", "ref"):
        (out / f"{stem}_{which}.cif").write_text(f"data_{which}\nHETATM 1 C\n")
    (out / "index.json").write_text(json.dumps({"pairs": [{"stem": stem}]}))
    return [{"stem": stem, "family": "RECP", "ligand": "LIG1", "pocket": pocket,
             "reference": "1ABC", "ligand_code": "ETH", "site": 0.5, "pose": 1.2,
             "shape": 0.4, "atoms": 3, "residues": 40}]


def test_the_offline_report_draws_the_pairs_too(bm, tmp_path):
    measured = _pose_pair_files(tmp_path)
    markup, script = bm._pose_pair_viewers_html(measured, tmp_path)
    assert "pose-tile-viewer" in markup and "Pocket SITE1" in markup
    assert "$3Dmol" in script and "createViewer" in script


def test_the_offline_pair_coordinates_are_inlined_not_fetched(bm, tmp_path):
    """boltz_dashboard.html is meant to survive being emailed on its own.

    A viewer that reads two files beside it shows nothing the moment the report is
    moved, which is the failure the vendored Plotly and 3Dmol already exist to avoid.
    """
    measured = _pose_pair_files(tmp_path)
    _markup, script = bm._pose_pair_viewers_html(measured, tmp_path)
    assert "data_pred" in script and "data_ref" in script
    assert "fetch(" not in script


def test_a_pair_with_no_coordinates_on_disk_is_not_given_a_frame(bm, tmp_path):
    """An index entry can outlive its files -- a campaign re-analysed after its
    references changed measures fewer pairs than its last index names."""
    measured = _pose_pair_files(tmp_path)
    (tmp_path / "boltz_pose_pairs" / "T1_pred.cif").unlink()
    assert bm._pose_pair_viewers_html(measured, tmp_path) == ("", "")


def test_the_offline_report_does_not_draw_every_pair_at_once(bm, tmp_path):
    """A browser silently kills the oldest WebGL context rather than refusing a new
    one, so an uncapped grid blacks out the earliest frames while the last look fine.
    This report already spends one context per target on the binding-site panels."""
    measured = _pose_pair_files(tmp_path)
    _markup, script = bm._pose_pair_viewers_html(measured, tmp_path)
    assert "IntersectionObserver" in script, "frames are drawn on scroll"
    assert f"budget = {bm.POSE_VIEWER_BUDGET}" in script
    assert "pose-tile-draw" in script, "past the budget, a button rather than a black frame"


def test_the_viewer_grid_lands_inside_the_pose_card(bm, tmp_path):
    """Inside the card, not after it: a viewer in a card of its own reads as a
    separate finding rather than as the picture of the table above it."""
    md = tmp_path / "c.md"
    md.write_text(POCKET_MD)
    panel = bm._build_ligand_pose_panel_html(
        bm.parse_md(md), tmp_path,
        measured=_pose_pair_files(tmp_path), errors=set(),
        viewer_html="<div class='pose-pane'>MARKER</div>")
    assert panel.count("md-card") == 1
    assert panel.index("MARKER") < panel.rindex("</div>")
    assert panel.index("</table>") < panel.index("MARKER")


def test_the_dashboards_mobile_rules_come_last_in_its_stylesheet(bm):
    """The same trap brand.css has a test for, in BoltzMaker's own stylesheet.

    A media query carries no extra specificity, so a plain rule written below it
    beats it at every width -- and the pose grid's phone rule was written beside its
    section, above every rule that follows.
    """
    import re as _re
    css = bm._DASHBOARD_CSS if hasattr(bm, "_DASHBOARD_CSS") else None
    if css is None:                       # the stylesheet is an unnamed literal
        source = pathlib.Path(bm.__file__).read_text()
        css = source[source.index(".md-3dmol-viewer {"):source.index("_BRAND_HEADER")]
    first_media = css.index("@media (max-width: 768px)")
    for rule in _re.finditer(r"^\.[a-zA-Z][\w.-]*\s*(,|\{)", css[first_media:], _re.M):
        raise AssertionError(
            f"a plain rule ({rule.group(0).strip()}) is defined after the mobile block")


def test_tightening_a_pocket_does_not_retune_the_baseline_arm(bm, tmp_path):
    """`Pocket distance:` must not reach the confine-to-receptor sweep.

    The two constraints ask different questions. A named pocket asks "which site",
    and tightening it is the point -- 8A to 4A took a measured pose from 9.51A to
    2.56A. The sweep asks "which protein" of residues scattered the length of the
    chain, where no ligand can be near all of them. Coupling them meant that
    changing the pocket silently changed the unconstrained baseline the pocket was
    about to be compared against, which is exactly the variable a matrix campaign
    exists to hold still.
    """
    md = tmp_path / "c.md"
    md.write_text("""Settings:
Output folder: ./y
Pocket distance: 4

Protein: RECP
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ
Pocket contact: RECP residue 12 as SITE

Ligand: LIG1
SMILES: CCO
""")
    campaign = bm.parse_md(md)
    named, sweep = None, None
    for fam, lig, code in bm._expand_targets(campaign):
        doc = bm._build_yaml_doc(fam, lig, campaign, code)
        pocket = [c["pocket"] for c in doc.get("constraints", []) if "pocket" in c][0]
        if code:
            named = pocket
        else:
            sweep = pocket
    assert named["max_distance"] == 4.0, "the named pocket honours the setting"
    assert sweep["max_distance"] == bm.CONFINE_DISTANCE_A == 8.0


def test_the_two_widest_column_groups_start_collapsed(bm):
    """Confidence and Interactions are most of the table's width and neither is what
    it is opened to answer. Each keeps one column showing so the group is still
    readable at a glance, and the header says how many are hidden."""
    assert bm._COLLAPSED_GROUPS == {"Confidence": "confidence_score",
                                    "Interactions": "plip_total_count"}


def test_an_apo_row_says_apo_rather_than_not_applicable(bm):
    """"Apo" says what the row is; "N/A" said only that a ligand id could not be
    shown, which is the least interesting true thing about it."""
    import pandas as _pd
    df = _pd.DataFrame([
        {"run": 1, "family_group": "RECP", "ligand_id": "LIG1", "pocket": "V6G",
         "confidence_score": 0.8, "flags": ""},
        {"run": 2, "family_group": "RECP", "ligand_id": None, "pocket": None,
         "confidence_score": 0.7, "flags": ""},
    ])
    html = bm._build_full_table_html(df)
    assert ">Apo<" in html, "the ligand cell names the row"
    assert "no pocket applies" in html, "and the pocket cell says why it is empty"


def test_the_pic50_cell_carries_no_ensemble_spread(bm):
    """The spread of two ensemble sub-models is not a confidence interval, and it
    doubled the width of the column. It stays a column of its own in the CSV."""
    import pandas as _pd
    df = _pd.DataFrame([{"run": 1, "family_group": "RECP", "ligand_id": "LIG1",
                         "pocket": "Unc", "pIC50": 8.5, "pIC50_ensemble_std": 0.42,
                         "flags": ""}])
    html = bm._build_full_table_html(df)
    assert "8.50" in html and "±" not in html and "0.42" not in html


# --- what the campaign was built on -------------------------------------------

def _cif_with_entities(path, descriptions, hetero=(), chains=("A",)):
    """A minimal mmCIF carrying an _entity loop and a few atoms."""
    lines = ["data_test", "loop_", "_entity.id", "_entity.type", "_entity.pdbx_description"]
    for i, name in enumerate(descriptions, 1):
        lines.append(f"{i} polymer '{name}'")
    lines += ["#", "loop_"]
    columns = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_comp_id",
               "auth_asym_id", "auth_seq_id", "Cartn_x", "Cartn_y", "Cartn_z"]
    lines += [f"_atom_site.{c}" for c in columns]
    n = 1
    for chain in chains:
        for i in range(3):
            lines.append(f"ATOM {n} C CA ALA {chain} {i + 1} 0.0 0.0 {float(i)}")
            n += 1
    for comp in hetero:
        lines.append(f"HETATM {n} C C1 {comp} {chains[0]} 900 1.0 1.0 1.0")
        n += 1
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_g_protein_coupled_reference_is_reported_as_active(bm, tmp_path):
    """An "apo" structure is very often ligand-free AND G-protein-coupled.

    That is the active state, so a motif comparison against it measures active
    against active and the activation shift cannot appear. Measured on GLP-1R: TM6
    moves 2.56A against 7rg9 (apo, Gs-bound) and 8.81A against 5VEW (inactive), for
    the same prediction. The panel has to say which one a campaign used.
    """
    path = _cif_with_entities(
        tmp_path / "apo.cif",
        ["Glucagon-like peptide 1 receptor",
         "Isoform Gnas-2 of Guanine nucleotide-binding protein G(s) subunit alpha"],
        chains=("R", "A"))
    info = bm._reference_state(path)
    assert info["g_protein"] is True
    assert "active" in info["state"]


def test_state_is_read_from_the_entity_names_not_from_the_sequence(bm, tmp_path):
    """A Walker A motif looked more principled and does not work.

    These are cryo-EM complexes built with mini-G constructs whose P-loop is often
    unmodelled: tried on 7rg9, 8wa3 and 7E14, all three of which contain Gs and none
    of which matched. 7E14 names its entities only "Gs" and "G protein", so the
    pattern has to catch those too.
    """
    path = _cif_with_entities(tmp_path / "terse.cif", ["Gs", "G protein"])
    assert bm._reference_state(path)["g_protein"] is True


def test_an_inactive_reference_is_not_mistaken_for_active_by_its_ligand(bm, tmp_path):
    """5VEW carries a negative allosteric modulator and no G protein.

    A bound ligand says nothing about the state -- which is exactly why the prep
    field is no longer called "apo".
    """
    path = _cif_with_entities(tmp_path / "inactive.cif",
                              ["Glucagon-like peptide 1 receptor,Endolysin chimera"],
                              hetero=("97Y",))
    info = bm._reference_state(path)
    assert info["g_protein"] is False
    assert info["ligands"] == ["97Y"], "the modulator is reported, not ignored"


def test_a_pocket_records_the_structure_it_came_from(bm, tmp_path):
    """The spec used to keep a pocket's residue numbers and drop its provenance."""
    md = tmp_path / "c.md"
    md.write_text("""Settings:
Output folder: ./y

Protein: RECP
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ
Pocket source: V6G from 7E14
Pocket contact: RECP residue 12 as V6G

Ligand: LIG1
SMILES: CCO
""")
    campaign = bm.parse_md(md)
    assert campaign.pocket_sources == {"V6G": "7E14"}
    panel = bm._build_reference_panel_html(campaign, tmp_path)
    assert "7E14" in panel and "V6G" in panel


def test_a_malformed_pocket_source_is_refused_with_the_shape_it_wanted(bm, tmp_path):
    md = tmp_path / "c.md"
    md.write_text("""Settings:
Output folder: ./y

Protein: RECP
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ
Pocket source: 7E14
Pocket contact: RECP residue 12 as V6G

Ligand: LIG1
SMILES: CCO
""")
    with pytest.raises(bm.MDParseError) as excinfo:
        bm.parse_md(md)
    assert "from" in str(excinfo.value) and "V6G from 7E14" in str(excinfo.value)


# --- charts that say which receptor a point belongs to -------------------------

def _summary_frame():
    import pandas as _pd
    return _pd.DataFrame([
        {"display_name": "1_A_LIG1", "family_group": "RECA", "pIC50": 9.0,
         "confidence_score": 0.80, "affinity_probability_binary": 0.6},
        {"display_name": "2_A_LIG2", "family_group": "RECA", "pIC50": 7.5,
         "confidence_score": 0.75, "affinity_probability_binary": 0.4},
        {"display_name": "3_B_LIG1", "family_group": "RECB", "pIC50": 8.5,
         "confidence_score": 0.78, "affinity_probability_binary": 0.5},
    ])


def _traces(html):
    import json, re
    body = re.search(r'Plotly\.newPlot\(\s*"[^"]+",\s*(\[.*?\]),\s*\{', html, re.S)
    return json.loads(body.group(1))


def test_each_protein_gets_its_own_marker_shape(bm):
    """Colour is already carrying the confidence tier, so shape is the only channel
    left to say which receptor a point belongs to -- and it is the one that survives
    next to a colourbar."""
    traces = _traces(bm._make_scatter(_summary_frame(), "chart-scatter"))
    shapes = {t["name"]: t["marker"]["symbol"] for t in traces}
    assert shapes == {"RECA": "circle", "RECB": "diamond"}


def test_the_ranked_bars_are_grouped_by_protein_then_ranked_inside_each(bm):
    """One sequence across the whole campaign interleaves receptors, and the question
    the bars answer is "which compound wins ON THIS receptor" -- unreadable when the
    neighbouring bar belongs to something else."""
    traces = _traces(bm._make_bar_chart(_summary_frame(), "pIC50", "chart-pic50"))
    assert [t["name"] for t in traces] == ["RECA", "RECB"]
    assert traces[0]["y"] == [9.0, 7.5], "ranked within the group, not across the campaign"
    # Contiguous positions, so the groups do not interleave on the axis.
    assert traces[0]["x"] == [0, 1] and traces[1]["x"] == [2]


def test_one_trace_per_protein_is_what_makes_the_legend_clickable(bm):
    """Plotly toggles a trace when its legend entry is clicked, so the interactivity
    asked for comes from the split itself rather than from any handler."""
    for html in (bm._make_scatter(_summary_frame(), "s"),
                 bm._make_bar_chart(_summary_frame(), "pIC50", "b")):
        traces = _traces(html)
        assert len(traces) == 2
        assert all(t.get("showlegend") for t in traces)


def test_a_single_protein_campaign_gets_no_legend(bm):
    """A legend of one entry is a label pretending to be a control."""
    import pandas as _pd
    one = _summary_frame().head(2)          # both rows are RECA
    html = bm._make_bar_chart(one, "pIC50", "b")
    assert '"showlegend": false' in html.replace(" ", "").replace('"showlegend":false',
                                                                 '"showlegend": false') \
        or '"showlegend":false' in html


def test_a_legend_below_the_plot_is_given_room(bm):
    """Placed below the axes it is outside them, so without its own margin it is
    drawn into the bottom edge and clipped -- which reads as the legend not rendering."""
    html = bm._make_bar_chart(_summary_frame(), "pIC50", "b")
    assert '"b": 160' in html or '"b":160' in html
