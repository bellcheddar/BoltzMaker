"""Prepare-form additions: PDB verification, apo uploads, partner picking.

Four things that were all the same complaint -- the form asked people to retype
what it already knew, or to trust an identifier it never read back.
"""

from __future__ import annotations

import io
import json

import pytest

from boltzmaker_web import apo


@pytest.fixture
def client():
    from boltzmaker_web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ---- reading a PDB id back --------------------------------------------------

def test_a_bad_pdb_id_is_refused_without_asking_rcsb(client):
    for bad in ("zzzz", "1", "12345", "abcd"):
        r = client.get(f"/auto/pdb/{bad}.json")
        assert r.status_code == 400, bad
        assert "4-character" in r.get_json()["error"]


def test_the_lookup_reports_bound_ligands(client, monkeypatch):
    """The ligand list is the point: "apo" in a title is not a guarantee.

    Stubbed rather than hitting RCSB, so the test says something about this code
    and not about the network.
    """
    payload = {"data": {"entry": {
        "struct": {"title": "Structure of the receptor with a modulator"},
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "rcsb_accession_info": {"initial_release_date": "2017-05-31T00:00:00Z"},
        "rcsb_entry_info": {"resolution_combined": [2.7],
                            "polymer_entity_count_protein": 1},
        "nonpolymer_entities": [
            {"nonpolymer_comp": {"chem_comp": {"id": "97Y", "name": "a modulator"}}},
            {"nonpolymer_comp": {"chem_comp": {"id": "OLA", "name": "oleic acid"}}},
        ],
    }}}

    class _Response:
        def read(self):
            return json.dumps(payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("boltzmaker_web.views_auto.urllib.request.urlopen",
                        lambda *a, **k: _Response())
    body = client.get("/auto/pdb/5vew.json").get_json()
    assert body["pdb_id"] == "5VEW"
    assert body["resolution"] == 2.7
    assert [l["id"] for l in body["ligands"]] == ["97Y", "OLA"]
    assert body["released"] == "2017-05-31"


def test_an_entry_that_does_not_exist_is_a_404(client, monkeypatch):
    class _Response:
        def read(self):
            return json.dumps({"data": {"entry": None}}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("boltzmaker_web.views_auto.urllib.request.urlopen",
                        lambda *a, **k: _Response())
    r = client.get("/auto/pdb/9zzz.json")
    assert r.status_code == 404


# ---- taking a structure from the user's machine -----------------------------

CIF = b"data_XYZ\n_entry.id XYZ\n"
PDB = b"ATOM      1  N   MET A   1      11.104   6.134  -6.504\n"


def test_an_uploaded_structure_lands_under_reference():
    path, data = apo.accept_upload("2rh1_apo.cif", CIF)
    assert path == "reference/2rh1_apo.cif"
    assert data == CIF
    assert apo.accept_upload("model.pdb", PDB)[0] == "reference/model.pdb"


def test_a_filename_cannot_escape_the_reference_folder():
    """The name ends up as a path inside an archive somebody unpacks."""
    path, _ = apo.accept_upload("../../etc/passwd.pdb", PDB)
    assert path == "reference/passwd.pdb"
    assert ".." not in path


def test_awkward_filenames_are_made_safe():
    path, _ = apo.accept_upload("My Structure (1).cif", CIF)
    assert path == "reference/my_structure__1.cif"


def test_the_contents_are_sniffed_not_taken_from_the_extension():
    """A .cif that is not a CIF fails on someone else's machine otherwise."""
    with pytest.raises(apo.ApoFetchError) as caught:
        apo.accept_upload("notreally.cif", b"hello world, this is prose")
    assert "does not look like" in str(caught.value)


def test_the_obvious_refusals_each_say_why():
    cases = {
        "notes.txt": (CIF, "not a .cif or .pdb"),
        "empty.cif": (b"   ", "is empty"),
        "huge.cif": (CIF + b"x" * (apo.MAX_UPLOAD_BYTES + 1), "the limit for a structure"),
    }
    for name, (blob, expected) in cases.items():
        with pytest.raises(apo.ApoFetchError) as caught:
            apo.accept_upload(name, blob)
        assert expected in str(caught.value), name
        assert getattr(caught.value, "field", "") == "protein_apo_pdb"


# ---- the form carries it ----------------------------------------------------

def test_the_prepare_form_is_multipart_and_names_uploads_per_row(client):
    """Both halves of getting a file to the server.

    A urlencoded form posts the filename without the file; and an empty file input
    posts nothing at all, so a `name[]` array would be shorter than every other
    field and each upload would attach to the wrong protein.
    """
    page = client.get("/auto/prepare").get_data(as_text=True)
    assert 'enctype="multipart/form-data"' in page
    assert "data-apo-upload" in page
    assert 'name="protein_apo_file' not in page, (
        "the name is stamped per row by wizard.js, not written into the template")


def test_the_partner_picker_replaced_the_typed_list(client):
    page = client.get("/auto/prepare").get_data(as_text=True)
    assert "data-partner-picker" in page
    # Still one hidden comma-separated field per row: the server contract and the
    # parallel-array alignment are unchanged, only how it gets filled in.
    assert 'name="protein_partners[]"' in page
    assert 'type="hidden" name="protein_partners[]"' in page


def test_recycling_defaults_to_four_for_a_new_campaign(client):
    page = client.get("/auto/prepare").get_data(as_text=True)
    marker = 'name="targets_per_invocation"'
    assert marker in page
    segment = page[page.index(marker) - 200:page.index(marker) + 200]
    assert 'value="4"' in segment


# ---- the partner picker has to hear about programmatic fills ----------------

def _wizard_js() -> str:
    from pathlib import Path
    return (Path(__file__).parent.parent / "web/static/js/wizard.js").read_text()


def test_uniprot_autofill_announces_the_fields_it_fills():
    """Setting .value in script fires no event, so nothing downstream hears it.

    Filling a partner from its accession left the proteins' partner pickers
    unaware of it until some later edit happened to trigger a re-sync, which read
    as "partners only appear when I add another one". Autosave missed it the same
    way. Asserted structurally because the fix is that the assignment goes through
    a helper that dispatches -- a direct `fields.name.value =` is the bug.
    """
    source = _wizard_js()
    assert "function setFilled(" in source
    assert 'field.dispatchEvent(new Event("input"' in source
    assert 'field.dispatchEvent(new Event("change"' in source
    assert "setFilled(fields.name," in source
    assert "setFilled(fields.sequence," in source
    assert "fields.name.value = entry.gene" not in source
    assert "fields.sequence.value = entry.sequence" not in source


def test_the_picker_resyncs_on_every_way_a_partner_name_can_change():
    source = _wizard_js()
    for trigger in ('"boltz:wizard-ready", syncAll',
                    '"boltz:form-changed", syncAll',
                    '"boltz:page-applied", syncAll'):
        assert trigger in source, trigger
    assert '["input", "change"].forEach' in source
