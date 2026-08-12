from __future__ import annotations

import shutil

from flask import Blueprint, Response, current_app, render_template, request

from .app import new_scratch_dir
from .runner import BoltzMakerTimeout, extract_error_message, run_boltzmaker
from .wizard import (
    Constraint,
    LigandInput,
    PartnerInput,
    ProteinInput,
    WizardValidationError,
    assemble_boltz_input_md,
    validate_name,
)

bp = Blueprint("new", __name__)


def _parse_form() -> tuple[bool, list[ProteinInput], list[PartnerInput], list[LigandInput]]:
    """Parses the flat parallel-array form fields new_wizard.html/wizard.js
    produce back into the dataclasses wizard.py's assembler expects. Uses one
    shared `used_names` set across proteins/partners/ligands, exactly
    matching cmd_new's own single shared-namespace enforcement."""
    used_names: set[str] = set()

    predict_affinity = request.form.get("predict_affinity") == "on"

    partner_names = request.form.getlist("partner_name[]")
    partner_sequences = request.form.getlist("partner_sequence[]")
    partners: list[PartnerInput] = []
    for raw_name, seq in zip(partner_names, partner_sequences):
        if not raw_name.strip() and not seq.strip():
            continue  # a fully-blank trailing row from the client's add-row UI
        name = validate_name(raw_name, used_names, field="partner_name")
        used_names.add(name)
        if not seq.strip():
            raise WizardValidationError(f"Partner '{name}' needs a sequence.", field="partner_sequence")
        partners.append(PartnerInput(name=name, sequence=seq))
    known_partner_names = {p.name for p in partners}

    protein_names_raw = request.form.getlist("protein_name[]")
    protein_sequences = request.form.getlist("protein_sequence[]")
    protein_partners_raw = request.form.getlist("protein_partners[]")  # comma-separated
    proteins: list[ProteinInput] = []
    for raw_name, seq, partners_csv in zip(protein_names_raw, protein_sequences, protein_partners_raw):
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
        proteins.append(ProteinInput(name=name, sequence=seq, partner_names=chosen_partners))

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
    ligands: list[LigandInput] = []
    for raw_name, kind, value in zip(ligand_names_raw, ligand_kinds, ligand_values):
        if not raw_name.strip() and not value.strip():
            continue
        name = validate_name(raw_name, used_names, field="ligand_name")
        used_names.add(name)
        if not value.strip():
            raise WizardValidationError(f"Ligand '{name}' needs a SMILES or CCD value.", field="ligand_value")
        ligands.append(LigandInput(name=name, kind=kind, value=value))

    return predict_affinity, proteins, partners, ligands


@bp.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "GET":
        return render_template("new_wizard.html", active="new")

    try:
        predict_affinity, proteins, partners, ligands = _parse_form()
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
