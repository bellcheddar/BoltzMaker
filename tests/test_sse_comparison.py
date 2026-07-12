import json

import gemmi
import pytest

import BoltzMaker as bm
from sse_comparison.alignment import (InsufficientReferenceRegionError, build_comparison_frame,
                                       stable_reference_positions)
from sse_comparison.annotators.gpcrdb import GPCRdbAnnotator, _decode_generic_number
from sse_comparison.annotators.klifs import KLIFSAnnotator, _map_pocket_to_sequence
from sse_comparison.annotators.pfam import PfamFallbackAnnotator
from sse_comparison.cache import cache_key, cached_lookup
from sse_comparison.metrics import classify_state, compute_motif_row
from sse_comparison.motifs import Motif
from sse_comparison.structures import (AmbiguousApoChainError, load_and_clean,
                                        load_structure_for_comparison, one_letter_sequence,
                                        resolve_protein_chain)

FIXTURES_SSE = None  # set by conftest's sys.path insert; imported lazily below


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

def test_grammar_parses_apo_fields():
    from pathlib import Path
    campaign = bm.parse_md(Path(__file__).parent / "fixtures" / "apo_structure_case.md")
    fam = campaign.families[0]
    assert fam.apo_structure == "reference/testr_apo.pdb"
    assert fam.apo_chain == "A"
    assert fam.family_type == "gpcr"


def test_grammar_defaults_when_apo_fields_absent():
    from pathlib import Path
    campaign = bm.parse_md(Path(__file__).parent / "fixtures" / "pocket_contacts_case.md")
    fam = campaign.families[0]
    assert fam.apo_structure is None
    assert fam.apo_chain is None
    assert fam.family_type == "auto"


def test_grammar_rejects_invalid_family_type(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text(
        "Settings:\n\nProtein: TESTR\nSequence: MDILCEENTSLSSTTNSLMQ\nFamily type: notarealtype\n\n"
        "Ligand: LIG1\nSMILES: CC(=O)Oc1ccccc1C(=O)O\n"
    )
    with pytest.raises(bm.MDParseError):
        bm.parse_md(bad)


# ---------------------------------------------------------------------------
# cache.py
# ---------------------------------------------------------------------------

def test_cache_hit_skips_refetch(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"hello": "world"}

    k = cache_key("seq123")
    r1 = cached_lookup(tmp_path, k, fetch)
    r2 = cached_lookup(tmp_path, k, fetch)
    assert r1 == r2 == {"hello": "world"}
    assert calls["n"] == 1


def test_cache_caches_failure_without_retrying(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        raise RuntimeError("network down")

    k = cache_key("seq456")
    assert cached_lookup(tmp_path, k, fetch) is None
    assert cached_lookup(tmp_path, k, fetch) is None
    assert calls["n"] == 1


def test_cache_refresh_bypasses_cache(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"v": calls["n"]}

    k = cache_key("seq789")
    cached_lookup(tmp_path, k, fetch)
    cached_lookup(tmp_path, k, fetch, refresh=True)
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# structures.py
# ---------------------------------------------------------------------------

def test_one_letter_sequence_handles_real_disordered_gap(egfr_apo_path):
    st = load_and_clean(egfr_apo_path)
    polymer = st[0]["A"].get_polymer()
    seq = one_letter_sequence(polymer)
    assert len(seq) == len(list(polymer))
    assert "-" not in seq


def test_resolve_protein_chain_fusion_construct_auto_detects(adrb2_apo_path, adrb2_sequence):
    st = load_and_clean(adrb2_apo_path)
    chain = resolve_protein_chain(st, None, adrb2_sequence)
    assert chain.name == "A"


def test_resolve_protein_chain_rejects_unrelated_sequence(adrb2_apo_path):
    st = load_and_clean(adrb2_apo_path)
    with pytest.raises(AmbiguousApoChainError):
        resolve_protein_chain(st, None, "Z" * 20)


def test_resolve_protein_chain_kinase_domain_only_apo_scores_by_shorter_sequence(egfr_apo_path, egfr_sequence):
    # 1M14 is only the ~308-residue EGFR kinase domain; egfr_sequence is the full
    # 1210-residue receptor. A naive score normalized by the full length could never
    # clear a real "is this even a match" bar -- this is the regression test for that.
    st = load_and_clean(egfr_apo_path)
    chain = resolve_protein_chain(st, None, egfr_sequence)
    assert chain.name == "A"


# ---------------------------------------------------------------------------
# GPCRdb annotator
# ---------------------------------------------------------------------------

def test_decode_generic_number_recognizes_known_segments():
    assert _decode_generic_number(1.28) == ("TM1", "1.28")
    assert _decode_generic_number(12.50) == ("ICL1", "12.50")
    assert _decode_generic_number(6.55) == ("TM6", "6.55")


def test_decode_generic_number_rejects_real_bfactors():
    # Real crystallographic B-factors for unassigned residues are excluded by not
    # matching any of GPCRdb's own closed set of segment codes.
    assert _decode_generic_number(97.74) == (None, None)
    assert _decode_generic_number(-1.0) == (None, None)


class _FakeGPCRdbClient:
    def __init__(self, response_path):
        self._response = {int(k): tuple(v) for k, v in json.loads(response_path.read_text()).items()}

    def assign_generic_numbers(self, pdb_path, refresh=False):
        return self._response


def test_gpcrdb_annotate_full_pipeline_real_2rh1(adrb2_apo_path, adrb2_sequence):
    from pathlib import Path
    fake_client = _FakeGPCRdbClient(Path(__file__).parent / "fixtures" / "sse" / "gpcrdb_2rh1_response.json")
    ann = GPCRdbAnnotator(client=fake_client)
    motifs = ann.annotate(adrb2_sequence, structure_path=str(adrb2_apo_path))
    names = {m.name for m in motifs}
    assert {"TM1", "TM2", "TM3", "TM4", "TM5", "TM6", "TM7", "H8"} <= names
    tm6 = next(m for m in motifs if m.name == "TM6")
    assert tm6.is_binding_site_adjacent
    tm1 = next(m for m in motifs if m.name == "TM1")
    assert not tm1.is_binding_site_adjacent


def test_gpcrdb_applies_to_heuristic(adrb2_sequence):
    ann = GPCRdbAnnotator()
    assert ann.applies_to(adrb2_sequence)
    assert not ann.applies_to("MAAAAAAAAAAA")  # too short, no class-A motifs


# ---------------------------------------------------------------------------
# KLIFS annotator
# ---------------------------------------------------------------------------

_REAL_EGFR_POCKET = ("KVLGSGAFGTVYKVAIKELEILDEAYVMASVDPHVCRLLGIQLITQLMPFGCLLDYVRE"
                     "YLEDRRLVHRDLAARNVLVITDFGLA")


def test_map_pocket_to_sequence_synthetic():
    # A short synthetic "pocket" that's a substring of a synthetic sequence, no gaps.
    sequence = "AAAAA" + "MVIT" + "BBBBB"
    mapping = _map_pocket_to_sequence("MVIT", sequence)
    assert mapping == {1: 5, 2: 6, 3: 7, 4: 8}


def test_map_pocket_to_sequence_real_egfr(egfr_sequence):
    mapping = _map_pocket_to_sequence(_REAL_EGFR_POCKET, egfr_sequence)
    assert len(mapping) == 85
    # verified ground truth: KLIFS position 17 = catalytic Lys K745 (0-indexed 744)
    assert mapping[17] == 744
    assert egfr_sequence[mapping[17]] == "K"
    # KLIFS position 45 = the gatekeeper T790 (0-indexed 789)
    assert mapping[45] == 789
    assert egfr_sequence[mapping[45]] == "T"


class _FakeKLIFSClient:
    def lookup_pocket(self, kinase_name, species="HUMAN", refresh=False):
        return {"pocket": _REAL_EGFR_POCKET, "kinase_ID": 406}


def test_klifs_annotate_full_pipeline_real_egfr(egfr_sequence):
    ann = KLIFSAnnotator(client=_FakeKLIFSClient())
    motifs = ann.annotate(egfr_sequence, name_hint="EGFR")
    by_name = {m.name: m for m in motifs}
    assert set(by_name) >= {"catalytic_Lys", "alphaC_Glu", "gatekeeper", "hinge",
                             "catalytic_loop", "DFG", "pocket_scaffold"}
    # real EGFR ground truth (1-indexed residue numbers): K745, E762, T790, D855
    assert by_name["catalytic_Lys"].residues == [744]
    assert by_name["alphaC_Glu"].residues == [761]
    assert by_name["gatekeeper"].residues == [789]
    assert 854 in by_name["DFG"].residues
    assert not by_name["pocket_scaffold"].is_binding_site_adjacent
    assert by_name["DFG"].is_binding_site_adjacent


def test_klifs_applies_to_heuristic(egfr_sequence):
    ann = KLIFSAnnotator()
    assert ann.applies_to(egfr_sequence)
    assert not ann.applies_to("MAAAAAAAAAAA")


# ---------------------------------------------------------------------------
# Pfam fallback annotator
# ---------------------------------------------------------------------------

class _FakePDBeClient:
    def lookup_domains(self, pdb_id, chain_id=None, refresh=False):
        # Real, previously-verified PDBe SIFTS data for 2RH1: PF00001 (7tm_1) spans
        # author residues 50-326, PF00959 (Phage lysozyme, the T4L insert) 1009-1151.
        return [(50, 326, "7tm_1", "A"), (1009, 1151, "Phage_lysozyme", "A")]


def test_pfam_fallback_full_pipeline_real_2rh1(adrb2_apo_path, adrb2_sequence):
    ann = PfamFallbackAnnotator(client=_FakePDBeClient())
    motifs = ann.annotate(adrb2_sequence, pdb_id="2rh1", structure_path=str(adrb2_apo_path))
    names = {m.name for m in motifs}
    assert "7tm_1" in names
    seven_tm = next(m for m in motifs if m.name == "7tm_1")
    # the largest domain should dwarf any T4L alignment noise
    largest = max(motifs, key=lambda m: len(m.residues))
    assert largest.name == "7tm_1"
    assert len(seven_tm.residues) > 200


def test_pfam_fallback_applies_to_is_universal():
    assert PfamFallbackAnnotator().applies_to("ANYTHING")


# ---------------------------------------------------------------------------
# alignment.py + metrics.py: full pipeline, real structures, fake network clients
# ---------------------------------------------------------------------------

def test_full_pipeline_adrb2_tm6_shift_exceeds_tm1(adrb2_apo_path, adrb2_holo_cif_path, adrb2_sequence):
    from pathlib import Path
    fake_client = _FakeGPCRdbClient(Path(__file__).parent / "fixtures" / "sse" / "gpcrdb_2rh1_response.json")
    ann = GPCRdbAnnotator(client=fake_client)
    motifs = ann.annotate(adrb2_sequence, structure_path=str(adrb2_apo_path))

    apo = load_structure_for_comparison(adrb2_apo_path, None, adrb2_sequence)
    holo = load_structure_for_comparison(adrb2_holo_cif_path, "ADRB2", adrb2_sequence)
    frame = build_comparison_frame(apo, holo, adrb2_sequence, motifs, "gpcr")

    rows = {r["motif_name"]: r for r in (compute_motif_row(frame, m) for m in motifs) if r}
    # Assert the *direction* of the best-known result in GPCR structural biology (TM6
    # swings out on activation) rather than a hardcoded RMSD value -- an X-ray apo
    # structure vs an ML-predicted holo structure will never numerically match any
    # specific literature number, but the relative ranking is a real, checkable claim.
    assert rows["TM6"]["ca_rmsd_A"] > rows["TM1"]["ca_rmsd_A"]
    assert rows["TM6"]["ca_rmsd_A"] > rows["TM2"]["ca_rmsd_A"]


def test_full_pipeline_egfr_dfg_state_resolves(egfr_apo_path, egfr_holo_cif_path, egfr_sequence):
    ann = KLIFSAnnotator(client=_FakeKLIFSClient())
    motifs = ann.annotate(egfr_sequence, name_hint="EGFR")

    apo = load_structure_for_comparison(egfr_apo_path, None, egfr_sequence)
    holo = load_structure_for_comparison(egfr_holo_cif_path, "EGFR", egfr_sequence)
    frame = build_comparison_frame(apo, holo, egfr_sequence, motifs, "kinase")

    dfg_pos = next(m.residues[0] for m in motifs if m.name == "DFG")
    lys_pos = next(m.residues[0] for m in motifs if m.name == "catalytic_Lys")
    state_apo, state_holo, changed = classify_state(frame, dfg_pos, lys_pos, 8.0)
    assert state_apo in ("in", "out")
    assert state_holo in ("in", "out")
    assert changed in (True, False)


def test_insufficient_reference_region_raises_clear_error(adrb2_apo_path, adrb2_holo_cif_path, adrb2_sequence):
    apo = load_structure_for_comparison(adrb2_apo_path, None, adrb2_sequence)
    holo = load_structure_for_comparison(adrb2_holo_cif_path, "ADRB2", adrb2_sequence)
    # A single tiny motif -- nowhere near enough for a real superposition fit.
    motifs = [Motif(name="tiny", kind="point", residues=[10, 11], is_binding_site_adjacent=False)]
    with pytest.raises(InsufficientReferenceRegionError):
        build_comparison_frame(apo, holo, adrb2_sequence, motifs, "gpcr")


def test_stable_reference_positions_pfam_picks_largest_domain_only():
    motifs = [
        Motif(name="big", kind="loop", residues=list(range(100)), is_binding_site_adjacent=False),
        Motif(name="small", kind="loop", residues=[500, 501, 502], is_binding_site_adjacent=False),
    ]
    ref = stable_reference_positions(motifs, "pfam")
    assert ref == list(range(100))  # only the largest domain, not the pooled union


# ---------------------------------------------------------------------------
# metrics.py: classify_state on synthetic, unambiguous coordinates
# ---------------------------------------------------------------------------

class _FakePolymerResidue:
    def __init__(self, pos):
        self._pos = pos

    def sole_atom(self, name):
        class _A:
            pass
        a = _A()
        a.pos = self._pos
        return a


class _FakePolymer:
    def __init__(self, positions):
        self._positions = positions

    def __getitem__(self, i):
        return _FakePolymerResidue(self._positions[i])


class _FakeStructure:
    def __init__(self, polymer):
        self.polymer = polymer


class _FakeFrame:
    def __init__(self, apo, holo, fam_to_apo, fam_to_holo):
        self.apo, self.holo = apo, holo
        self.fam_to_apo, self.fam_to_holo = fam_to_apo, fam_to_holo


def test_classify_state_synthetic_in_and_out():
    # anchor1=0, anchor2=1: apo has them 3A apart ("in"), holo 15A apart ("out").
    apo_struct = _FakeStructure(_FakePolymer([gemmi.Position(0, 0, 0), gemmi.Position(3, 0, 0)]))
    holo_struct = _FakeStructure(_FakePolymer([gemmi.Position(0, 0, 0), gemmi.Position(15, 0, 0)]))
    frame = _FakeFrame(apo_struct, holo_struct, {100: 0, 200: 1}, {100: 0, 200: 1})
    state_apo, state_holo, changed = classify_state(frame, 100, 200, threshold=8.0)
    assert state_apo == "in"
    assert state_holo == "out"
    assert changed is True


def test_classify_state_missing_anchor_returns_none():
    apo_struct = _FakeStructure(_FakePolymer([gemmi.Position(0, 0, 0)]))
    holo_struct = _FakeStructure(_FakePolymer([gemmi.Position(0, 0, 0)]))
    frame = _FakeFrame(apo_struct, holo_struct, {100: 0}, {100: 0})
    state_apo, state_holo, changed = classify_state(frame, 100, 999, threshold=8.0)
    assert state_apo is None
    assert changed is None


# ---------------------------------------------------------------------------
# cli.py: clean failure path
# ---------------------------------------------------------------------------

def _minimal_campaign_no_apo():
    settings = bm.Settings()
    fam = bm.ProteinFamily(id="TESTR", sequence="MDILCEENT")
    ligand = bm.Ligand(id="LIG1", smiles="CC(=O)Oc1ccccc1C(=O)O")
    return bm.Campaign(settings=settings, partners={}, families=[fam], ligands=[ligand])


def test_run_compare_sse_strict_no_apo_structure_configured(tmp_path):
    # Standalone `compare-sse` command's default (strict=True): nothing configured
    # anywhere is a real error worth stopping for.
    from sse_comparison.cli import run_compare_sse
    with pytest.raises(SystemExit, match="produced no comparable targets"):
        run_compare_sse(_minimal_campaign_no_apo(), tmp_path)


def test_run_compare_sse_nonstrict_no_apo_structure_never_raises(tmp_path):
    # analyze/all's auto-run (strict=False): must never abort the pipeline over an
    # optional, additive feature -- always returns, always reports family_status.
    from sse_comparison.cli import run_compare_sse
    result = run_compare_sse(_minimal_campaign_no_apo(), tmp_path, strict=False)
    assert result["df"].empty
    assert result["family_status"]["TESTR"]["status"] == "no_apo_structure"


def test_run_compare_sse_writes_family_status_sidecar(tmp_path):
    from sse_comparison.cli import run_compare_sse
    run_compare_sse(_minimal_campaign_no_apo(), tmp_path, strict=False)
    status_path = tmp_path / "boltz_sse_family_status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text())
    assert status["TESTR"]["status"] == "no_apo_structure"
    assert "Apo structure" in status["TESTR"]["message"]


# ---------------------------------------------------------------------------
# report.py: family coverage, summary stats, N/A rendering
# ---------------------------------------------------------------------------

def test_build_family_status_html_reports_unconfigured_family():
    from sse_comparison.report import build_family_status_html
    html = build_family_status_html({
        "ADRB2": {"status": "ok", "message": "14 motif row(s) across 2 target(s)"},
        "OTHERFAM": {"status": "no_apo_structure", "message": "No 'Apo structure:' configured"},
    })
    assert "ADRB2" in html
    assert "OTHERFAM" in html
    assert "No apo structure configured" in html  # human label, not the raw status code


def test_build_family_status_html_empty_returns_empty_string():
    from sse_comparison.report import build_family_status_html
    assert build_family_status_html({}) == ""


def test_compute_summary_stats_real_adrb2(adrb2_apo_path, adrb2_holo_cif_path, adrb2_sequence):
    from pathlib import Path
    from sse_comparison.report import compute_summary_stats
    fake_client = _FakeGPCRdbClient(Path(__file__).parent / "fixtures" / "sse" / "gpcrdb_2rh1_response.json")
    ann = GPCRdbAnnotator(client=fake_client)
    motifs = ann.annotate(adrb2_sequence, structure_path=str(adrb2_apo_path))
    apo = load_structure_for_comparison(adrb2_apo_path, None, adrb2_sequence)
    holo = load_structure_for_comparison(adrb2_holo_cif_path, "ADRB2", adrb2_sequence)
    frame = build_comparison_frame(apo, holo, adrb2_sequence, motifs, "gpcr")
    rows = [compute_motif_row(frame, m) for m in motifs]
    rows = [r for r in rows if r]
    for r in rows:
        r["target_stem"] = "ADRB2_ISO1"
        r["target_display"] = "ADRB2_ISO1"
    from sse_comparison.report import build_metrics_dataframe
    df = build_metrics_dataframe(rows)
    stats = compute_summary_stats(df)
    assert stats["n_targets"] == 1
    assert stats["n_motifs"] == len(rows)
    assert stats["max_rmsd_label"].startswith("ADRB2_ISO1")
    # self-consistency: the reported max really is the row-wise max of the input df
    assert stats["max_rmsd"] == df["ca_rmsd_A"].max()
    assert stats["mean_rmsd"] == pytest.approx(df["ca_rmsd_A"].mean())


def test_compute_summary_stats_empty_df_returns_empty_dict():
    from sse_comparison.report import build_metrics_dataframe, compute_summary_stats
    assert compute_summary_stats(build_metrics_dataframe([])) == {}


def test_write_csv_uses_na_for_missing_metrics(tmp_path):
    from sse_comparison.report import build_metrics_dataframe, write_csv
    df = build_metrics_dataframe([{
        "family_id": "F", "target_stem": "F_L", "ligand_id": "L", "motif_name": "loop1",
        "motif_kind": "loop", "annotator_source": "pfam", "n_residues": 5, "ca_rmsd_A": 1.2,
        "centroid_shift_A": 0.5, "axis_rotation_deg": None, "n_flagged_phipsi_residues": 0,
        "flagged_residues": [],
    }])
    out = tmp_path / "out.csv"
    write_csv(df, out)
    text = out.read_text()
    assert ",N/A," in text or text.rstrip().endswith("N/A")


# ---------------------------------------------------------------------------
# report.py: grouped SSE table (short headers, rounding, all-N/A group dropping)
# ---------------------------------------------------------------------------

def _gpcr_style_row(**overrides):
    row = {
        "family_id": "F", "family_display": "F", "target_stem": "F_L", "target_display": "F_L",
        "ligand_id": "L", "motif_name": "TM1",
        "motif_kind": "helix", "annotator_source": "gpcr", "n_residues": 33,
        "ca_rmsd_A": 1.737864498, "centroid_shift_A": 0.892157501,
        "axis_rotation_deg": 4.471211655, "n_flagged_phipsi_residues": 2,
        "flagged_residues": [1, 2],
    }
    row.update(overrides)
    return row


def test_sse_table_rounds_floats_to_two_decimal_places():
    from sse_comparison.report import build_metrics_dataframe, build_sse_table_html
    df = build_metrics_dataframe([_gpcr_style_row()])
    html = build_sse_table_html(df)
    assert "1.74" in html  # ca_rmsd_A rounded, not the raw 1.737864498...
    assert "1.737864498" not in html
    assert "0.89" in html  # centroid_shift_A rounded


def test_sse_table_uses_short_grouped_headers():
    from sse_comparison.report import build_metrics_dataframe, build_sse_table_html
    df = build_metrics_dataframe([_gpcr_style_row()])
    html = build_sse_table_html(df)
    assert "RMSD (A)" in html  # short label, not the raw ca_rmsd_A
    assert ">Shift<" in html  # a colspan group header band is present
    assert "ca_rmsd_A" not in html  # raw snake_case header no longer shown


def test_sse_table_drops_all_na_kinase_columns_for_gpcr_family():
    from sse_comparison.report import build_metrics_dataframe, build_sse_table_html
    # A GPCR-family row never has DFG/alphaC state populated -- the whole "Kinase
    # state" column group should be dropped, not shown as a wall of N/A cells.
    df = build_metrics_dataframe([_gpcr_style_row()])
    html = build_sse_table_html(df)
    assert "Kinase state" not in html
    assert "DFG apo" not in html


def test_sse_table_keeps_kinase_columns_when_populated():
    from sse_comparison.report import build_metrics_dataframe, build_sse_table_html
    df = build_metrics_dataframe([_gpcr_style_row(
        annotator_source="kinase", motif_name="DFG",
        dfg_state_apo="out", dfg_state_holo="out", dfg_state_changed=False,
        alphac_state_apo="in", alphac_state_holo="out", alphac_state_changed=True,
    )])
    html = build_sse_table_html(df)
    assert "Kinase state" in html
    assert "DFG apo" in html
    assert "alphaC apo" in html


def test_sse_table_drops_only_genuinely_empty_columns_not_whole_group():
    # Fine-grained, per-column dropping: DFG is populated but alphaC isn't (e.g. one of
    # the two anchor residues couldn't be resolved) -- DFG columns stay, alphaC columns
    # (genuinely all-N/A for this campaign) are dropped, not the whole Kinase state group.
    from sse_comparison.report import build_metrics_dataframe, build_sse_table_html
    df = build_metrics_dataframe([_gpcr_style_row(
        annotator_source="kinase", motif_name="DFG",
        dfg_state_apo="out", dfg_state_holo="out", dfg_state_changed=False,
    )])
    html = build_sse_table_html(df)
    assert "DFG apo" in html
    assert "alphaC apo" not in html


def test_sse_table_always_keeps_identity_and_shift_columns():
    from sse_comparison.report import _resolve_sse_table_columns, build_metrics_dataframe
    df = build_metrics_dataframe([_gpcr_style_row(axis_rotation_deg=None)])
    cols = _resolve_sse_table_columns(df)
    assert {"family_display", "target_display", "motif_name", "n_residues", "ca_rmsd_A"} <= set(cols)


def test_sse_table_sorted_by_ligand_then_kind_then_motif():
    import re
    from sse_comparison.report import build_metrics_dataframe, build_sse_table_html
    rows = [
        _gpcr_style_row(ligand_id="PRO1", target_stem="F_PRO1", motif_kind="helix", motif_name="TM2"),
        _gpcr_style_row(ligand_id="ISO1", target_stem="F_ISO1", motif_kind="loop", motif_name="ICL1"),
        _gpcr_style_row(ligand_id="ISO1", target_stem="F_ISO1", motif_kind="helix", motif_name="TM1"),
        _gpcr_style_row(ligand_id="PRO1", target_stem="F_PRO1", motif_kind="helix", motif_name="TM1"),
    ]
    df = build_metrics_dataframe(rows)
    html = build_sse_table_html(df)
    # rendered column order is Ligand, then Motif (name), then Kind -- extract all three
    # per row and confirm the *sort* (by ligand, then kind, then motif name) held.
    rows_found = re.findall(r"<td class=''>(ISO1|PRO1)</td><td class=''>(TM1|TM2|ICL1)</td>"
                             r"<td class=''>(helix|loop)</td>", html)
    assert rows_found == [
        ("ISO1", "TM1", "helix"), ("ISO1", "ICL1", "loop"),
        ("PRO1", "TM1", "helix"), ("PRO1", "TM2", "helix"),
    ]
