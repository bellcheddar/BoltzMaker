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

def test_run_compare_sse_no_apo_structure_configured(tmp_path):
    from sse_comparison.cli import run_compare_sse
    settings = bm.Settings()
    fam = bm.ProteinFamily(id="TESTR", sequence="MDILCEENT")
    ligand = bm.Ligand(id="LIG1", smiles="CC(=O)Oc1ccccc1C(=O)O")
    campaign = bm.Campaign(settings=settings, partners={}, families=[fam], ligands=[ligand])
    with pytest.raises(SystemExit, match="nothing to compare"):
        run_compare_sse(campaign, tmp_path)
