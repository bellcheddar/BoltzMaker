"""Landlord's Python side: the contract, the gate, the fallback and the degradation.

None of these need the model, a Swift binary or an Apple machine. That is the point:
the parts that must work everywhere are tested everywhere, and the parts that need
this specific Mac live in test_placement.py behind the `hardware` marker.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import mock

import pytest

from landlord import fallback, install, validate
from landlord.bridge import NarrationUnavailable, narrate
from landlord.campaign import plan_chunks, summarise_stats
from landlord.config import NarrationConfig
from landlord.factblock import PROMPT_TOKEN_BUDGET, Confidence, FactBlock, LigandFact, fmt

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/landlord"


def _block(name: str = "GIPR_LSN1_41Y") -> FactBlock:
    payload = json.loads((FIXTURES / f"{name}.json").read_text())
    payload.pop("_why_this_fixture", None)
    return FactBlock.model_validate(payload)


@pytest.fixture
def block():
    return _block()


# ---- the contract -----------------------------------------------------------

def test_numbers_are_formatted_here_not_by_the_model():
    """A model given 0.8417 will round it differently each time it is asked."""
    assert fmt(0.8417) == "0.842"
    assert fmt(2.79, 2, "Å") == "2.79 Å"
    assert fmt(None) == "not measured"
    assert fmt(float("nan")) == "not measured"


def test_every_golden_fixture_fits_the_prompt_budget():
    for path in sorted(FIXTURES.glob("*.json")):
        b = _block(path.stem)
        assert b.fits_budget(), (
            f"{path.stem} is {b.token_estimate()} tokens, over {PROMPT_TOKEN_BUDGET}")


def test_the_prompt_form_is_compact_and_the_pretty_form_is_not():
    """Compact is latency, not tidiness: measured at 22.9 s against 11.8 s."""
    b = _block()
    assert "\n" not in b.to_prompt_json()
    assert "\n" in b.to_pretty_json()
    assert json.loads(b.to_prompt_json()) == json.loads(b.to_pretty_json())


def test_too_many_ligands_is_refused_rather_than_silently_truncated():
    """Dropping ligands without saying so is the failure this guards against."""
    b = _block()
    many = [LigandFact(name=f"L{i}", rank="1 of 9", predicted_pic50="8",
                       pic50_spread="0.1", binder_probability="0.5",
                       contacts_summary="none") for i in range(9)]
    with pytest.raises(ValueError, match="ligands_omitted"):
        FactBlock(**{**b.model_dump(exclude_none=True), "ligands": many})


# ---- the gate ---------------------------------------------------------------

def test_the_gate_passes_the_template_it_will_fall_back_to(block):
    assert validate.check_summary(fallback.render_summary(block), block)


@pytest.mark.parametrize("was,now,what", [
    ("0.91", "0.9", "a pose RMSD rounded down"),
    ("8.85", "8.9", "a pIC50 rounded"),
    ("11", "12", "a contact count changed"),
    ("0.742", "0.75", "a binder probability rounded"),
])
def test_the_gate_rejects_a_corrupted_number(block, was, now, what):
    summary = fallback.render_summary(block)
    summary["ligandNotes"] = [n.replace(was, now) for n in summary["ligandNotes"]]
    verdict = validate.check_summary(summary, block)
    assert not verdict, f"{what} slipped through"
    assert now in verdict.orphans


def test_trailing_zeros_are_the_same_number(block):
    """8.80 and 8.8 are one measurement; failing that would be noise, not rigour."""
    assert validate.check("the value was 0.910", block).ok


def test_the_gate_catches_a_number_from_nowhere(block):
    assert not validate.check("confidence scores above 0.8", block)


def test_the_gate_checks_presence_not_attribution(block):
    """A known and deliberate limit, recorded so it is not mistaken for a bug.

    The gate cannot tell that a supplied number has been attached to the wrong noun.
    That is why campaign-level findings, which are all tallies, are composed in
    Python rather than narrated -- see CampaignStats.key_findings.
    """
    supplied = sorted(block.numeric_tokens())[0]
    assert validate.check(f"there were {supplied} kangaroos", block).ok


# ---- the fallback -----------------------------------------------------------

def test_the_template_is_deterministic(block):
    assert fallback.render_summary(block) == fallback.render_summary(block)


def test_the_template_says_what_it_knows(block):
    text = fallback.render(block)
    for expected in (block.confidence.confidence_score, block.recommendation):
        assert expected in text


# ---- degradation ------------------------------------------------------------

def test_a_missing_binary_still_produces_a_summary(block):
    got = narrate(block, NarrationConfig(mode="auto"), binary=Path("/nonexistent/x"))
    assert got.generated_by == "template" and got.summary["ligandNotes"]


def test_model_mode_raises_where_auto_degrades(block):
    with pytest.raises(NarrationUnavailable):
        narrate(block, NarrationConfig(mode="model"), binary=Path("/nonexistent/x"))


@pytest.mark.parametrize("mode", ["off", "template"])
def test_disabled_modes_never_touch_a_binary(block, mode):
    with mock.patch("landlord.bridge.find_binary",
                    side_effect=AssertionError("should not look for a binary")):
        assert narrate(block, NarrationConfig(mode=mode)).generated_by == "template"


# ---- campaign roll-up -------------------------------------------------------

def test_campaign_findings_are_computed_not_narrated():
    blocks = [_block(p.stem) for p in sorted(FIXTURES.glob("*.json"))]
    stats = summarise_stats(blocks, "fixtures")
    assert stats.key_findings
    joined = " ".join(stats.key_findings)
    assert f"Of {len(blocks)} targets" in joined


def test_reduce_chunks_are_sized_to_fit_rather_than_assumed():
    blocks = [_block(p.stem) for p in sorted(FIXTURES.glob("*.json"))]
    stats = summarise_stats(blocks, "fixtures")
    summaries = [dict(fallback.render_summary(b), target_id=b.target_id) for b in blocks]
    chunks = plan_chunks(summaries * 6, stats)
    assert chunks and all(c.token_estimate() <= 700 for c in chunks)
    assert sum(len(c.summaries) for c in chunks) == len(summaries) * 6


# ---- packaging --------------------------------------------------------------

@pytest.mark.parametrize("system,machine,version,expected", [
    ("Linux", "x86_64", "0", "no on-device Apple model"),
    ("Darwin", "x86_64", "26.0", "no Intel path"),
    ("Darwin", "arm64", "15.5", "predates FoundationModels"),
])
def test_unsupported_platforms_degrade_with_a_reason(system, machine, version, expected):
    with mock.patch("platform.system", return_value=system), \
         mock.patch("platform.machine", return_value=machine), \
         mock.patch("platform.mac_ver", return_value=(version, ("", "", ""), "")):
        ok, why = install.platform_supported()
        assert not ok and expected in why
