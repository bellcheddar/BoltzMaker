"""Structure loading, chain resolution, and secondary-structure extraction for
apo/holo comparison. gemmi.read_structure() handles both .cif and .pdb natively
(confirmed against real PDB and mmCIF files) -- callers never need to know which
format a given file is in.
"""

import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import gemmi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from BoltzMaker import _align_positions  # noqa: E402  -- reused as-is, not reimplemented


class ChainNotFoundError(Exception):
    pass


def one_letter_sequence(polymer: "gemmi.ResidueSpan") -> str:
    """Builds a one-letter sequence string guaranteed index-aligned 1:1 with `polymer`
    (seq[i] always corresponds to polymer[i]). NOT gemmi's own
    polymer.make_one_letter_sequence(): that method collapses an entire missing/
    disordered span (residues absent from the model, seqid jumping e.g. 960->979) into
    a *single* '-' placeholder character, silently breaking index correspondence with
    `polymer` for every position after the gap -- confirmed concretely against real PDB
    1M14 (an 18-residue disordered loop collapsed to one '-', shifting every downstream
    alignment position by up to 17 residues). Real gaps need no placeholder at all here:
    _align_positions's own gap penalty already handles a missing span correctly given a
    plain concatenation of what's actually present.
    """
    chars = []
    for res in polymer:
        info = gemmi.find_tabulated_residue(res.name)
        chars.append(info.one_letter_code.upper() if info else "X")
    return "".join(chars)


class AmbiguousApoChainError(Exception):
    pass


@dataclass
class SSEElement:
    kind: str            # "helix" | "strand"
    start_seqid: int
    end_seqid: int
    label: object = None  # deposited helix/sheet id if present


@dataclass
class LoadedStructure:
    structure: object          # gemmi.Structure
    chain: object                # gemmi.Chain
    polymer: object                # gemmi.ResidueSpan
    sequence: str
    ss_source: str                    # "deposited" | "dssp" | "none"
    helices: list = field(default_factory=list)
    sheets: list = field(default_factory=list)


def load_and_clean(path: Path, keep_ligand_codes: frozenset = frozenset()) -> "gemmi.Structure":
    """Loads a structure and strips heteroatoms other than the ligand of interest.

    Not gemmi's own remove_ligands_and_waters() -- that would also strip the ligand
    BoltzMaker cares about. Waters are always dropped; any other HETATM residue
    (res.het_flag == 'H') is dropped unless its name is in keep_ligand_codes.
    """
    st = gemmi.read_structure(str(path))
    st.setup_entities()
    model = st[0]
    model.remove_waters()
    for chain in model:
        for i in range(len(chain) - 1, -1, -1):
            res = chain[i]
            if res.het_flag == "H" and res.name not in keep_ligand_codes:
                del chain[i]
    st.remove_empty_chains()
    return st


def resolve_protein_chain(structure: "gemmi.Structure", expected_chain_id: object,
                           expected_sequence: str, min_identity: float = 0.3,
                           min_margin: float = 0.15) -> "gemmi.Chain":
    """Resolves the protein chain to use for comparison.

    expected_chain_id given (holo: always fam.id -- Boltz preserves it verbatim in the
    output CIF; apo: fam.apo_chain if the user set one) -> direct lookup.
    expected_chain_id is None (apo, no "Apo chain:" set) -> score every polymer chain
    via _align_positions against expected_sequence and pick the best match.

    min_identity is deliberately a low absolute floor, not a "is this really a match"
    threshold: real apo depositions are commonly fusion constructs (T4L/BRIL inserted
    in place of a loop), so identity against the *whole* chain -- fusion partner
    included -- legitimately lands well below 0.9 even for a fully correct match
    (confirmed empirically against real PDB 2RH1: a correct beta2AR-in-T4L-fusion match
    scores ~0.71, not because the match is wrong but because ~35% of the chain is T4L
    and the native ICL3 residues T4L replaces are genuinely absent from the alignment).
    Ambiguity between multiple real candidate chains is instead caught by min_margin --
    the winner must be clearly better than the runner-up, not just clear some fixed bar.
    """
    model = structure[0]
    if expected_chain_id is not None:
        try:
            return model[expected_chain_id]
        except ValueError:
            available = [c.name for c in model]
            raise ChainNotFoundError(f"chain '{expected_chain_id}' not found "
                                      f"(available: {available})")

    scored = []
    for chain in model:
        polymer = chain.get_polymer()
        if not polymer or polymer.check_polymer_type() not in (
                gemmi.PolymerType.PeptideL, gemmi.PolymerType.PeptideD):
            continue
        chain_seq = one_letter_sequence(polymer)
        if not chain_seq:
            continue
        mapping = _align_positions(expected_sequence, chain_seq)
        # Identity, not coverage: global alignment maps nearly all ref positions to
        # *something* even for an unrelated sequence (gaps are expensive), so raw
        # mapping length is a poor discriminator. Count only positions where the
        # aligned residues actually match.
        matches = sum(1 for r_pos, t_pos in mapping.items()
                       if expected_sequence[r_pos] == chain_seq[t_pos])
        # Normalize by the *shorter* sequence, not always expected_sequence: a kinase-
        # domain-only apo structure (~300 residues) matched against a full-length
        # multi-domain family sequence (~1200 residues, extracellular+TM+kinase) can
        # never exceed ~25% identity against the full length even for a flawless
        # match -- verified concretely against real PDB 1M14 (isolated EGFR kinase
        # domain) vs full-length UniProt EGFR. Using the shorter side as the
        # denominator scores a clean subdomain match near 1.0, as it should.
        shorter = min(len(expected_sequence), len(chain_seq))
        score = matches / shorter if shorter else 0.0
        scored.append((score, chain))

    if not scored:
        raise ChainNotFoundError("no protein polymer chains found in structure")
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_chain = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else -1.0
    if best_score < min_identity or (runner_up_score >= 0 and best_score - runner_up_score < min_margin):
        candidates = [(c.name, round(s, 3)) for s, c in scored[:4]]
        raise AmbiguousApoChainError(
            f"could not confidently auto-detect the apo chain (candidates: {candidates}) "
            f"-- set 'Apo chain:' explicitly in boltz_input.md")
    return best_chain


def dssp_available() -> object:
    return shutil.which("mkdssp") or shutil.which("dssp")


def extract_secondary_structure(structure: "gemmi.Structure", chain: "gemmi.Chain",
                                 dssp_binary: object = None) -> tuple:
    """Returns (list[SSEElement], source) where source is "deposited"/"dssp"/"none".

    Deposited-first: gemmi.read_structure() auto-populates structure.helices/.sheets
    from mmCIF _struct_conf or legacy PDB HELIX/SHEET records on read (verified
    directly against real PDB and mmCIF files -- no extra call needed). Falls back to
    an external DSSP binary via Biopython when the structure has no such annotation
    (true for every Boltz-predicted CIF, which carries zero deposited SS).
    """
    helices = [SSEElement("helix", h.start.res_id.seqid.num, h.end.res_id.seqid.num, h.pdb_helix_class)
               for h in structure.helices if h.start.chain_name == chain.name]
    sheets = []
    for sheet in structure.sheets:
        for strand in sheet.strands:
            if strand.start.chain_name == chain.name:
                sheets.append(SSEElement("strand", strand.start.res_id.seqid.num,
                                          strand.end.res_id.seqid.num, sheet.name))
    if helices or sheets:
        return helices + sheets, "deposited"

    binary = dssp_binary or dssp_available()
    if not binary:
        return [], "none"

    from Bio.PDB import DSSP, PDBParser
    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdb = Path(tmp) / "chain.pdb"
        single_chain_st = gemmi.Structure()
        single_chain_st.add_model(gemmi.Model("1"))
        single_chain_st[0].add_chain(chain)
        single_chain_st.setup_entities()
        single_chain_st.write_pdb(str(tmp_pdb))

        parser = PDBParser(QUIET=True)
        bio_structure = parser.get_structure("x", str(tmp_pdb))
        bio_model = bio_structure[0]
        dssp = DSSP(bio_model, str(tmp_pdb), dssp=binary)

        elements, current = [], None
        for key in dssp.keys():
            _, res_id = key
            resnum = res_id[1]
            ss = dssp[key][2]
            kind = "helix" if ss in ("H", "G", "I") else ("strand" if ss in ("E", "B") else None)
            if kind is None:
                current = None
                continue
            if current and current["kind"] == kind and resnum == current["end"] + 1:
                current["end"] = resnum
            else:
                current = {"kind": kind, "start": resnum, "end": resnum}
                elements.append(current)
        return [SSEElement(e["kind"], e["start"], e["end"]) for e in elements], "dssp"


def load_structure_for_comparison(path: Path, chain_id: object, expected_sequence: str,
                                   keep_ligand_codes: frozenset = frozenset(),
                                   dssp_binary: object = None) -> LoadedStructure:
    st = load_and_clean(path, keep_ligand_codes)
    chain = resolve_protein_chain(st, chain_id, expected_sequence)
    polymer = chain.get_polymer()
    sequence = one_letter_sequence(polymer)
    elements, ss_source = extract_secondary_structure(st, chain, dssp_binary)
    helices = [e for e in elements if e.kind == "helix"]
    sheets = [e for e in elements if e.kind == "strand"]
    return LoadedStructure(structure=st, chain=chain, polymer=polymer, sequence=sequence,
                            ss_source=ss_source, helices=helices, sheets=sheets)
