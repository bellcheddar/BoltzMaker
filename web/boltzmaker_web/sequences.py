"""Sequences, per-residue numbering and a conservation alignment, from the CIFs.

Everything here is plain Python on purpose. This app's venv is Flask and nothing
else -- BoltzMaker's own dependencies (gemmi, biopython, rdkit) live in a separate
venv that is only ever reached through a subprocess, so a `import gemmi` here
would work on the development machine and fail on the droplet.

Two things come out of a structure:

* The residue sequence of each chain, with the author numbering the viewer and
  PLIP both use, so a residue clicked in the sequence track can be selected in
  Mol* and matched against a PLIP contact.
* An alignment across the campaign's distinct proteins, which is what the
  conservation logo above the track is drawn from.
"""

from __future__ import annotations

from pathlib import Path

#: The 20 standard residues plus the handful of modified ones Boltz emits.
#: Anything unrecognised becomes X rather than being dropped, so the numbering
#: never silently shifts.
THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M", "SEC": "U", "PYL": "O", "HYP": "P", "SEP": "S",
    "TPO": "T", "PTR": "Y", "CSO": "C", "MLY": "K",
}

#: Colouring for the track. Grouped by the property that makes a contact make
#: sense: what is greasy, what carries a charge, what can donate or accept.
RESIDUE_CLASS = {
    "A": "hydrophobic", "V": "hydrophobic", "L": "hydrophobic", "I": "hydrophobic",
    "M": "hydrophobic", "F": "aromatic", "W": "aromatic", "Y": "aromatic",
    "P": "hydrophobic", "G": "small", "C": "small", "S": "polar", "T": "polar",
    "N": "polar", "Q": "polar", "D": "acidic", "E": "acidic",
    "K": "basic", "R": "basic", "H": "basic",
}

_ATOM_PREFIX = ("ATOM ", "HETATM ")


def _atom_site_columns(lines: list[str]) -> tuple[dict[str, int], int]:
    """Column index by name, and the line the atom rows start on.

    The order of _atom_site fields is not fixed by the format -- Boltz writes one
    order, the PDB writes another -- so they are read by name rather than by the
    position they happen to occupy in the files this was written against.
    """
    for i, line in enumerate(lines):
        if line.startswith("_atom_site."):
            columns: dict[str, int] = {}
            j = i
            while j < len(lines) and lines[j].startswith("_atom_site."):
                columns[lines[j].strip()[len("_atom_site."):]] = j - i
                j += 1
            return columns, j
    return {}, len(lines)


def chains_from_cif(path: Path) -> list[dict]:
    """Every chain in the file, in the order it appears, with its residues.

    PLIP reports chains as single letters because it reads a PDB conversion of
    this file, where chains are relabelled A, B, C... in order. The CIF keeps the
    real names (5HT2A, GNAQ, ...), so the letter is reconstructed from the chain's
    position -- that is the mapping that lets a PLIP contact on "chain A residue
    139" be found in a structure whose first chain is called 5HT2A.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    columns, start = _atom_site_columns(lines)
    needed = ("auth_asym_id", "auth_seq_id", "label_comp_id", "label_atom_id")
    if not all(name in columns for name in needed):
        return []
    c_chain = columns["auth_asym_id"]
    c_seq = columns["auth_seq_id"]
    c_comp = columns["label_comp_id"]
    c_atom = columns["label_atom_id"]
    # Coordinates are optional here: the sequence track needs none of them, and
    # the superposition needs all of them.
    coords = [columns.get(name) for name in ("Cartn_x", "Cartn_y", "Cartn_z")]
    has_coords = all(index is not None for index in coords)
    #: In an AlphaFold model the B-factor column holds pLDDT, which is what says
    #: whether a residue's position is worth superposing on.
    c_bfactor = columns.get("B_iso_or_equiv")
    width = len(columns)

    order: list[str] = []
    residues: dict[str, list[tuple[int, str]]] = {}
    seen: dict[str, set] = {}
    for line in lines[start:]:
        if not line.startswith(_ATOM_PREFIX):
            continue
        fields = line.split()
        if len(fields) < width:
            continue
        chain = fields[c_chain]
        if chain not in residues:
            order.append(chain)
            residues[chain] = []
            seen[chain] = set()
        # One row per residue. CA carries the backbone position for a protein; a
        # ligand has no CA, so its first atom stands for it.
        raw_seq = fields[c_seq]
        try:
            number = int(raw_seq)
        except ValueError:
            continue
        if number in seen[chain]:
            continue
        if fields[c_atom] != "CA" and fields[c_comp] in THREE_TO_ONE:
            continue
        seen[chain].add(number)
        point = None
        if has_coords:
            try:
                point = [float(fields[i]) for i in coords]
            except ValueError:
                point = None
        score = None
        if c_bfactor is not None:
            try:
                score = float(fields[c_bfactor])
            except ValueError:
                score = None
        residues[chain].append((number, fields[c_comp], point, score))

    out = []
    for index, chain in enumerate(order):
        rows = residues[chain]
        letters = "".join(THREE_TO_ONE.get(comp, "X") for _, comp, _, _ in rows)
        protein = sum(1 for _, comp, _, _ in rows if comp in THREE_TO_ONE) > max(1, len(rows) // 2)
        out.append({
            "id": chain,
            # A..Z by position; beyond 26 chains PLIP's own labelling breaks down
            # too, so there is nothing sensible to map to.
            "letter": chr(ord("A") + index) if index < 26 else "",
            "kind": "protein" if protein else "ligand",
            "letters": letters,
            "numbers": [number for number, _, _, _ in rows],
            "restypes": [comp for _, comp, _, _ in rows],
            #: One CA position per residue, in file order, for the superposition.
            "ca": [point for _, _, point, _ in rows],
            "score": [score for _, _, _, score in rows],
        })
    return out


# --- alignment ---------------------------------------------------------------

#: A coarse substitution score. BLOSUM62 would be better and is 24x24 of numbers
#: to carry for a display feature; identity plus a bonus for staying inside a
#: property class puts the paralogues of a receptor family in frame, which is all
#: the logo needs.
def _score(a: str, b: str) -> int:
    if a == b:
        return 4
    if RESIDUE_CLASS.get(a) and RESIDUE_CLASS.get(a) == RESIDUE_CLASS.get(b):
        return 1
    return -2


_GAP = -6


def align_pair(ref: str, other: str) -> tuple[str, str]:
    """Needleman-Wunsch, linear gap. Two 480-residue sequences is 230k cells,
    which is a fraction of a second and is done once per campaign and cached."""
    n, m = len(ref), len(other)
    # Row of scores plus a full traceback matrix of 2-bit moves packed as bytes.
    previous = list(range(0, _GAP * (m + 1), _GAP)) if m else [0]
    trace = bytearray((n + 1) * (m + 1))
    for j in range(1, m + 1):
        trace[j] = 2                                  # came from the left
    for i in range(1, n + 1):
        current = [previous[0] + _GAP]
        row_offset = i * (m + 1)
        trace[row_offset] = 1                         # came from above
        a = ref[i - 1]
        for j in range(1, m + 1):
            diagonal = previous[j - 1] + _score(a, other[j - 1])
            up = previous[j] + _GAP
            left = current[j - 1] + _GAP
            best = diagonal
            move = 0
            if up > best:
                best, move = up, 1
            if left > best:
                best, move = left, 2
            current.append(best)
            trace[row_offset + j] = move
        previous = current

    out_ref: list[str] = []
    out_other: list[str] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = trace[i * (m + 1) + j]
        if i > 0 and j > 0 and move == 0:
            out_ref.append(ref[i - 1]); out_other.append(other[j - 1]); i -= 1; j -= 1
        elif i > 0 and move == 1:
            out_ref.append(ref[i - 1]); out_other.append("-"); i -= 1
        else:
            out_ref.append("-"); out_other.append(other[j - 1]); j -= 1
    return "".join(reversed(out_ref)), "".join(reversed(out_other))


def align_to_reference(sequences: list[str]) -> list[str]:
    """Star alignment on the longest sequence.

    Every sequence is aligned to the same reference and the results are merged on
    the reference's columns, so a gap opened by one member does not shift the
    others. Progressive alignment would be better for distant sequences; these are
    paralogues of one receptor family and the reference is never far from any of
    them.
    """
    if len(sequences) < 2:
        return list(sequences)
    reference = max(sequences, key=len)
    # For each sequence: what it contributes at each reference position, and what
    # it inserts before that position.
    at: list[list[str]] = []
    inserts: list[list[str]] = []
    for sequence in sequences:
        aligned_ref, aligned_seq = align_pair(reference, sequence)
        column = ["-"] * len(reference)
        insert = [""] * (len(reference) + 1)
        position = 0
        for r, s in zip(aligned_ref, aligned_seq):
            if r == "-":
                insert[position] += s
            else:
                column[position] = s
                position += 1
        at.append(column)
        inserts.append(insert)

    widths = [max(len(ins[k]) for ins in inserts) for k in range(len(reference) + 1)]
    out = []
    for column, insert in zip(at, inserts):
        parts = []
        for k in range(len(reference)):
            parts.append(insert[k].ljust(widths[k], "-"))
            parts.append(column[k])
        parts.append(insert[len(reference)].ljust(widths[len(reference)], "-"))
        out.append("".join(parts))
    return out


def logo_columns(aligned: list[str]) -> list[list]:
    """Per column: the residues present and how much of the column each holds,
    ordered largest last so a stacked drawing builds from the bottom up.

    The height is the information content in bits, the usual scale for a sequence
    logo: log2(20) for a column that never varies, 0 for one spread evenly across
    all twenty.

    Gaps are handled the way they have to be and not the way that falls out of the
    arithmetic. Counting them as one more symbol in the frequencies makes a column
    that only one sequence of three even has look almost perfectly conserved --
    that one residue is 1/3 of the column, which reads as information rather than
    as absence. So frequencies are taken over the sequences that HAVE a residue
    there, and the column's height is then scaled by how many of them there were.
    A residue seen in one of three is drawn a third as tall as one seen in all
    three, which is the honest answer.
    """
    if not aligned:
        return []
    import math

    columns = []
    total = len(aligned)
    max_bits = math.log2(20)
    for index in range(len(aligned[0])):
        counts: dict[str, int] = {}
        for sequence in aligned:
            counts[sequence[index]] = counts.get(sequence[index], 0) + 1
        residues = {k: v for k, v in counts.items() if k != "-"}
        observed = sum(residues.values())
        if not observed:
            columns.append([])
            continue
        entropy = 0.0
        for count in residues.values():
            p = count / observed
            entropy -= p * math.log2(p)
        bits = max(0.0, max_bits - entropy) * (observed / total)
        stack = sorted(residues.items(), key=lambda kv: kv[1])
        columns.append([[letter, round(count / observed, 4), round(bits, 4)]
                        for letter, count in stack])
    return columns
