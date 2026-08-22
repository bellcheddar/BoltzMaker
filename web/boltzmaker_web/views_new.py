from __future__ import annotations

import itertools
import re

import shutil

from flask import Blueprint, Response, current_app, render_template, request

from .app import new_scratch_dir
from .runner import BoltzMakerTimeout, extract_error_message, run_boltzmaker
from .wizard import (
    Constraint,
    LIGAND_ROLES,
    LigandInput,
    PartnerInput,
    ProteinInput,
    WizardValidationError,
    assemble_boltz_input_md,
    validate_name,
)

bp = Blueprint("new", __name__)


PDB_ID_RE = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
# UniProt's own accession grammar: six or ten characters, and the ten-character
# form is the one modern entries (A0A2I2YKA3) use. An isoform or version suffix
# is accepted and dropped -- P28223-1 names a sequence, and AlphaFold is keyed on
# the entry.
UNIPROT_RE = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$")


def clean_pdb_id(raw: str) -> str:
    """Normalise an optional PDB id, or raise.

    A PDB id is four characters beginning with a digit. Validated here rather than
    trusted, because it is interpolated into a download URL and then into a
    filename inside the campaign the user runs -- neither of which should ever see
    an unchecked string.
    """
    value = (raw or "").strip().upper()
    if not value:
        return ""
    if not PDB_ID_RE.match(value):
        raise WizardValidationError(
            f"'{value}' is not a PDB id -- they are four characters starting with a "
            "digit, like 2RH1. Leave it blank to have an apo structure predicted instead.",
            field="protein_apo_pdb",
        )
    return value


def clean_reference_path(raw: str) -> str:
    """A path to a file the campaign carries, relative to its own folder.

    Absolute paths and parent traversal are refused rather than cleaned: this
    string is written into a spec that runs on someone's machine, and "reference/"
    plus a filename is the only shape the bundle can actually deliver. Refusing is
    also the honest answer -- silently rewriting a path would produce a campaign
    that points somewhere the author did not mean.
    """
    value = (raw or "").strip().replace("\\", "/")
    if not value:
        return ""
    if value.startswith("/") or value.startswith("~") or ".." in value.split("/"):
        raise WizardValidationError(
            f"Apo structure path '{raw}' must be inside the campaign folder, "
            "e.g. reference/2rh1_apo.pdb.", field="protein_apo_path")
    return value


def clean_accession(raw: str) -> str:
    """Normalise an optional UniProt accession, or raise.

    Checked here rather than trusted, for the same reason the PDB id is: it ends
    up interpolated into a request to two external APIs.
    """
    value = (raw or "").strip().upper().split("-")[0].split(".")[0]
    if not value:
        return ""
    if not UNIPROT_RE.match(value):
        raise WizardValidationError(
            f"'{value}' is not a UniProt accession -- they look like P28223 or "
            "A0A2I2YKA3. Leave it blank and the explorer will try to find it from "
            "the sequence instead.",
            field="protein_uniprot",
        )
    return value


def _parse_form() -> tuple[bool, list[ProteinInput], list[PartnerInput], list[LigandInput]]:
    """Parses the flat parallel-array form fields new_wizard.html/wizard.js
    produce back into the dataclasses wizard.py's assembler expects. Uses one
    shared `used_names` set across proteins/partners/ligands, exactly
    matching cmd_new's own single shared-namespace enforcement."""
    used_names: set[str] = set()

    predict_affinity = request.form.get("predict_affinity") == "on"
    # Checked by default in the form, so an absent value on a hand-built POST means
    # off; the form always sends it when ticked.
    confine_to_receptor = request.form.get("confine_to_receptor") == "on"

    partner_names = request.form.getlist("partner_name[]")
    partner_sequences = request.form.getlist("partner_sequence[]")
    partners: list[PartnerInput] = []
    partner_uniprot_raw = request.form.getlist("partner_uniprot[]")
    # zip_longest for the same reason the proteins use it: this field was added
    # after the form shipped, and a cached page posts one fewer array.
    for raw_name, seq, uniprot_raw in itertools.zip_longest(
            partner_names, partner_sequences, partner_uniprot_raw, fillvalue=""):
        if not raw_name.strip() and not seq.strip():
            continue  # a fully-blank trailing row from the client's add-row UI
        name = validate_name(raw_name, used_names, field="partner_name")
        used_names.add(name)
        if not seq.strip():
            raise WizardValidationError(f"Partner '{name}' needs a sequence.", field="partner_sequence")
        partners.append(PartnerInput(name=name, sequence=seq,
                                     uniprot=clean_accession(uniprot_raw)))
    known_partner_names = {p.name for p in partners}

    protein_names_raw = request.form.getlist("protein_name[]")
    protein_sequences = request.form.getlist("protein_sequence[]")
    protein_partners_raw = request.form.getlist("protein_partners[]")  # comma-separated
    protein_apo_raw = request.form.getlist("protein_apo_pdb[]")
    protein_uniprot_raw = request.form.getlist("protein_uniprot[]")
    protein_ligands_raw = request.form.getlist("protein_ligands[]")   # comma-separated
    protein_group_raw = request.form.getlist("protein_group[]")
    protein_family_raw = request.form.getlist("protein_family_type[]")
    protein_apo_path_raw = request.form.getlist("protein_apo_path[]")
    protein_apo_chain_raw = request.form.getlist("protein_apo_chain[]")
    protein_apo_name_raw = request.form.getlist("protein_apo_name[]")
    # A set of row ordinals, not a parallel array: an unchecked box posts nothing,
    # so this field is shorter than the others by however many were left unticked.
    # Anything unparseable is ignored rather than shifting a row's meaning.
    apo_predict_rows = set()
    for raw in request.form.getlist("protein_apo_predict[]"):
        try:
            apo_predict_rows.add(int(raw))
        except (TypeError, ValueError):
            continue
    # A page cached from before this field existed posts none of them at all. That
    # must not silently turn the default off for everyone still on the old page, so
    # absence of the field entirely means "default", not "all unticked".
    apo_field_present = "protein_apo_predict[]" in request.form
    proteins: list[ProteinInput] = []
    # zip_longest, not zip: the apo field was added after this form shipped, and a
    # cached page (or a saved page file from before it existed) posts one fewer array.
    # Plain zip would silently drop the last protein rather than defaulting its apo.
    for row_index, (raw_name, seq, partners_csv, apo_raw, uniprot_raw) in enumerate(
            itertools.zip_longest(
                protein_names_raw, protein_sequences, protein_partners_raw,
                protein_apo_raw, protein_uniprot_raw, fillvalue="")):
        if not raw_name.strip() and not seq.strip():
            continue
        name = validate_name(raw_name, used_names, field="protein_name")
        used_names.add(name)
        if not seq.strip():
            raise WizardValidationError(f"Protein '{name}' needs a sequence.", field="protein_sequence")
        chosen_partners = [p.strip() for p in partners_csv.split(",") if p.strip()]
        for pn in chosen_partners:
            if pn not in known_partner_names:
                raise WizardValidationError(
                    f"Protein '{name}' references partner '{pn}', which isn't defined above.",
                    field="protein_partners",
                )
        def _row(values, default=""):
            raw = values[row_index] if row_index < len(values) else default
            return (raw or "").strip()

        family_type = _row(protein_family_raw).lower()
        if family_type not in ("gpcr", "kinase", "auto"):
            family_type = ""          # "auto" is the parser's own default; say nothing
        proteins.append(ProteinInput(
            name=name, sequence=seq, partner_names=chosen_partners,
            apo_pdb=clean_pdb_id(apo_raw),
            apo_predict=(row_index in apo_predict_rows) if apo_field_present else True,
            uniprot=clean_accession(uniprot_raw),
            ligand_names=[x.strip() for x in _row(protein_ligands_raw).split(",") if x.strip()],
            group=_row(protein_group_raw),
            family_type=family_type,
            apo_path=clean_reference_path(_row(protein_apo_path_raw)),
            apo_chain=_row(protein_apo_chain_raw)[:4],
            apo_name=_row(protein_apo_name_raw)[:5].upper(),
        ))

    protein_names_defined = {p.name for p in proteins}
    constraint_owners = request.form.getlist("constraint_owner[]")
    constraint_kinds = request.form.getlist("constraint_kind[]")
    constraint_r1 = request.form.getlist("constraint_residue1[]")
    constraint_a1 = request.form.getlist("constraint_atom1[]")
    constraint_other = request.form.getlist("constraint_other[]")
    constraint_r2 = request.form.getlist("constraint_residue2[]")
    constraint_a2 = request.form.getlist("constraint_atom2[]")
    constraint_dist = request.form.getlist("constraint_distance[]")
    for owner, kind, r1, a1, other, r2, a2, dist in zip(
        constraint_owners, constraint_kinds, constraint_r1, constraint_a1,
        constraint_other, constraint_r2, constraint_a2, constraint_dist,
    ):
        if not owner.strip():
            continue
        if owner not in protein_names_defined:
            raise WizardValidationError(
                f"Constraint references protein '{owner}', which isn't defined above.",
                field="constraint_owner",
            )
        c = Constraint(
            kind=kind, owner=owner, residue1=r1.strip(), atom1=a1.strip(),
            other=other.strip(), residue2=r2.strip(), atom2=a2.strip(),
            distance=dist.strip() or "6.0",
        )
        for p in proteins:
            if p.name == owner:
                p.constraints.append(c)
                break

    ligand_names_raw = request.form.getlist("ligand_name[]")
    ligand_kinds = request.form.getlist("ligand_kind[]")
    ligand_values = request.form.getlist("ligand_value[]")
    # Defaulted per row rather than zipped: an older saved form has no class field at
    # all, and truncating to the shortest list is exactly the bug the check below
    # exists to catch.
    ligand_classes = request.form.getlist("ligand_class[]")
    ligand_roles = request.form.getlist("ligand_role[]")
    ligands: list[LigandInput] = []
    # zip() over parallel arrays truncates to the shortest, which is how a form bug
    # that posted one ligand_kind for several rows silently dropped every ligand after
    # the first. The form should now always send one of each per row; if it ever does
    # not again, say so instead of quietly building a smaller campaign than was asked
    # for. Trailing blank rows are stripped below, so a mismatch here is structural.
    if not (len(ligand_names_raw) == len(ligand_kinds) == len(ligand_values)):
        raise WizardValidationError(
            f"Ligand fields arrived unevenly ({len(ligand_names_raw)} names, "
            f"{len(ligand_kinds)} types, {len(ligand_values)} values) -- please report this.",
            field="ligand_name",
        )
    for index, (raw_name, kind, value) in enumerate(
            zip(ligand_names_raw, ligand_kinds, ligand_values)):
        ligand_class = (ligand_classes[index] if index < len(ligand_classes)
                        else "experimental")
        if ligand_class not in ("control", "experimental"):
            ligand_class = "experimental"
        if not raw_name.strip() and not value.strip():
            continue
        name = validate_name(raw_name, used_names, field="ligand_name")
        used_names.add(name)
        if not value.strip():
            raise WizardValidationError(f"Ligand '{name}' needs a SMILES or CCD value.", field="ligand_value")
        role = (ligand_roles[index] if index < len(ligand_roles) else "").strip().lower()
        if role not in LIGAND_ROLES:
            role = ""
        ligands.append(LigandInput(name=name, kind=kind, value=value,
                                   ligand_class=ligand_class, role=role))

    return predict_affinity, proteins, partners, ligands, confine_to_receptor


@bp.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "GET":
        return render_template("new_wizard.html", active="new")

    try:
        predict_affinity, proteins, partners, ligands, confine_to_receptor = _parse_form()
        md_text = assemble_boltz_input_md(predict_affinity, proteins, partners, ligands)
    except WizardValidationError as exc:
        return render_template("new_wizard.html", active="new", error=str(exc), form=request.form)

    # Validate by subprocess-invoking `format` (not `format --check`, see the plan --
    # --check conflates "needs cosmetic realignment" with "is structurally valid").
    # On success this also rewrites the file with proper comment alignment, matching
    # example.md's own house style -- a nice bonus, not just a validation side effect.
    scratch = new_scratch_dir(current_app)
    try:
        md_path = scratch / "boltz_input.md"
        md_path.write_text(md_text)
        result = run_boltzmaker("format", md_path)
        if result.returncode != 0:
            return render_template(
                "new_wizard.html", active="new",
                error=extract_error_message(result.stderr), form=request.form,
            )
        final_text = md_path.read_text()
    except BoltzMakerTimeout as exc:
        return render_template("new_wizard.html", active="new", error=str(exc), form=request.form)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if request.form.get("download") == "1":
        return Response(
            final_text, mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=boltz_input.md"},
        )

    return render_template("new_wizard.html", active="new", result_text=final_text)
