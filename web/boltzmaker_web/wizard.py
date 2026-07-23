"""Assemble a boltz_input.md from web-form data.

Mirrors cmd_new's exact block/field order and line-list assembly
(BoltzMaker.py's cmd_new, ~line 1138) -- pure string templating, never
touches cmd_new's own input()-based code.

One gap cmd_new's own structure doesn't cover for us: _wiz_name enforces the
5-character/global-uniqueness id rule interactively, rejecting and
re-prompting on the spot. parse_md/`format` do NOT enforce this at parse time
-- a too-long name parses just fine and is only caught later by preflight's
check_chain_id_length. Since this wizard has no "reject and re-prompt" loop
(it's a one-shot form submission), that check has to happen here, explicitly,
before assembly -- otherwise a user could submit a form that produces a
technically-valid-but-doomed boltz_input.md that only fails much later.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class WizardValidationError(ValueError):
    """A field-level problem the form itself should have prevented (defense
    in depth -- the HTML form's own client-side checks are the first line,
    this is the authoritative server-side one). `.field` lets the view map
    the error back to a specific form input."""

    def __init__(self, message: str, field: str = None):
        super().__init__(message)
        self.field = field


def validate_name(name: str, used_names: set[str], field: str = "name") -> str:
    """Mirrors _wiz_name's exact rules (BoltzMaker.py ~line 1007): non-empty,
    at most 5 characters, globally unique across the WHOLE shared namespace
    (proteins, partners, ligands, and any Copies: entries all share one
    namespace -- see docs/tier_b... no, see the boltzmaker-input-wizard
    skill's grammar reference for the full rationale). Returns the
    stripped name on success."""
    name = (name or "").strip()
    if not name:
        raise WizardValidationError("A name is required.", field=field)
    if len(name) > 5:
        raise WizardValidationError(
            f"'{name}' is {len(name)} characters -- Boltz needs chain ids MAX 5 CHARACTERS.",
            field=field,
        )
    if name in used_names:
        raise WizardValidationError(f"'{name}' is already used -- pick a different name.", field=field)
    return name


@dataclass
class Constraint:
    kind: str  # "covalent" | "pocket" | "distance"
    owner: str  # the protein this constraint is attached to (name)
    residue1: str = ""
    atom1: str = ""
    other: str = ""
    residue2: str = ""
    atom2: str = ""
    distance: str = "6.0"

    def to_sentence(self) -> str:
        if self.kind == "covalent":
            return (f"Covalent bond: {self.owner} residue {self.residue1} atom {self.atom1} "
                    f"to {self.other} residue {self.residue2} atom {self.atom2}")
        if self.kind == "pocket":
            return f"Pocket contact: {self.owner} residue {self.residue1}"
        if self.kind == "distance":
            return (f"Distance constraint: {self.owner} residue {self.residue1} to "
                    f"{self.other} residue {self.residue2} within {self.distance} Angstrom")
        raise WizardValidationError(f"Unknown constraint kind: {self.kind!r}")


@dataclass
class ProteinInput:
    name: str
    sequence: str
    partner_names: list[str] = field(default_factory=list)  # names of Partners already validated/collected
    constraints: list[Constraint] = field(default_factory=list)


@dataclass
class PartnerInput:
    name: str
    sequence: str


@dataclass
class LigandInput:
    name: str
    kind: str  # "smiles" | "ccd"
    value: str


def assemble_boltz_input_md(
    predict_affinity: bool,
    proteins: list[ProteinInput],
    partners: list[PartnerInput],
    ligands: list[LigandInput],
) -> str:
    """Builds the exact same line-list structure cmd_new does, then
    "\\n".join(...) + "\\n" -- byte-for-byte the same assembly rule.

    Name validation (5-char/uniqueness) must already have been done by the
    caller (typically views_new.py, threading one shared `used_names` set
    across proteins+partners+ligands as it builds these dataclasses from
    form data) -- this function only assembles, it doesn't re-validate,
    matching the separation of concerns cmd_new itself has (validation
    happens at _wiz_name()/_wiz_prompt() time, assembly happens after).
    """
    if not proteins:
        raise WizardValidationError("At least one protein is required.", field="proteins")
    if not ligands:
        raise WizardValidationError("At least one ligand is required.", field="ligands")

    out = ["Settings:", "Output folder: ./boltz_yamls",
           f"Predict affinity: {'yes' if predict_affinity else 'no'}"]

    protein_blocks: list[list[str]] = []
    statement_lines: list[str] = []

    for p in proteins:
        block = [f"Protein: {p.name}", f"Sequence: {p.sequence.strip()}"]
        if p.partner_names:
            block.append(f"Partners: {', '.join(p.partner_names)}")
        protein_blocks.append(block)
        for c in p.constraints:
            statement_lines.append(c.to_sentence())

    partner_blocks = [[f"Partner: {pt.name}", f"Sequence: {pt.sequence.strip()}"] for pt in partners]

    ligand_blocks = []
    for lg in ligands:
        if lg.kind == "ccd":
            ligand_blocks.append([f"Ligand: {lg.name}", f"CCD: {lg.value.strip()}"])
        else:
            ligand_blocks.append([f"Ligand: {lg.name}", f"SMILES: {lg.value.strip()}"])

    for block in protein_blocks + partner_blocks + ligand_blocks:
        out.append("")
        out.extend(block)
    if statement_lines:
        out.append("")
        out.extend(statement_lines)

    return "\n".join(out) + "\n"
