"""Telling "nobody looked" from "nothing to see".

cif2plip is optional, so a campaign run without it produces no contacts for any
target. The viewer reported that as "0 contacting residues and the ligand as
sticks" -- an absence of analysis presented as a finding about the ligand, and the
two are opposite claims. A ligand that genuinely contacts nothing would be a
remarkable result; a campaign that never ran PLIP is a setup detail.
"""

from __future__ import annotations

import json
from pathlib import Path

from boltzmaker_web import results as results_mod


def _campaign(tmp_path: Path, with_interactions: bool) -> Path:
    """The smallest extracted .bmz the loader will read, with or without the csv."""
    root = tmp_path / ("with" if with_interactions else "without")
    (root / "summary").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps(
        # Read from the module so the fixture cannot drift from what it accepts.
        {"bmz_version": results_mod.SUPPORTED_BMZ_VERSIONS[-1],
         "campaign_name": "C", "targets_expected": 1}))
    (root / "summary" / "boltz_summary.csv").write_text(
        "target_id,display_name,family_id,ligand_id,confidence_score\n"
        "T1,1_T1,RECP,LIG1,0.9\n")
    if with_interactions:
        (root / "summary" / "boltz_interactions.csv").write_text(
            "target_id,chain,resnr,restype,kind\nT1,A,42,PHE,hydrophobic\n")
    return root


def test_a_campaign_without_the_plip_csv_is_marked_as_not_run(tmp_path):
    loaded = results_mod.load(_campaign(tmp_path, with_interactions=False))
    assert loaded.interactions_ran is False
    assert loaded.interactions == {}


def test_a_campaign_with_the_csv_is_marked_as_run(tmp_path):
    loaded = results_mod.load(_campaign(tmp_path, with_interactions=True))
    assert loaded.interactions_ran is True
    assert loaded.interactions.get("T1"), "and the contacts themselves are read"


# ---- the viewer has to act on it -------------------------------------------

def _explorer_js() -> str:
    return (Path(__file__).parent.parent / "web/static/js/explorer.js").read_text()


def test_the_viewer_distinguishes_not_run_from_none_found():
    source = _explorer_js()
    assert "interactions_ran === false" in source
    assert "Interaction analysis was not run" in source
    assert "No contacts were detected for this ligand" in source


def test_the_zero_contact_case_no_longer_reports_a_bare_count():
    """The exact string the user saw must not be reachable with no analysis."""
    source = _explorer_js()
    assert "if (framed && !contacts.length)" in source, (
        "a framed view with zero contacts needs its own message, or it falls "
        "through to '0 contacting residues'")


def test_the_payload_carries_the_flag_to_the_page():
    server = (Path(__file__).parent.parent
              / "web/boltzmaker_web/results.py").read_text()
    assert '"interactions_ran": results.interactions_ran,' in server
