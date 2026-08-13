"""The apo reference compare-sse needs, and where it comes from.

compare-sse only runs for families that name an `Apo structure:`. The web wizard
never emitted one, so a campaign built on the site could not produce a
secondary-structure comparison at all -- and the "skip compare-sse" option had
nothing to skip. These cover the arrangement that fixed it: predict a ligand-free
companion by default, or use a real experimental structure when one is named.
"""

from __future__ import annotations

import re

import pytest
from werkzeug.datastructures import MultiDict

from boltzmaker_web import apo, bundle
from boltzmaker_web.app import create_app
from boltzmaker_web.views_new import clean_pdb_id
from boltzmaker_web.wizard import (
    LigandInput, ProteinInput, WizardValidationError,
    apo_companion_name, assemble_boltz_input_md,
)

SEQUENCE = ("MNIFEMLRIDEGLRLKIYKDTEGYYTIGIGHLLTKSPSLNAAKSELDKAIGRNTNGVITKDEAEKLFNQ"
            "DVDAAVRGILRNAKLKPVYDSLDAVRRAALINMVFQMGETGVAGFTNSLRMLQQKRWDEAAVNLAKSRW"
            "YNQTPNRAKRVITTFRTGTWDAYKNL")


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _spec(**kwargs) -> str:
    return assemble_boltz_input_md(
        kwargs.pop("predict_affinity", False),
        kwargs.pop("proteins"),
        kwargs.pop("partners", []),
        kwargs.pop("ligands", [LigandInput(name="BNZ", kind="smiles", value="c1ccccc1")]),
        **kwargs,
    )


# ---- the default: a predicted companion ----------------------------------

def test_each_protein_gets_an_apo_companion_by_default():
    """The idiom this repo's own 5HT2 example uses: an extra ligand-free Protein
    block, with the holo family pointing at its predicted CIF."""
    spec = _spec(proteins=[ProteinInput(name="T4L", sequence=SEQUENCE)])
    assert "Apo structure: boltz_cif/T4LAP_model_0.cif" in spec
    assert "Protein: T4LAP" in spec
    assert "Ligands: none" in spec


def test_the_companion_is_the_same_system_without_the_ligand():
    spec = _spec(proteins=[ProteinInput(name="REC", sequence=SEQUENCE,
                                        partner_names=["GNAS", "GNB1"])])
    companion = spec.split("Protein: RECAP")[1]
    assert "Partners: GNAS, GNB1" in companion, "the companion must co-fold the same partners"
    assert "Ligands: none" in companion


def test_skipping_compare_sse_predicts_nothing_extra():
    """Unticking it is what makes the whole arrangement go away -- that is the
    option's only job now, and previously it had none."""
    spec = _spec(proteins=[ProteinInput(name="T4L", sequence=SEQUENCE)], compare_sse=False)
    assert "Apo structure" not in spec
    assert "Ligands: none" not in spec
    assert spec.count("Protein:") == 1


def test_companion_names_stay_inside_the_five_character_namespace():
    """Boltz chain ids cap at 5 characters and share one namespace with every
    protein, partner and ligand, so the companion cannot just be f"{name}_apo"."""
    used = {"ABCDE", "ABCAP", "ABAP"}
    name = apo_companion_name("ABCDE", used)
    assert len(name) <= 5
    assert name not in used


def test_companion_names_do_not_collide_across_many_proteins():
    proteins = [ProteinInput(name=f"P{i:02d}", sequence=SEQUENCE) for i in range(12)]
    spec = _spec(proteins=proteins)
    declared = re.findall(r"^Protein: (\S+)$", spec, re.M)
    assert len(declared) == len(set(declared)), f"duplicate chain id: {declared}"
    assert all(len(name) <= 5 for name in declared)


# ---- a real experimental structure ---------------------------------------

def test_a_named_pdb_replaces_the_companion_rather_than_adding_to_it():
    """Measured beats predicted: if a real apo structure is given there is no
    reason to spend GPU time predicting one."""
    spec = _spec(proteins=[ProteinInput(name="T4L", sequence=SEQUENCE, apo_pdb="2RH1")],
                 apo_reference_paths={"T4L": "reference/2rh1.pdb"})
    assert "Apo structure: reference/2rh1.pdb" in spec
    assert "Ligands: none" not in spec
    assert spec.count("Protein:") == 1


@pytest.mark.parametrize("raw,expected", [("2rh1", "2RH1"), ("  6LU7 ", "6LU7"), ("", "")])
def test_pdb_ids_are_normalised(raw, expected):
    assert clean_pdb_id(raw) == expected


@pytest.mark.parametrize("raw", ["ABCD", "12345", "../etc/passwd", "2RH"])
def test_bad_pdb_ids_are_refused(raw):
    """The id is interpolated into a download URL and then a filename inside the
    campaign the user runs; neither should ever see an unchecked string."""
    with pytest.raises(WizardValidationError):
        clean_pdb_id(raw)


def test_a_missing_pdb_entry_is_reported_not_swallowed():
    class NotFound:
        def __call__(self, url, timeout=None):
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    with pytest.raises(apo.ApoFetchError) as exc:
        apo.fetch("9ZZZ", opener=NotFound())
    assert "no entry" in str(exc.value)


def test_an_error_page_is_not_mistaken_for_a_structure():
    """A 200 carrying HTML would otherwise be shipped as a structure and fail
    inside the run, hours later."""
    class HtmlPage:
        def __call__(self, url, timeout=None):
            return self
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=None): return b"<html><body>Service unavailable</body></html>"

    with pytest.raises(apo.ApoFetchError) as exc:
        apo.fetch("2RH1", opener=HtmlPage())
    assert "does not look like a PDB file" in str(exc.value)


# ---- through the form -----------------------------------------------------

def _form(**overrides) -> MultiDict:
    data = MultiDict([
        ("campaign_name", "Apo test"),
        ("protein_name[]", "T4L"), ("protein_sequence[]", SEQUENCE),
        ("protein_partners[]", ""), ("protein_apo_pdb[]", ""),
        ("ligand_name[]", "BNZ"), ("ligand_kind[]", "smiles"), ("ligand_value[]", "c1ccccc1"),
    ])
    for key, value in overrides.items():
        field = "protein_apo_pdb[]" if key == "protein_apo_pdb" else key
        data.setlist(field, [value])
    return data


def test_prepare_ships_a_campaign_that_can_actually_compare(client):
    response = client.post("/auto/prepare", data=_form())
    assert response.status_code == 200
    spec = bundle.unpack(response.data)["boltz_input.md"].decode()
    assert "Apo structure:" in spec


def test_prepare_with_skip_sse_ships_no_apo_at_all(client):
    response = client.post("/auto/prepare", data=_form(skip_sse="1"))
    spec = bundle.unpack(response.data)["boltz_input.md"].decode()
    assert "Apo structure" not in spec


def test_a_malformed_pdb_id_stops_at_the_form(client):
    """Not three hours into a run, which is where a bad reference used to surface."""
    response = client.post("/auto/prepare", data=_form(protein_apo_pdb="NOPE"))
    assert response.headers.get("Content-Disposition") is None
    assert "is not a PDB id" in response.data.decode()
