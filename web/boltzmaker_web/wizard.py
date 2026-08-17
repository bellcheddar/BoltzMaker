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


def apo_companion_name(base: str, used_names: set) -> str:
    """A unique, <=5-character id for a protein's ligand-free companion.

    Boltz chain ids are capped at 5 characters and share one namespace with every
    protein, partner and ligand in the campaign, so this cannot simply be
    f"{base}_apo". This repo's own 5HT2 example uses hand-picked ids of exactly
    this shape (5HT2A -> H2AAP); this reproduces that convention automatically and
    keeps trying until it finds a free one rather than silently colliding.
    """
    candidates = [(base[:3] + "AP")[:5], (base[:2] + "AP")[:5], "APO"]
    candidates += [f"{base[:2]}AP{i}"[:5] for i in range(1, 10)]
    candidates += [f"APO{i}"[:5] for i in range(1, 100)]
    for candidate in candidates:
        candidate = candidate.upper()
        if candidate and candidate not in used_names:
            return candidate
    raise WizardValidationError(
        f"could not find a free 5-character name for {base}'s apo companion.",
        field="protein_name",
    )


@dataclass
class ProteinInput:
    name: str
    sequence: str
    partner_names: list[str] = field(default_factory=list)  # names of Partners already validated/collected
    constraints: list[Constraint] = field(default_factory=list)
    # A four-character PDB id for a real, experimental apo structure. When set, that
    # structure is the comparison reference and no ligand-free prediction is made for
    # this protein: measured beats predicted.
    apo_pdb: str = ""
    # Predict a ligand-free companion of this protein. On by default, and
    # independent of apo_pdb: an experimental structure is the better thing to
    # measure against, but a predicted apo of the user's own construct is worth
    # having alongside it, and is a target in its own right.
    apo_predict: bool = True
    # Optional, and only ever used by the website: it names the entry whose
    # AlphaFold model the explorer overlays on this protein's prediction. Nothing
    # in the pipeline reads it, so it travels in config.json rather than in
    # boltz_input.md, and BoltzMaker.py never has to learn a key it does not use.
    uniprot: str = ""
    # The holo structure this protein contributes to the campaign's set of sites.
    pocket_pdb: str = ""
    pocket_ligand: str = ""
    # {site code: [residue positions]} in THIS protein's numbering -- one entry per
    # site named anywhere in the campaign, including sites taken from another
    # protein's structure and projected here through a sequence alignment.
    pockets: dict = field(default_factory=dict)


@dataclass
class PartnerInput:
    name: str
    sequence: str
    # As for a protein: website metadata, recorded so the explorer can name the
    # entry a chain came from without guessing it back out of the sequence.
    uniprot: str = ""


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
    compare_sse: bool = True,
    apo_reference_paths: dict = None,
    pocket_distance: float = 0.0,
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
    # Only written when a pocket is actually in use, so a campaign without one
    # produces the same file it always did.
    if pocket_distance and any(p.pockets for p in proteins):
        out.append(f"Pocket distance: {pocket_distance:g}")

    protein_blocks: list[list[str]] = []
    statement_lines: list[str] = []

    # compare-sse compares a holo prediction against an apo structure, and only runs
    # for families that name one. Nothing here used to emit `Apo structure:` at all,
    # so a campaign built on this site could never produce a secondary-structure
    # comparison, and the "skip compare-sse" option had nothing to skip.
    #
    # The default is now a ligand-free companion prediction per protein, which is the
    # idiom this repo's own 5HT2 example uses: an extra Protein block with
    # `Ligands: none`, whose predicted CIF the holo families point at. A real
    # experimental structure is better when one exists, so naming a PDB id replaces
    # the companion rather than adding to it.
    #
    # It is not free: each companion is another target to predict. One protein with
    # one ligand doubles; one protein with six ligands adds a seventh. The form says
    # so, and unticking compare-sse turns it off.
    apo_reference_paths = apo_reference_paths or {}
    used_names = ({p.name for p in proteins} | {pt.name for pt in partners}
                  | {lg.name for lg in ligands})
    apo_companions: list[ProteinInput] = []
    apo_reference: dict = {}

    if compare_sse:
        for p in proteins:
            experimental = apo_reference_paths.get(p.name) if p.apo_pdb else None

            companion_path = None
            if p.apo_predict:
                companion = apo_companion_name(p.name, used_names)
                used_names.add(companion)
                apo_companions.append(ProteinInput(name=companion, sequence=p.sequence,
                                                   partner_names=list(p.partner_names)))
                companion_path = f"boltz_cif/{companion}_model_0.cif"

            # A family can name exactly one apo structure, so when both exist the
            # experimental one wins: it is a measurement, and the prediction is a
            # prediction. The companion is still computed and still appears in the
            # results as its own target -- a predicted apo of the user's own
            # construct, which the deposited entry generally is not.
            reference = experimental or companion_path
            if reference:
                apo_reference[p.name] = reference

    for p in proteins:
        block = [f"Protein: {p.name}", f"Sequence: {p.sequence.strip()}"]
        if p.partner_names:
            block.append(f"Partners: {', '.join(p.partner_names)}")
        if apo_reference.get(p.name):
            block.append(f"Apo structure: {apo_reference[p.name]}")
        for code, positions in sorted(p.pockets.items()):
            for position in positions:
                block.append(f"Pocket contact: {p.name} residue {position} as {code}")

        protein_blocks.append(block)
        for c in p.constraints:
            statement_lines.append(c.to_sentence())

    for companion in apo_companions:
        block = [f"Protein: {companion.name}", f"Sequence: {companion.sequence.strip()}"]
        if companion.partner_names:
            block.append(f"Partners: {', '.join(companion.partner_names)}")
        block.append("Ligands: none")      # the whole point: same system, no ligand
        protein_blocks.append(block)

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
