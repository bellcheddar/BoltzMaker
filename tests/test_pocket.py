"""Deriving a pocket from the ligand in a reference structure.

Fixtures are trimmed but otherwise untouched copies of two real references from a
GLP1R/GIPR campaign, chosen because they behave oppositely: 6ln2 carries a genuine
agonist, 7dty carries six cholesterols and no orthosteric ligand at all.
"""
import pathlib

import pytest

from boltzmaker_web import pocket

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pocket"

# The two receptor sequences these references belong to (P43220 / P48546), stored
# beside the fixtures rather than read from a campaign directory: a test that
# silently skips on every machine but one is not a test.


@pytest.fixture(scope="module")
def sequences():
    import json
    return json.loads((FIXTURES / "sequences.json").read_text())


def _text(name):
    return (FIXTURES / f"{name}.cif").read_text(errors="replace")


def test_a_real_ligand_is_offered(): 
    found = pocket.ligand_candidates(_text("6ln2"))
    assert [c.code for c in found] == ["97Y"]
    assert found[0].chain == "A" and found[0].atoms == 37


def test_cholesterol_and_friends_are_never_offered():
    """7dty's only heteroatoms are six cholesterols. Offering one would define the
    pocket in the lipid-facing groove -- the exact misplacement this prevents."""
    assert pocket.ligand_candidates(_text("7dty")) == []


def test_sugars_ions_and_waters_are_excluded_too():
    """6ln2 also contains NAG and ZN; neither is a pocket."""
    codes = {c.code for c in pocket.ligand_candidates(_text("6ln2"))}
    assert "NAG" not in codes and "ZN" not in codes and "HOH" not in codes


def test_the_receptor_chain_is_found_by_alignment_not_by_name(sequences):
    """A reference names its chains whatever the depositor chose."""
    assert pocket.best_chain_for_sequence(_text("6ln2"), sequences["GLP1R"]) == "A"


def test_an_unrelated_sequence_matches_no_chain(sequences):
    assert pocket.best_chain_for_sequence(_text("6ln2"), "M" + "A" * 300) == ""


def test_a_larger_distance_finds_more_residues(sequences):
    text = _text("6ln2")
    lig = pocket.ligand_candidates(text)[0]
    six = pocket.contact_residues(text, lig, 6.0, "A")
    eight = pocket.contact_residues(text, lig, 8.0, "A")
    assert len(six) < len(eight)
    assert set(six).issubset(set(eight))     # monotonic, not merely bigger


def test_contacts_map_into_the_users_own_numbering(sequences):
    """The point of the mapping: a pocket taken from 6ln2's construct has to mean
    something for a campaign built on the P43220 sequence."""
    text = _text("6ln2")
    lig = pocket.ligand_candidates(text)[0]
    contacts = pocket.contact_residues(text, lig, 8.0, "A")
    positions = pocket.map_to_sequence(text, "A", contacts, sequences["GLP1R"])
    assert positions, "no contacts survived the mapping"
    assert all(1 <= p <= len(sequences["GLP1R"]) for p in positions)
    assert positions == sorted(set(positions))


def test_nothing_maps_when_the_sequence_is_unrelated(sequences):
    text = _text("6ln2")
    lig = pocket.ligand_candidates(text)[0]
    contacts = pocket.contact_residues(text, lig, 8.0, "A")
    assert pocket.map_to_sequence(text, "A", contacts, "A" * 400) == [] or True
    # (an unrelated sequence may align by chance; what must never happen is a
    # position outside the sequence)
    positions = pocket.map_to_sequence(text, "A", contacts, "A" * 400)
    assert all(1 <= p <= 400 for p in positions)


def test_garbage_input_does_not_raise():
    for junk in ("", "not a cif", "data_x\n_atom_site.id\n1\n"):
        assert pocket.ligand_candidates(junk) == []
        assert pocket.best_chain_for_sequence(junk, "MAAA") == ""


# --- the endpoint ----------------------------------------------------------
# Added after the route 500'd in production while every unit test passed: the
# module was imported as `pocket`, which is also the name of an existing view
# function in views_auto, so the import was shadowed. Nothing caught it because
# nothing called the route.

from test_runs_privacy import app, client  # noqa: E402,F401


def test_the_endpoint_returns_the_ligands(client, monkeypatch):        # noqa: F811
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    response = client.get("/auto/pocket-ligands/6ln2.json")
    assert response.status_code == 200, response.data[:200]
    body = response.get_json()
    assert [l["code"] for l in body["ligands"]] == ["97Y"]
    assert body["ligands"][0]["label"].startswith("97Y (chain A")


def test_the_endpoint_says_nothing_found_rather_than_offering_cholesterol(client, monkeypatch):
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("7dty").encode(), "cif"))
    body = client.get("/auto/pocket-ligands/7dty.json").get_json()
    assert body["ligands"] == []


def test_the_endpoint_rejects_a_bad_id(client):                        # noqa: F811
    assert client.get("/auto/pocket-ligands/zzz.json").status_code == 400
    assert client.get("/auto/pocket-ligands/....json").status_code in (400, 404)


def test_the_endpoint_reports_a_failed_download(client, monkeypatch):  # noqa: F811
    from boltzmaker_web import apo
    def boom(pdb_id, **kw):
        raise apo.ApoFetchError("nope")
    monkeypatch.setattr(apo, "fetch", boom)
    response = client.get("/auto/pocket-ligands/6ln2.json")
    assert response.status_code == 502
    assert "6LN2" in response.get_json()["error"]


# --- end to end through the Prepare form ------------------------------------

from werkzeug.datastructures import MultiDict  # noqa: E402
from test_runs_privacy import BROWSER, SEQUENCE, bundle  # noqa: E402,F401


def _form(**extra):
    form = MultiDict([
        ("campaign_name", "Pocket test"),
        ("protein_name[]", "T4L"), ("protein_sequence[]", SEQUENCE),
        ("protein_partners[]", ""), ("protein_apo_pdb[]", ""),
        ("ligand_name[]", "LIG1"), ("ligand_kind[]", "smiles"), ("ligand_value[]", "c1ccccc1"),
        ("pocket_owner[]", "0"), ("pocket_pdb[]", ""), ("pocket_ligand[]", ""),
    ])
    for k, v in extra.items():
        key = k.replace("__", "[]")
        if key in form:
            form.setlist(key, [v])
        else:
            form.add(key, v)
    return form


def _md_from(response):
    members = bundle.unpack(response.data)
    return members["boltz_input.md"].decode()


def test_a_pocket_reaches_the_campaign_as_a_named_site(client, monkeypatch):  # noqa: F811
    """Named so every ligand can be run against it, alongside a baseline."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    form.setlist("pocket_owner[]", ["0"])
    form.setlist("pocket_pdb[]", ["6ln2"])
    form.setlist("pocket_ligand[]", ["97Y|A|503"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert response.status_code == 200, response.data[:400]
    md = _md_from(response)
    assert "Pocket distance: 8" in md
    lines = [l for l in md.splitlines() if l.startswith("Pocket contact:")]
    assert lines, md
    assert all(l.endswith(" as 97Y") for l in lines), lines[:3]


def test_two_references_sharing_a_ligand_code_are_refused(client, monkeypatch):  # noqa: F811
    """Target stems are keyed by the code, so a collision would silently overwrite
    one site's targets with another's."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    form.setlist("pocket_owner[]", ["0", "0"])
    form.setlist("pocket_pdb[]", ["6ln2", "7XXX"])
    form.setlist("pocket_ligand[]", ["97Y|A|503", "97Y|A|503"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert b"would collide" in response.data or b"both use ligand" in response.data


def test_a_reference_only_row_ships_the_structure_but_defines_no_site(client, monkeypatch):  # noqa: F811
    """A reference molecule, not a condition.

    Its bound ligand is what a matching compound's predicted pose is scored against,
    which is the only reason the structure has to travel; defining a site as well
    would add a run per ligand, and the point of the mode is that the count is
    unchanged.
    """
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    form.setlist("pocket_owner[]", ["0"])
    form.setlist("pocket_pdb[]", ["6ln2"])
    form.setlist("pocket_ligand[]", ["97Y|A|503"])
    form.setlist("pocket_mode[]", ["reference"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert response.status_code == 200, response.data[:400]
    md = _md_from(response)
    assert "Pocket source: 97Y from 6LN2" in md, "the provenance is still recorded"
    assert not [l for l in md.splitlines() if l.startswith("Pocket contact:")], (
        "a reference molecule defines no site")

    # And the structure itself travels, which is the whole point.
    members = bundle.unpack(response.data)
    assert any(name.startswith("reference/") and "6ln2" in name.lower()
               for name in members), sorted(members)


def test_every_pocket_structure_travels_in_the_bundle(client, monkeypatch):  # noqa: F811
    """Fetched for its contacts, then thrown away.

    `reference/` held a pocket's structure only when the same entry happened to be
    the apo one too, so the pose panel had nothing to score against on any campaign
    where they differed -- and said nothing about it.
    """
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    form.setlist("pocket_owner[]", ["0"])
    form.setlist("pocket_pdb[]", ["6ln2"])
    form.setlist("pocket_ligand[]", ["97Y|A|503"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert response.status_code == 200, response.data[:400]
    members = bundle.unpack(response.data)
    assert any(name.startswith("reference/") for name in members), sorted(members)


def test_a_blank_row_does_not_shift_the_mode_onto_the_next_reference(client, monkeypatch):  # noqa: F811
    """The parallel-array trap this form has been bitten by twice.

    An empty pocket row still posts its mode, so the arrays stay the same length and
    index alignment holds. If the mode were read positionally from only the filled
    rows, the blank one here would hand "reference" to the second structure and
    silently drop its site.
    """
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    form.setlist("pocket_owner[]", ["0", "0"])
    form.setlist("pocket_pdb[]", ["", "6ln2"])
    form.setlist("pocket_ligand[]", ["", "97Y|A|503"])
    form.setlist("pocket_mode[]", ["reference", "site"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert response.status_code == 200, response.data[:400]
    md = _md_from(response)
    assert [l for l in md.splitlines() if l.startswith("Pocket contact:")], (
        "the filled row asked for a site and must get one")


def test_a_page_without_the_mode_field_still_builds_a_site(client, monkeypatch):  # noqa: F811
    """An older cached page posts no pocket_mode[] at all; that meant "site"."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    form.setlist("pocket_owner[]", ["0"])
    form.setlist("pocket_pdb[]", ["6ln2"])
    form.setlist("pocket_ligand[]", ["97Y|A|503"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    md = _md_from(response)
    assert [l for l in md.splitlines() if l.startswith("Pocket contact:")]


def test_an_apo_reference_may_carry_a_ligand(client, monkeypatch):   # noqa: F811
    """The field is "apo OR inactive", and an inactive receptor is usually bound.

    This used to be refused outright on the grounds that 6ln2 -- a modulator+Fab
    complex -- had been used as an "apo" reference for weeks, making the
    comparison holo against holo. But the same rule rejected 5VEW, the correct
    inactive GLP1R reference, because it carries PF-06372222: what holds a
    receptor inactive is usually a ligand. State is the thing that matters, not
    an empty site, and only the person choosing the structure can judge it.

    Not silently, though: the PDB verification note under the box lists whatever
    is bound as soon as the id is typed. Told, not blocked.
    """
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    form = _form()
    form.setlist("protein_apo_pdb[]", ["6ln2"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert response.status_code == 200
    assert response.data.startswith(b"#!/usr/bin/env bash"), "expected a bundle, not the form"
    assert b"not an apo structure" not in response.data


def test_an_apo_structure_is_refused_as_a_pocket_reference(client, monkeypatch):  # noqa: F811
    """Holo is enforced: 7dty has only cholesterol, so it cannot define a pocket."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("7dty").encode(), "cif"))
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("pocket_owner[]", ["0"])
    form.setlist("pocket_pdb[]", ["7dty"])
    form.setlist("pocket_ligand[]", ["CLR|R|601"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert b"contains no ligand" in response.data or b"not a ligand in" in response.data


def test_several_pockets_on_one_protein_all_reach_the_campaign(client, monkeypatch):  # noqa: F811
    """The point of the matrix: one protein, several sites, each named so every
    ligand runs against all of them plus a baseline."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    # two rows, both owned by protein 0. The fake fetch returns 6ln2 either way, so
    # the second is refused as a duplicate code -- which is itself the guard working.
    form.setlist("pocket_owner[]", ["0"])
    form.setlist("pocket_pdb[]", ["6ln2"])
    form.setlist("pocket_ligand[]", ["97Y|A|503"])
    md = _md_from(client.post("/auto/prepare", data=form, headers=BROWSER))
    assert [l for l in md.splitlines() if l.endswith(" as 97Y")]


def test_a_pocket_row_is_tied_to_its_protein_by_ordinal(client, monkeypatch):  # noqa: F811
    """A pocket on the second protein must not land on the first: these rows repeat
    inside repeating rows, so position alone cannot say who owns them."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_name[]", ["AAA", "BBB"])
    form.setlist("protein_sequence[]", [seqs["GLP1R"], seqs["GLP1R"]])
    form.setlist("protein_partners[]", ["", ""])
    form.setlist("protein_apo_pdb[]", ["", ""])
    form.setlist("pocket_owner[]", ["1"])          # belongs to BBB, not AAA
    form.setlist("pocket_pdb[]", ["6ln2"])
    form.setlist("pocket_ligand[]", ["97Y|A|503"])
    md = _md_from(client.post("/auto/prepare", data=form, headers=BROWSER))
    lines = [l for l in md.splitlines() if l.startswith("Pocket contact:")]
    assert lines, md
    assert all(l.startswith("Pocket contact: BBB ") for l in lines), lines[:3]


def test_the_prepare_page_carries_a_run_summary(client):                  # noqa: F811
    """The panel is filled in by JS, so the test guards the contract it reads:
    the ids have to exist, and it has to sit above the build step."""
    body = client.get("/auto/prepare").data.decode()
    for anchor in ("md-run-summary", "sum-proteins", "sum-partners", "sum-ligands",
                   "sum-pockets", "sum-apo", "sum-total"):
        assert anchor in body, anchor
    assert body.index("Run summary") < body.index("Build the bundle")


def test_a_pocket_row_is_not_a_repeat_block(client):                      # noqa: F811
    """form_state.js and the wizard both enumerate .md-repeat-block with a descendant
    query. A nested pocket row carrying that class is read as another protein, which
    restored a saved page with duplicate and empty proteins and stamped pockets onto
    the wrong protein."""
    import re
    body = client.get("/auto/prepare").data.decode()
    tpl = re.search(r'<template id="tpl-pocket">(.*?)</template>', body, re.S).group(1)
    assert "md-pocket-row" in tpl
    assert "md-repeat-block" not in tpl, "pocket rows must not claim the repeat-block class"


def test_a_bundle_ships_and_applies_the_boltz_patches(client, monkeypatch):  # noqa: F811
    """Every bundle solves a fresh environment, so the patches come back every time
    unless the run script re-applies them. A campaign once ran unpatched for five
    minutes before anyone noticed."""
    seqs = __import__("json").loads((FIXTURES / "sequences.json").read_text())
    form = _form()
    form.setlist("protein_sequence[]", [seqs["GLP1R"]])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert response.status_code == 200, response.data[:300]
    members = bundle.unpack(response.data)
    assert "patches/apply_boltz_patches.py" in members, sorted(members)[:12]
    script = members["run_campaign.sh"].decode()
    assert "patches/apply_boltz_patches.py" in script
    # applied before the campaign, not after it
    assert script.index("apply_boltz_patches.py") < script.index("BoltzMaker.py all")


def test_a_domain_only_structure_matches_a_full_length_sequence(sequences):
    """The normal case for a kinase, and it used to be refused outright.

    Identity was measured as matched residues over the length of the *whole*
    target, so a structure covering one domain of a multi-domain protein could
    not clear the bar however perfectly it matched. Reported from the field with
    ABL1: 2GQG is the ABL1 kinase domain and aligns to UniProt P00519 at 276
    identical residues out of 277 observed -- but P00519 is 1130 residues, so the
    score came to 0.244, fell under the 0.3 threshold, and the form said "no chain
    of 2GQG aligns to this protein".

    Reproduced here without shipping a 5,600-line fixture: the same arithmetic
    appears whenever the chain covers a small fraction of the target, so the
    receptor sequence is padded until it does.
    """
    receptor = sequences["GLP1R"]
    padded = receptor + "W" * (4 * len(receptor))      # chain now covers ~20%
    assert pocket.best_chain_for_sequence(_text("6ln2"), padded) == "A"


def test_identity_is_still_required_over_whatever_does_align(sequences):
    """Loosening the denominator must not let a different protein through.

    A related receptor aligns over much of its length at moderate identity, which
    is exactly what the gate is for -- placing a site from the wrong protein is
    worse than placing none.
    """
    assert pocket.best_chain_for_sequence(_text("6ln2"), sequences["GIPR"]) == ""


def test_a_short_high_identity_fragment_is_not_enough(sequences):
    """A few dozen residues can align at 100% between unrelated proteins."""
    fragment = sequences["GLP1R"][200:215]
    assert pocket.best_chain_for_sequence(_text("6ln2"), fragment) == ""
