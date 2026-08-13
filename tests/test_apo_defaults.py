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


class _Response:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=None): return self.body


class _Server:
    """Serves only the formats it was given, 404s the rest -- like the real RCSB."""

    def __init__(self, **bodies):
        self.bodies = bodies
        self.asked = []

    def __call__(self, url, timeout=None):
        extension = url.rsplit(".", 1)[1]
        self.asked.append(extension)
        if extension not in self.bodies:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Response(self.bodies[extension])


def test_an_entry_published_only_as_mmcif_is_fetched():
    """The bug this covers reported a real structure as nonexistent.

    The legacy PDB format cannot represent a large modern entry, so the RCSB does
    not publish a .pdb for many recent depositions. Asking only for .pdb gave a
    404 and, from it, the flatly untrue message "the PDB has no entry 9LL9" --
    9LL9 being a real cryo-EM 5-HT2A-Gq complex, mmCIF only.
    """
    server = _Server(cif=b"data_9LL9\n_entry.id 9LL9\n")
    data, extension = apo.fetch("9LL9", opener=server)
    assert extension == "cif"
    assert data.startswith(b"data_")


def test_mmcif_is_preferred_when_both_formats_exist():
    """mmCIF is canonical and complete; the legacy file for a large entry can be
    truncated or split. gemmi reads either, so there is no reason to prefer .pdb."""
    server = _Server(cif=b"data_2RH1\n", pdb=b"HEADER    MEMBRANE PROTEIN\n")
    _data, extension = apo.fetch("2RH1", opener=server)
    assert extension == "cif"
    assert server.asked == ["cif"], "the legacy file should not even be requested"


def test_a_legacy_only_entry_still_works():
    server = _Server(pdb=b"HEADER    OLD ENTRY\n")
    data, extension = apo.fetch("1ABC", opener=server)
    assert extension == "pdb"
    assert data.startswith(b"HEADER")
    assert server.asked == ["cif", "pdb"]


def test_no_entry_is_only_claimed_when_neither_format_exists():
    server = _Server()
    with pytest.raises(apo.ApoFetchError) as exc:
        apo.fetch("9ZZZ", opener=server)
    assert "no entry" in str(exc.value)
    assert server.asked == ["cif", "pdb"], "both formats must be tried before saying that"


def test_an_error_page_is_not_mistaken_for_a_structure():
    """A 200 carrying HTML would otherwise be shipped as a structure and fail
    inside the run, hours later."""
    server = _Server(cif=b"<html><body>Service unavailable</body></html>")
    with pytest.raises(apo.ApoFetchError) as exc:
        apo.fetch("2RH1", opener=server)
    assert "does not look like a structure file" in str(exc.value)


def test_the_reference_path_carries_the_format_actually_retrieved():
    """gemmi infers the format from the filename, so a .cif named .pdb is a trap."""
    assert apo.reference_path("9LL9", "cif") == "reference/9ll9.cif"
    assert apo.reference_path("2RH1", "pdb") == "reference/2rh1.pdb"


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
