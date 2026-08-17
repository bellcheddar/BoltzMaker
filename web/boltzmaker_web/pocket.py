"""Derive a pocket definition from the ligand in a reference structure.

Boltz co-folding places a ligand wherever the model likes. Measured on a real
GLP1R/GIPR campaign: only 10 of 13 GLP1R ligands and 6 of 14 GIPR ligands landed
in the same site, and six ligands docked onto the G-protein subunits instead of
the receptor at all -- which makes their predicted affinities meaningless as
receptor pharmacology. A pocket constraint fixes that by naming residues the
ligand must stay near.

**Pure Python on purpose.** The droplet installs flask, gunicorn, werkzeug and
python-dotenv and nothing else -- no gemmi, no numpy, no biopython. A local venv
happens to have all three, which makes this an easy thing to get wrong and only
discover on deploy. Everything here parses mmCIF/PDB text and does its own
arithmetic, matching sequences.py and alphafold.py.

**Additives are excluded, not ranked down.** A reference is chosen for its
receptor, and what crystallises alongside it is usually cholesterol, detergent,
sugar or buffer. 7dty (a GIPR reference) contains six cholesterols and no
orthosteric ligand at all, so "largest non-polymer residue" would have defined
the pocket in the lipid-facing groove -- producing exactly the misplacement this
module exists to prevent. Anything on the exclusion list is never offered; a
reference with nothing left simply has no pocket to offer, and says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from .sequences import THREE_TO_ONE, _atom_site_columns, align_pair

# Waters and ions, common buffers and cryoprotectants, sugars from glycosylation,
# and the lipids/detergents that GPCR structures are full of. These are things a
# structure contains *incidentally*; none of them defines a binding site anyone
# wants to dock into.
EXCLUDED_CODES = {
    # solvent and ions
    "HOH", "DOD", "WAT", "NA", "K", "MG", "CA", "ZN", "MN", "FE", "FE2", "CU",
    "CU1", "NI", "CO", "CD", "HG", "CL", "BR", "IOD", "F", "SO4", "PO4", "NO3",
    "ACT", "AZI", "CYN", "SCN", "OH", "O", "OXY", "PER",
    # buffers, cryoprotectants, precipitants
    "GOL", "EDO", "PEG", "PG4", "PGE", "1PE", "2PE", "P6G", "MPD", "DMS", "TRS",
    "EPE", "MES", "BTB", "CIT", "FLC", "TAR", "MLI", "ACY", "FMT", "IPA", "MOH",
    "BME", "DTT", "TCE", "IMD", "BEN", "URE", "SIN",
    # sugars (glycosylation)
    "NAG", "NDG", "BMA", "MAN", "BGC", "GLC", "GAL", "FUC", "XYL", "SIA", "NGA",
    # lipids, sterols and detergents
    "CLR", "CHL", "CHS", "PLM", "OLA", "OLC", "OLB", "STE", "MYR", "PCW", "POV",
    "PEE", "PGT", "PSC", "LMT", "LMN", "DDQ", "UND", "HEX", "D10", "D12", "DAO",
    "MC3", "Y01", "9Z9", "HTG", "BOG", "C8E", "LDA", "SDS",
    # nucleotides and cofactors that are almost never the ligand of interest here
    "ATP", "ADP", "AMP", "GTP", "GDP", "GNP", "GSP", "ANP", "NAD", "NAP", "FAD",
    "FMN", "SAM", "SAH", "COA", "HEM", "PLP",
}

# Below this, a residue is a fragment, an ion cluster or a modified sidechain
# rather than something worth defining a pocket around.
MIN_LIGAND_ATOMS = 8


@dataclass
class Candidate:
    code: str
    chain: str
    seq_id: str
    atoms: int

    @property
    def key(self) -> str:
        """Stable identifier for the form value: code|chain|seq_id."""
        return f"{self.code}|{self.chain}|{self.seq_id}"

    @property
    def label(self) -> str:
        return f"{self.code} (chain {self.chain}, {self.atoms} atoms)"

    def to_json(self) -> dict:
        return {"key": self.key, "code": self.code, "chain": self.chain,
                "seq_id": self.seq_id, "atoms": self.atoms, "label": self.label}


def _atom_rows(text: str):
    """Yield (group, comp_id, chain, seq_id, atom_id, x, y, z) for every atom.

    Handles the mmCIF loop only. A PDB-format reference is converted by the caller
    before it reaches here; keeping one parser avoids two subtly different ideas of
    what a chain is.
    """
    lines = text.splitlines()
    columns, start = _atom_site_columns(lines)
    needed = ("auth_asym_id", "auth_seq_id", "label_comp_id", "label_atom_id",
              "Cartn_x", "Cartn_y", "Cartn_z")
    if not all(name in columns for name in needed):
        return
    group = columns.get("group_PDB")
    ci = (columns["auth_asym_id"], columns["auth_seq_id"], columns["label_comp_id"],
          columns["label_atom_id"], columns["Cartn_x"], columns["Cartn_y"], columns["Cartn_z"])
    width = max(max(ci), group if group is not None else 0)
    for line in lines[start:]:
        if line.startswith("#") or line.startswith("loop_"):
            break
        parts = line.split()
        if len(parts) <= width:
            continue
        try:
            x, y, z = float(parts[ci[4]]), float(parts[ci[5]]), float(parts[ci[6]])
        except ValueError:
            continue
        kind = parts[group] if group is not None else "ATOM"
        yield kind, parts[ci[2]], parts[ci[0]], parts[ci[1]], parts[ci[3]], x, y, z


def ligand_candidates(text: str) -> list[Candidate]:
    """Every plausible pocket-defining ligand, largest first.

    Excluded codes are dropped entirely rather than sorted to the bottom, so a
    reference whose only heteroatoms are cholesterol offers nothing and the caller
    can say so, instead of quietly proposing a lipid.
    """
    counts: dict[tuple, int] = {}
    for kind, comp, chain, seq_id, _atom, _x, _y, _z in _atom_rows(text):
        if kind != "HETATM":
            continue
        if comp.upper() in EXCLUDED_CODES or comp.upper() in THREE_TO_ONE:
            continue
        counts[(comp, chain, seq_id)] = counts.get((comp, chain, seq_id), 0) + 1
    found = [Candidate(code=c, chain=ch, seq_id=s, atoms=n)
             for (c, ch, s), n in counts.items() if n >= MIN_LIGAND_ATOMS]
    found.sort(key=lambda c: (-c.atoms, c.code, c.chain))
    return found


def _chain_sequence(text: str, chain: str) -> tuple[str, list[str]]:
    """The observed one-letter sequence of a polymer chain, and its residue numbers."""
    seen: dict[str, str] = {}
    order: list[str] = []
    for kind, comp, ch, seq_id, atom, _x, _y, _z in _atom_rows(text):
        if ch != chain or kind != "ATOM" or atom != "CA":
            continue
        if seq_id not in seen:
            seen[seq_id] = THREE_TO_ONE.get(comp.upper(), "X")
            order.append(seq_id)
    return "".join(seen[s] for s in order), order


def contact_residues(text: str, candidate: Candidate, distance: float,
                     chain: str) -> list[str]:
    """Residue numbers of `chain` with any atom within `distance` of the ligand."""
    ligand = [(x, y, z) for kind, comp, ch, seq_id, _a, x, y, z in _atom_rows(text)
              if ch == candidate.chain and seq_id == candidate.seq_id and comp == candidate.code]
    if not ligand:
        return []
    limit = distance * distance
    hits: list[str] = []
    seen: set[str] = set()
    for kind, _comp, ch, seq_id, _atom, x, y, z in _atom_rows(text):
        if ch != chain or kind != "ATOM" or seq_id in seen:
            continue
        for lx, ly, lz in ligand:
            if (x - lx) ** 2 + (y - ly) ** 2 + (z - lz) ** 2 <= limit:
                seen.add(seq_id)
                hits.append(seq_id)
                break
    return hits


def map_to_sequence(text: str, chain: str, contacts: list[str],
                    target_sequence: str) -> list[int]:
    """Translate reference residue numbers into positions in the user's sequence.

    A reference structure is a construct: it has tags, mutations, gaps at
    disordered loops, and its own numbering. The user's sequence is whatever they
    pasted. Aligning the chain's *observed* sequence to theirs and carrying the
    contacts across is what makes a pocket derived from 6ln2 mean anything for a
    campaign built on P43220 -- and returning positions in their numbering is what
    BoltzMaker's `Pocket contact:` statements expect.
    """
    observed, numbers = _chain_sequence(text, chain)
    if not observed or not target_sequence:
        return []
    ref_aln, tgt_aln = align_pair(observed, target_sequence)
    ref_i = tgt_i = 0
    number_to_position: dict[str, int] = {}
    for a, b in zip(ref_aln, tgt_aln):
        if a != "-" and b != "-":
            if ref_i < len(numbers):
                number_to_position[numbers[ref_i]] = tgt_i + 1
        if a != "-":
            ref_i += 1
        if b != "-":
            tgt_i += 1
    positions = sorted({number_to_position[n] for n in contacts if n in number_to_position})
    return positions


def best_chain_for_sequence(text: str, target_sequence: str) -> str:
    """Which chain of the reference corresponds to the user's protein.

    Chosen by alignment identity rather than by name or order: a reference names
    its chains whatever the depositor chose, and the receptor is not reliably
    chain A.
    """
    best, best_score = "", -1.0
    chains = {ch for kind, _c, ch, _s, _a, _x, _y, _z in _atom_rows(text) if kind == "ATOM"}
    for chain in sorted(chains):
        observed, _numbers = _chain_sequence(text, chain)
        if len(observed) < 30:
            continue
        ref_aln, tgt_aln = align_pair(observed, target_sequence)
        same = sum(1 for a, b in zip(ref_aln, tgt_aln) if a == b and a != "-")
        score = same / max(len(target_sequence), 1)
        if score > best_score:
            best, best_score = chain, score
    return best if best_score >= 0.3 else ""
