"""Reference-region selection and apo/holo structural superposition.

Reference-region residues are excluded from every binding-site-adjacent motif so
ligand-induced local shifts don't skew the global fit -- then apo is superposed onto
holo using only those residues, via gemmi.superpose_positions with explicit,
pre-paired CA positions (not gemmi.calculate_superposition, which pairs residues
positionally within a span -- unsafe here since apo/holo numbering isn't assumed to
agree, see structures.py).
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import gemmi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from BoltzMaker import _align_positions  # noqa: E402


class InsufficientReferenceRegionError(Exception):
    pass


@dataclass
class ComparisonFrame:
    apo: object              # structures.LoadedStructure
    holo: object               # structures.LoadedStructure
    fam_sequence: str
    fam_to_apo: dict              # family 0-idx pos -> apo polymer 0-idx pos (identity-filtered)
    fam_to_holo: dict               # family 0-idx pos -> holo polymer 0-idx pos (identity-filtered)
    sup: object                       # gemmi.SupResult, moves apo CA positions into the holo frame
    reference_positions: list


def stable_reference_positions(motifs: list, family_type: str) -> list:
    """Family-sequence 0-indexed positions to use for superposition.

    GPCR/kinase: every residue from every motif *not* flagged binding-site-adjacent,
    pooled together (e.g. GPCR: TM1-5/H8/loops other than ECL2; kinase: the KLIFS
    pocket scaffold outside hinge/gatekeeper/DFG/alphaC).
    pfam fallback: the single *largest* domain by residue count, not the pooled union
    -- PfamFallbackAnnotator marks every domain non-adjacent (it has no binding-site
    concept), so pooling would include small, possibly-spurious domain fragments (see
    the alignment-noise caveat in annotators/pfam.py) alongside the real scaffold.
    """
    non_adjacent = [m for m in motifs if not m.is_binding_site_adjacent]
    if not non_adjacent:
        return []
    if family_type == "pfam":
        largest = max(non_adjacent, key=lambda m: len(m.residues))
        return sorted(set(largest.residues))
    positions = set()
    for m in non_adjacent:
        positions.update(m.residues)
    return sorted(positions)


def _identity_filtered_mapping(fam_sequence: str, other_sequence: str) -> dict:
    # See the identical, empirically-verified issue in annotators/gpcrdb.py and
    # annotators/pfam.py: global alignment must consume both sequences end to end, so
    # an unrelated insert can smear across mediocre matches instead of being cleanly
    # gapped out. Filtering to only positions with matching residue identity fixes it.
    raw = _align_positions(fam_sequence, other_sequence)
    return {f: o for f, o in raw.items() if fam_sequence[f] == other_sequence[o]}


def build_comparison_frame(apo: object, holo: object, fam_sequence: str, motifs: list,
                            family_type: str, min_reference_positions: int = 20) -> ComparisonFrame:
    fam_to_apo = _identity_filtered_mapping(fam_sequence, apo.sequence)
    fam_to_holo = _identity_filtered_mapping(fam_sequence, holo.sequence)

    ref_positions = stable_reference_positions(motifs, family_type)
    usable = [p for p in ref_positions if p in fam_to_apo and p in fam_to_holo]
    if len(usable) < min_reference_positions:
        raise InsufficientReferenceRegionError(
            f"only {len(usable)} usable reference-region residues (need >= "
            f"{min_reference_positions}) -- motif annotation may have failed, or the "
            f"apo/holo structures don't correspond well to the family sequence")

    apo_pos = [apo.polymer[fam_to_apo[p]].sole_atom("CA").pos for p in usable]
    holo_pos = [holo.polymer[fam_to_holo[p]].sole_atom("CA").pos for p in usable]
    # gemmi.superpose_positions(pos1, pos2).transform maps pos2 -> pos1, not pos1 -> pos2
    # (verified empirically -- undocumented in the binding's docstring). holo_pos is
    # passed as pos1 so the returned transform maps apo positions into the holo frame,
    # matching this module's documented convention.
    sup = gemmi.superpose_positions(holo_pos, apo_pos)

    return ComparisonFrame(apo=apo, holo=holo, fam_sequence=fam_sequence, fam_to_apo=fam_to_apo,
                            fam_to_holo=fam_to_holo, sup=sup, reference_positions=usable)
