"""A protein may take a site from more than one structure.

Each pocket reference carries a reference molecule with it -- the bound ligand ships
in the bundle, and that is what a predicted pose is scored against. With one
reference only one compound can be checked: an ABL1 campaign supplying 2GQG scored
dasatinib and had nothing to measure imatinib against. The form and the spec both
had room for the sites but not for their provenance, so a second reference silently
overwrote the first's `Pocket source:` line.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from boltzmaker_web import derive_page
from boltzmaker_web.wizard import LigandInput, ProteinInput, assemble_boltz_input_md

sys.path.insert(0, str(Path(__file__).parent.parent))

SEQ = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"

TWO_REFERENCES = f"""Settings:
Pocket distance: 4

Protein: ABL1
Sequence: {SEQ}
Ligands: IMATI, DASAT
Pocket source: 1N1 from 2GQG
Pocket source: STI from 1IEP
Pocket contact: ABL1 residue 12 as 1N1
Pocket contact: ABL1 residue 20 as STI

Ligand: IMATI
SMILES: CCO

Ligand: DASAT
SMILES: CCC
"""


def _protein() -> ProteinInput:
    p = ProteinInput(name="ABL1", sequence=SEQ)
    p.pockets = {"1N1": [12], "STI": [20]}
    p.pocket_sources = {"1N1": "2GQG", "STI": "1IEP"}
    return p


# ---- writing ----------------------------------------------------------------

def test_every_reference_writes_its_own_provenance_line():
    md = assemble_boltz_input_md(True, [_protein()], [],
                                 [LigandInput(name="IMATI", kind="smiles", value="CCO")],
                                 compare_sse=False, pocket_distance=4.0)
    lines = [l for l in md.splitlines() if l.startswith("Pocket source:")]
    assert lines == ["Pocket source: 1N1 from 2GQG", "Pocket source: STI from 1IEP"], (
        "one line per site, sorted so the same form always writes the same spec")


def test_a_pocket_without_a_known_structure_writes_no_line():
    """The field is optional, and an empty id must not become 'from '."""
    p = _protein()
    p.pocket_sources = {"1N1": "2GQG", "STI": ""}
    md = assemble_boltz_input_md(True, [p], [],
                                 [LigandInput(name="IMATI", kind="smiles", value="CCO")],
                                 compare_sse=False, pocket_distance=4.0)
    assert [l for l in md.splitlines() if l.startswith("Pocket source:")] == \
        ["Pocket source: 1N1 from 2GQG"]


# ---- reading -----------------------------------------------------------------

# The parser half of this lives in test_run_progress.py, alongside the rest of the
# spec-format tests; what follows is the form's side of the same feature.


# ---- and back into the form --------------------------------------------------

def test_a_two_reference_spec_reloads_into_the_form_losslessly(app_ctx):
    """derive_verified rebuilds the page and proves it makes the same spec back."""
    page = derive_page.derive_verified(TWO_REFERENCES, {}, app=app_ctx)
    pockets = page["groups"]["protein"][0]["pockets"]
    assert {p["code"]: p["pdb"] for p in pockets} == {"1N1": "2GQG", "STI": "1IEP"}


@pytest.fixture
def app_ctx():
    from boltzmaker_web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield app


# ---- the form says the second one is possible --------------------------------

def test_the_form_explains_what_a_reference_molecule_buys():
    from boltzmaker_web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    page = app.test_client().get("/auto/prepare").get_data(as_text=True)
    assert "reference molecule" in page
    assert "add-pocket" in page, "and a way to add another one"


# ---- a reference molecule that defines no site -------------------------------

REFERENCE_ONLY = f"""Settings:
Pocket distance: 4

Protein: ABL1
Sequence: {SEQ}
Ligands: IMATI, DASAT
Pocket source: 1N1 from 2GQG
Pocket source: STI from 1IEP
Pocket contact: ABL1 residue 12 as 1N1

Ligand: IMATI
SMILES: CCO

Ligand: DASAT
SMILES: CCC
"""


def test_a_reference_only_row_costs_no_targets():
    """The whole point of the mode: a structure to score against, not a condition.

    A site is another run for every ligand, so on a two-ligand campaign adding a
    reference as a site takes 6 targets to 8. As a reference molecule it stays at 4.
    """
    import BoltzMaker as bm
    import tempfile
    path = Path(tempfile.mkdtemp()) / "c.md"
    path.write_text(REFERENCE_ONLY)
    campaign = bm.parse_md(path)
    stems = [bm._target_stem(f, l, c) for f, l, c in bm._expand_targets(campaign)]
    assert sorted(stems) == sorted(
        ["ABL1_IMATI", "ABL1_IMATI_1N1", "ABL1_DASAT", "ABL1_DASAT_1N1"])
    assert campaign.pocket_sources["STI"] == "1IEP", "still recorded, just not a site"


def test_a_reference_only_row_survives_a_reload(app_ctx):
    """Reloaded as a site it would silently add a target per ligand."""
    page = derive_page.derive_verified(REFERENCE_ONLY, {}, app=app_ctx)
    by_code = {p["code"]: p for p in page["groups"]["protein"][0]["pockets"]}
    assert by_code["STI"]["mode"] == "reference" and by_code["STI"]["residues"] == []
    assert by_code["1N1"]["mode"] == "site" and by_code["1N1"]["residues"] == [12]


def test_the_form_offers_the_mode_and_the_script_carries_it():
    from boltzmaker_web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    page = app.test_client().get("/auto/prepare").get_data(as_text=True)
    assert 'name="pocket_mode[]"' in page
    assert '<option value="reference"' in page
    source = (Path(__file__).parent.parent / "web/static/js/wizard.js").read_text()
    # Saved, restored, and kept out of the run count -- all three, or the mode is
    # cosmetic in one of the three places that matter.
    assert 'mode: mode ? mode.value : "site"' in source
    assert 'if (mode && saved && saved.mode) mode.value = saved.mode' in source
    assert 'modes[j].value === "reference"' in source


def test_a_reference_only_molecule_is_listed_in_the_report():
    """It is part of what the campaign was built on, so it belongs in that table."""
    import BoltzMaker as bm
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "c.md").write_text(REFERENCE_ONLY)
    html = bm._build_reference_panel_html(bm.parse_md(d / "c.md"), d)
    assert "STI" in html and "1IEP" in html
    assert "reference only" in html, "and marked as defining no site"

