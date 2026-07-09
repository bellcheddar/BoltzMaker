"""Motif abstraction shared by every MotifAnnotator subclass.

Annotators are deliberately sequence-only (not structure-only): GPCRdb/KLIFS/PDBe
are keyed by sequence or accession, not by an arbitrary uploaded structure. This
keeps them independently unit-testable with a fake client/session -- no structure
fixture required -- and puts the one sequence-to-structure residue mapping in
alignment.py, via BoltzMaker's own _align_positions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Motif:
    name: str                           # "TM6", "DFG", "hinge", a Pfam domain label, ...
    kind: str                            # "helix" | "loop" | "point"
    residues: list = field(default_factory=list)  # 0-indexed positions into the family sequence, N->C order
    is_binding_site_adjacent: bool = False


class MotifAnnotator(ABC):
    family_type = None  # subclasses set "gpcr" / "kinase" / "pfam"

    @abstractmethod
    def applies_to(self, sequence: str) -> bool:
        """Cheap, network-tolerant plausibility probe used by Family type: auto."""

    @abstractmethod
    def annotate(self, sequence: str, pdb_id: object = None, structure_path: object = None,
                 name_hint: object = None) -> list:
        """Returns list[Motif]. Extra kwargs are used only by annotators that need them
        and ignored by the rest: pdb_id by accession-keyed lookups (e.g.
        PfamFallbackAnnotator); structure_path -- a path to the apo structure file --
        by annotators whose backing service is structure- rather than sequence-based
        (e.g. GPCRdb has no sequence-input endpoint, verified against its live API);
        name_hint -- a human-readable identifier such as the family id -- by
        name-keyed lookups (e.g. KLIFS's kinase-name search). Never raises past the
        caller for a lookup/network failure -- returns [] so the caller's resolver can
        fall through to the next annotator.
        """
