"""Rebuilding the Prepare form from a spec, and refusing when that would lie.

Every bundle in the Runs archive predates the wizard storing its own state, so
uploading one could only report that there was nothing to restore. Deriving the
page from `boltz_input.md` fixes that, but only if the derivation is checked:
a spec can say things the form has no field for, and dropping one produces a
form that looks right, rebuilds into a different campaign, and says nothing.
"""

from __future__ import annotations

import io
import json

import pytest

from boltzmaker_web import bundle, derive_page, wizard


MD_PLAIN = """Settings:
Output folder: ./boltz_yamls
Predict affinity: yes

Protein: RECP1
Sequence: MDILCEEN
Partners: CHNX

Partner: CHNX
Sequence: MTLESKKAA

Ligand: LIG1
SMILES: CCO
"""


@pytest.fixture
def app():
    from boltzmaker_web.app import create_app
    created = create_app()
    created.config["TESTING"] = True
    return created


# ---- the round trip ---------------------------------------------------------

def test_a_plain_spec_derives_and_rebuilds_to_itself(app):
    state = derive_page.derive_verified(MD_PLAIN, {}, app=app)
    assert [r["protein_name[]"] for r in state["groups"]["protein"]] == ["RECP1"]
    assert [r["ligand_name[]"] for r in state["groups"]["ligand"]] == ["LIG1"]
    assert [r["partner_name[]"] for r in state["groups"]["partner"]] == ["CHNX"]


def test_the_features_the_form_used_to_lack_survive(app):
    """Ligand scoping, Group, Family type, Role and an apo path.

    None of these had a form field, which is why no example campaign could be
    loaded back into Step 1. Each is checked by round-tripping, so a field that
    is read but never re-emitted fails here rather than silently vanishing.
    """
    md = """Settings:
Output folder: ./boltz_yamls
Predict affinity: no

Protein: RECP1
Sequence: MDILCEEN
Partners: CHNX
Ligands: LIG1
Apo structure: reference/1abc.pdb
Apo chain: A
Family type: gpcr
Group: RECP

Partner: CHNX
Sequence: MTLESKKAA

Ligand: LIG1
SMILES: CCO
Role: agonist
Class: control
"""
    state = derive_page.derive_verified(md, {}, app=app)
    protein = state["groups"]["protein"][0]
    assert protein["protein_ligands[]"] == "LIG1"
    assert protein["protein_group[]"] == "RECP"
    assert protein["protein_family_type[]"] == "gpcr"
    assert protein["protein_apo_path[]"] == "reference/1abc.pdb"
    assert protein["protein_apo_chain[]"] == "A"
    ligand = state["groups"]["ligand"][0]
    assert ligand["ligand_role[]"] == "agonist"
    assert ligand["ligand_class[]"] == "control"


def test_a_covalent_bond_survives(app):
    """It used to be absorbed as the previous block's field and dropped.

    The parser took any `Key: value` line inside a block as one of its fields, so
    a constraint written after a Ligand block disappeared without a word.
    """
    md = MD_PLAIN + "\nCovalent bond: RECP1 residue 44 atom SG to LIG1 residue 1 atom C3\n"
    state = derive_page.derive_verified(md, {}, app=app)
    row = state["groups"]["constraint"][0]
    assert row["constraint_kind[]"] == "covalent"
    assert row["constraint_owner[]"] == "RECP1"
    assert row["constraint_atom1[]"] == "SG"


def test_the_constraint_reader_is_the_inverse_of_the_writer():
    """Pinned to Constraint.to_sentence() so the pair cannot drift apart."""
    for constraint in (
        wizard.Constraint(kind="covalent", owner="RECP1", residue1="44", atom1="SG",
                          other="LIG1", residue2="1", atom2="C3"),
        wizard.Constraint(kind="distance", owner="RECP1", residue1="10",
                          other="RECP1", residue2="80", distance="8.0"),
    ):
        row = derive_page._constraint_row(constraint.to_sentence())
        assert row["constraint_kind[]"] == constraint.kind
        assert row["constraint_owner[]"] == constraint.owner


def test_an_apo_companion_comes_back_as_the_tick_not_as_a_protein(app):
    """Otherwise the campaign doubles in size on every re-download."""
    built = wizard.assemble_boltz_input_md(
        False, [wizard.ProteinInput(name="RECP1", sequence="MDILCEEN")], [],
        [wizard.LigandInput(name="LIG1", kind="smiles", value="CCO")])
    assert "Ligands: none" in built                      # fixture really has one
    state = derive_page.derive_verified(built, {}, app=app)
    assert len(state["groups"]["protein"]) == 1
    assert state["groups"]["protein"][0]["protein_apo_predict[]"] is True


def test_a_companion_keeps_its_original_name(app):
    """Regenerating it renames the chain, and every output filename with it."""
    md = """Settings:
Output folder: ./boltz_yamls
Predict affinity: no

Protein: RECP1
Sequence: MDILCEEN
Apo structure: boltz_cif/ODDAP_model_0.cif

Protein: ODDAP
Sequence: MDILCEEN
Ligands: none

Ligand: LIG1
SMILES: CCO
"""
    state = derive_page.derive_verified(md, {}, app=app)
    assert state["groups"]["protein"][0]["protein_apo_name[]"] == "ODDAP"


# ---- refusing rather than lying ---------------------------------------------

def test_an_unknown_directive_refuses_instead_of_dropping_it(app):
    md = MD_PLAIN.replace("Sequence: MDILCEEN\n", "Sequence: MDILCEEN\nCyclic: yes\n")
    with pytest.raises(derive_page.DerivationError) as caught:
        derive_page.derive_verified(md, {}, app=app)
    assert "Cyclic" in str(caught.value)


def test_the_round_trip_catches_a_derivation_that_loses_something(app, monkeypatch):
    """The guard must fail when the derivation is wrong, not just when it is right.

    Without this the whole check could be vacuous -- passing because nothing ever
    disagrees rather than because the comparison works.
    """
    real = derive_page.derive

    def lossy(md_text, config=None):
        state = real(md_text, config)
        state["groups"]["ligand"] = state["groups"]["ligand"][:-1]   # drop one
        return state

    monkeypatch.setattr(derive_page, "derive", lossy)
    # Two ligands, so dropping one leaves a valid campaign and the failure has to
    # come from the comparison rather than from the assembler refusing to build.
    two = MD_PLAIN + "\nLigand: LIG2\nSMILES: CCC\n"
    with pytest.raises(derive_page.DerivationError) as caught:
        derive_page.derive_verified(two, {}, app=app)
    assert "would change the campaign" in str(caught.value)
    assert "LIG2" in str(caught.value)


def test_diff_specs_is_blind_to_comments_and_ordering():
    reordered = MD_PLAIN.replace(
        "Protein: RECP1\nSequence: MDILCEEN\nPartners: CHNX",
        "# a comment\nProtein: RECP1\nPartners: CHNX\nSequence: MDILCEEN")
    assert derive_page.diff_specs(MD_PLAIN, reordered) == []


def test_diff_specs_sees_a_changed_value():
    changed = MD_PLAIN.replace("SMILES: CCO", "SMILES: CCC")
    assert derive_page.diff_specs(MD_PLAIN, changed)


# ---- through the upload route -----------------------------------------------

def _command(md_text: str) -> bytes:
    """A bundle with no page_state, exactly like the archived ones."""
    return bundle.build("Derived", md_text, {"accelerator": "auto"}, 1, "{}",
                        run_key="k", private=False).content


def test_a_pageless_bundle_now_loads_through_the_route(app):
    client = app.test_client()
    r = client.post("/auto/prepare/page-state",
                    data={"results_file": (io.BytesIO(_command(MD_PLAIN)), "x.command")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    payload = r.get_json()
    assert payload["derived_from_spec"] is True
    assert payload["groups"]["protein"][0]["protein_name[]"] == "RECP1"


def test_a_pageless_bundle_the_form_cannot_hold_is_refused_with_a_reason(app):
    md = MD_PLAIN.replace("Sequence: MDILCEEN\n", "Sequence: MDILCEEN\nCyclic: yes\n")
    client = app.test_client()
    r = client.post("/auto/prepare/page-state",
                    data={"results_file": (io.BytesIO(_command(md)), "x.command")},
                    content_type="multipart/form-data")
    assert r.status_code == 422
    assert "Cyclic" in r.get_json()["error"]


def test_a_stored_page_still_wins_over_deriving_one(app):
    """Derivation is the fallback. A bundle that saved its page uses that."""
    state = {"scalars": {"campaign_name": "Stored"}, "groups": {}}
    content = bundle.build("Stored", MD_PLAIN, {"accelerator": "auto"}, 1, "{}",
                           run_key="k", private=False,
                           page_state=json.dumps(state)).content
    client = app.test_client()
    r = client.post("/auto/prepare/page-state",
                    data={"results_file": (io.BytesIO(content), "x.command")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json() == state
    assert "derived_from_spec" not in r.get_json()
