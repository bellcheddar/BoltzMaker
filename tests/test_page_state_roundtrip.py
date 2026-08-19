"""Carrying the wizard's own state through a campaign and back.

Extending a finished campaign should start on the page it was built on. The
alternative -- reconstructing the form from boltz_input.md -- loses everything
the spec does not carry: a pocket's PDB id has become contact tokens by then,
and a ticked checkbox has become an absence.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from boltzmaker_web import views_auto


class _Form(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


def test_a_valid_page_state_is_kept():
    state = {"protein_sequence[]": ["MKT"], "ligand_value[]": ["CCO"]}
    out = views_auto._page_state_from(_Form(page_state=json.dumps(state)))
    assert json.loads(out) == state


def test_it_is_reserialised_not_forwarded():
    """What ends up in a file other people download is a document this server
    produced, not a string it passed along unread."""
    out = views_auto._page_state_from(_Form(page_state='{"b":1,"a":2}'))
    assert out.index('"a"') < out.index('"b"')      # sorted -> rebuilt


def test_junk_is_dropped_rather_than_stored():
    for junk in ("", "   ", "not json", "[1,2,3]", "null", '"a string"'):
        assert views_auto._page_state_from(_Form(page_state=junk)) == ""


def test_an_implausibly_large_state_is_refused():
    """This arrives from a browser and ends up inside a bundle."""
    huge = json.dumps({"x": "y" * (600 * 1024)})
    assert views_auto._page_state_from(_Form(page_state=huge)) == ""


def test_a_missing_field_is_not_an_error():
    """A bundle without a saved page still runs -- it just cannot reload the form."""
    assert views_auto._page_state_from(_Form()) == ""


# ---------------------------------------------------------------------------
#  Reading it back out of a results archive
# ---------------------------------------------------------------------------

def _bmz(members: dict) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    buf.seek(0)
    return buf


@pytest.fixture
def client():
    from boltzmaker_web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _post(client, buf, name="results.bmz"):
    return client.post("/auto/prepare/page-state",
                       data={"results_file": (buf, name)},
                       content_type="multipart/form-data")


def test_the_state_comes_back_out(client):
    state = {"protein_name[]": ["GLP1R"], "ligand_value[]": ["CCO"]}
    r = _post(client, _bmz({"page_state.json": json.dumps(state)}))
    assert r.status_code == 200 and r.get_json() == state


def test_an_older_bundle_says_so_rather_than_failing_obscurely(client):
    r = _post(client, _bmz({"boltz_input.md": "Protein: X\n"}))
    assert r.status_code == 404
    assert "before the wizard started storing one" in r.get_json()["error"]


def test_something_that_is_not_a_zip(client):
    r = _post(client, io.BytesIO(b"this is not a zip"))
    assert r.status_code == 400


def test_a_member_that_lies_about_being_small_is_refused(client):
    """A zip is an archive of whatever its author chose."""
    r = _post(client, _bmz({"page_state.json": json.dumps({"x": "y" * (600 * 1024)})}))
    assert r.status_code == 413


def test_a_state_that_is_not_a_form(client):
    r = _post(client, _bmz({"page_state.json": "[1, 2, 3]"}))
    assert r.status_code == 422


def test_no_file_at_all(client):
    r = client.post("/auto/prepare/page-state", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
#  Keeping a ligand on its own protein
# ---------------------------------------------------------------------------

def test_the_setting_is_on_by_default_and_silent():
    """On is the default, so a spec built with it on is byte-identical to what the
    wizard produced before this option existed."""
    from boltzmaker_web import wizard
    from boltzmaker_web.wizard import ProteinInput, LigandInput
    md = wizard.assemble_boltz_input_md(
        False, [ProteinInput(name="RECP", sequence="MKTAYIAK")], [],
        [LigandInput(name="LIG", value="CCO", kind="smiles")])
    assert "Confine to receptor" not in md


def test_turning_it_off_is_written_into_the_spec():
    from boltzmaker_web import wizard
    from boltzmaker_web.wizard import ProteinInput, LigandInput
    md = wizard.assemble_boltz_input_md(
        False, [ProteinInput(name="RECP", sequence="MKTAYIAK")], [],
        [LigandInput(name="LIG", value="CCO", kind="smiles")],
        confine_to_receptor=False)
    assert "Confine to receptor: no" in md


def test_the_checkbox_is_ticked_by_default_in_the_form():
    """A ligand docking onto a co-folded partner is the failure this prevents, so it
    has to be the default rather than something you remember to turn on."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "web" / "templates" / "_wizard_fields.html").read_text()
    i = html.index('name="confine_to_receptor"')
    assert "checked" in html[i:i + 80]
