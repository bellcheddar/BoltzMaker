"""What the Reference structures panel is allowed to say about a structure's state.

An ABL1 kinase campaign reported its reference as "no G protein bound" -- true, and
meaningless: a G protein is not a thing a kinase is missing. Only a GPCR and a kinase
have a conformational state this project can read, and each is read differently.
"""

from __future__ import annotations

import BoltzMaker as bm
from sse_comparison.cli import family_kind


# ---- which question is even askable -----------------------------------------

#: Real ABL1 (P00519) fragment: carries the HRD catalytic loop and the DFG motif that
#: KLIFS's pre-filter looks for, which is what makes this a kinase to the detector.
KINASE_SEQ = ("MGQQPGKVLGDQRRPSLPALHFIKGAGKKESSRHGGPHCNVFVEHEALQRPVASDFEPQGLSEAARWNS"
              "KENLLAGPSENDPNLFVALYDFVASGDNTLSITKGEKLRVLGYNHNGEWCEAQTKNGQGWVPSNYITPV"
              "NHRDLAARNCLVGENHLVKVADFGLSRLMTGDTYTAHAGAKFPIKWTAPESLAYNKFSIKSDVWAFGVL")


def test_a_kinase_is_recognised_without_being_told():
    assert family_kind("auto", KINASE_SEQ) == "kinase"


def test_an_explicit_family_type_is_taken_at_its_word():
    """The user saying so beats a sequence heuristic, both ways."""
    assert family_kind("gpcr", KINASE_SEQ) == "gpcr"
    assert family_kind("kinase", "MKTVRQ") == "kinase"


def test_a_protein_that_is_neither_gets_no_family():
    assert family_kind("auto", "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ") is None


# ---- and therefore what the panel says --------------------------------------

def _reading(kind, g_protein=False, motifs=None):
    return bm._reference_state_reading(kind, g_protein, motifs or {})


def test_a_kinase_is_never_described_by_what_g_protein_it_lacks():
    """The reported bug, as a test. Applies whether or not its motifs resolved."""
    for motifs in ({}, {"DFG": "in", "αC": "out"}):
        text = " ".join(str(v) for v in _reading("kinase", motifs=motifs).values())
        assert "G protein" not in text
        assert "G-protein" not in text


def test_a_kinase_reads_its_dfg_and_alphac_motifs():
    reading = _reading("kinase", motifs={"DFG": "in", "αC": "out"})
    assert reading["state"] == "DFG-in, αC-out"
    assert reading["tier"] == bm._TIER_GREEN


def test_an_unresolved_kinase_state_is_unknown_rather_than_absent():
    """"No DFG state" would read as a missing motif; the anchors just did not resolve."""
    reading = _reading("kinase")
    assert "not resolved" in reading["state"]
    assert reading["tier"] == bm._TIER_AMBER
    assert "unknown, not absent" in reading["note"]


def test_a_gpcr_still_reads_its_g_protein_coupling():
    """The behaviour this panel was built for has to survive the fix."""
    active = _reading("gpcr", g_protein=True)
    assert active["state"] == "active (G protein bound)"
    assert active["tier"] == bm._TIER_AMBER, "an active reference cannot show the shift"
    assert _reading("gpcr")["state"] == "no G protein bound"
    assert _reading("gpcr")["tier"] == bm._TIER_GREEN


def test_neither_family_is_given_no_state_and_no_colour():
    """A tier would paint a verdict onto a question that was never asked."""
    reading = _reading(None)
    assert reading["tier"] is None
    assert "no activation state" in reading["note"]
    for word in ("G protein", "G-protein", "DFG"):
        assert word not in reading["state"]


# ---- the note under the table follows the same rule -------------------------

def test_the_hint_mentions_only_the_families_present():
    assert "G-protein-coupled" not in bm._sse_state_hint({"kinase"})
    assert "DFG" in bm._sse_state_hint({"kinase"})
    assert "DFG" not in bm._sse_state_hint({"gpcr"})
    assert "G-protein-coupled" in bm._sse_state_hint({"gpcr"})
    assert bm._sse_state_hint(set()) == ""


def test_a_mixed_campaign_explains_both():
    hint = bm._sse_state_hint({"gpcr", "kinase", None})
    assert "GPCR" in hint and "DFG" in hint and "none is claimed" in hint
