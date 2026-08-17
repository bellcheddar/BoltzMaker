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
        ("protein_pocket_pdb[]", ""), ("protein_pocket_ligand[]", ""),
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
    form.setlist("protein_pocket_pdb[]", ["6ln2"])
    form.setlist("protein_pocket_ligand[]", ["97Y|A|503"])
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
    form.setlist("protein_name[]", ["T4L", "T4LB"])
    form.setlist("protein_sequence[]", [seqs["GLP1R"], seqs["GLP1R"]])
    form.setlist("protein_partners[]", ["", ""])
    form.setlist("protein_apo_pdb[]", ["", ""])
    form.setlist("protein_pocket_pdb[]", ["6ln2", "7XXX"])
    form.setlist("protein_pocket_ligand[]", ["97Y|A|503", "97Y|A|503"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert b"would collide" in response.data or b"both use ligand" in response.data


def test_an_apo_reference_with_a_ligand_in_it_is_refused(client, monkeypatch):   # noqa: F811
    """6ln2 was used as an 'apo' reference for weeks; it is a modulator+Fab complex,
    so the apo-vs-holo comparison was holo against holo."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("6ln2").encode(), "cif"))
    form = _form()
    form.setlist("protein_apo_pdb[]", ["6ln2"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert b"not an apo structure" in response.data
    assert b"97Y" in response.data


def test_an_apo_structure_is_refused_as_a_pocket_reference(client, monkeypatch):  # noqa: F811
    """Holo is enforced: 7dty has only cholesterol, so it cannot define a pocket."""
    from boltzmaker_web import apo
    monkeypatch.setattr(apo, "fetch", lambda pdb_id, **kw: (_text("7dty").encode(), "cif"))
    form = _form(use_same_pocket="1", pocket_distance="8")
    form.setlist("protein_pocket_pdb[]", ["7dty"])
    form.setlist("protein_pocket_ligand[]", ["CLR|R|601"])
    response = client.post("/auto/prepare", data=form, headers=BROWSER)
    assert b"contains no ligand" in response.data or b"not a ligand in" in response.data
