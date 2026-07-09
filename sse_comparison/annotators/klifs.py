"""KLIFS-backed kinase pocket motif annotator.

The originally-assumed `opencadd-klifs` package does not exist on PyPI (verified
directly against PyPI's full package index) and its conda-forge distribution
(`opencadd`) currently fails to install at all -- its latest release hard-pins
`biopython<=1.77`, which no longer resolves against current conda-forge channel state.
Rather than depend on a package that cannot be installed, this talks to KLIFS's own
public REST API (https://klifs.net/api/, Swagger-documented) directly via `requests`,
the same approach used for GPCRdb.

KLIFS's fixed 85-position pocket alignment numbering was verified empirically against
real EGFR data (kinase_ID 406): position 17 = the catalytic Lys (K745 in EGFR's native
numbering), 24 = the conserved alphaC-Glu (E762), 45 = the gatekeeper (T790 -- EGFR's
famous drug-resistance residue), 46-48 = the hinge (includes M793), 68-70 = the HRD
catalytic-loop triad, 81-83 = the DFG motif (D855-F856-G857). These are the standard,
published KLIFS positions, not guessed.
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from BoltzMaker import SCRIPT_DIR, _align_positions  # noqa: E402

from ..cache import cache_key, cached_lookup
from ..motifs import Motif, MotifAnnotator

KLIFS_KINASE_ID_ENDPOINT = "https://klifs.net/api/kinase_ID"

# KLIFS's own fixed 85-position pocket numbering -- verified positions, see module docstring.
_MOTIF_POSITIONS = {
    "catalytic_Lys": [17],
    "alphaC_Glu": [24],
    "gatekeeper": [45],
    "hinge": [46, 47, 48],
    "catalytic_loop": [68, 69, 70],
    "DFG": [81, 82, 83],
}
_BINDING_SITE_ADJACENT = {"catalytic_Lys", "alphaC_Glu", "gatekeeper", "hinge", "catalytic_loop", "DFG"}


def _map_pocket_to_sequence(pocket: str, sequence: str) -> dict:
    """pocket is KLIFS's 85-char pocket alignment string (gaps as '-'). Returns
    {klifs_pos (1-indexed): family_seq_pos (0-indexed)}.

    KLIFS's returned pocket sequence is drawn from a specific reference structure and
    is not always residue-for-residue identical to an arbitrary UniProt sequence for
    the same kinase (verified against real EGFR data: most 6-residue windows of the
    pocket string match the real sequence exactly, but a handful differ by a single
    substituted residue -- likely construct/isoform noise, and the returned string can
    also come back with zero gap characters at all, in which case it's one single
    85-char run that will never exact-match end to end). An exact-substring approach is
    too fragile for that; instead this anchors on the first exact-matching sliding
    k-mer (tried at every offset along the ungapped pocket sequence, gap-blind) to
    locate the right region, then runs BLOSUM62 alignment (the existing
    _align_positions helper) between the ungapped pocket sequence and a window of the
    family sequence around that anchor, which tolerates the occasional mismatch.
    """
    pocket_ungapped_for_anchor = pocket.replace("-", "")
    kmer = 6
    anchor_idx = None
    for start in range(0, max(1, len(pocket_ungapped_for_anchor) - kmer + 1)):
        idx = sequence.find(pocket_ungapped_for_anchor[start:start + kmer])
        if idx != -1:
            anchor_idx = idx - start
            break
    if anchor_idx is None:
        return {}

    # A kinase catalytic domain (Gly-rich loop to APE motif) is comfortably under 350
    # residues; the window is generous on both sides to absorb anchor-position noise.
    window_start = max(0, anchor_idx - 30)
    window_end = min(len(sequence), anchor_idx + len(pocket) * 4 + 50)
    window = sequence[window_start:window_end]

    pocket_ungapped = pocket.replace("-", "")
    ungapped_to_klifs = {}
    u = 0
    for idx_p, ch in enumerate(pocket):
        if ch != "-":
            ungapped_to_klifs[u] = idx_p + 1  # 1-indexed KLIFS position
            u += 1

    local_map = _align_positions(pocket_ungapped, window)  # ungapped-pocket-pos -> window-pos
    mapping = {}
    for ungapped_pos, window_pos in local_map.items():
        klifs_pos = ungapped_to_klifs.get(ungapped_pos)
        if klifs_pos is not None:
            mapping[klifs_pos] = window_start + window_pos
    return mapping


class KLIFSClient:
    def __init__(self, cache_dir: object = None, timeout: float = 30.0):
        self.cache_dir = cache_dir or (SCRIPT_DIR / ".sse_cache" / "klifs")
        self.timeout = timeout

    def lookup_pocket(self, kinase_name: str, species: str = "HUMAN", refresh: bool = False) -> object:
        """Returns the 85-residue KLIFS pocket alignment string for a kinase name (or
        UniProt ID -- KLIFS accepts both), or None if not found/on failure.
        """
        key = cache_key(f"{kinase_name}|{species}")

        def fetch():
            resp = requests.get(KLIFS_KINASE_ID_ENDPOINT,
                                 params={"kinase_name": kinase_name, "species": species},
                                 timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                raise ValueError(f"no KLIFS kinase found for '{kinase_name}'")
            return {"pocket": data[0]["pocket"], "kinase_ID": data[0]["kinase_ID"]}

        return cached_lookup(self.cache_dir, key, fetch, refresh=refresh)


class KLIFSAnnotator(MotifAnnotator):
    family_type = "kinase"

    def __init__(self, client: object = None):
        self.client = client or KLIFSClient()

    def applies_to(self, sequence: str) -> bool:
        # Cheap, network-free plausibility pre-filter for Family type: auto -- the HRD
        # catalytic-loop and DFG motifs are near-universal across protein kinases.
        return "HRD" in sequence and "DFG" in sequence

    def annotate(self, sequence: str, pdb_id: object = None, structure_path: object = None,
                 name_hint: object = None) -> list:
        if not name_hint:
            return []
        try:
            result = self.client.lookup_pocket(name_hint)
        except Exception as exc:
            print(f"BoltzMaker: WARNING: KLIFS annotation failed ({exc})")
            return []
        if not result:
            return []

        klifs_to_fam = _map_pocket_to_sequence(result["pocket"], sequence)
        motifs = []
        claimed = set()
        for name, klifs_positions in _MOTIF_POSITIONS.items():
            claimed.update(klifs_positions)
            fam_positions = sorted({klifs_to_fam[p] for p in klifs_positions if p in klifs_to_fam})
            if not fam_positions:
                continue
            kind = "point" if len(klifs_positions) == 1 else "loop"
            motifs.append(Motif(name=name, kind=kind, residues=fam_positions,
                                 is_binding_site_adjacent=name in _BINDING_SITE_ADJACENT))

        # The remaining ~60 of KLIFS's 85 pocket positions -- the two-lobe scaffold
        # outside the mobile/functional anchors above -- serve as the superposition
        # reference region for kinases (alignment.stable_reference_positions). Without
        # this, every KLIFS motif this annotator returns is binding-site-adjacent and
        # there would be nothing left to superpose apo/holo on at all.
        scaffold_positions = sorted({fam_pos for klifs_pos, fam_pos in klifs_to_fam.items()
                                      if klifs_pos not in claimed})
        if scaffold_positions:
            motifs.append(Motif(name="pocket_scaffold", kind="loop", residues=scaffold_positions,
                                 is_binding_site_adjacent=False))
        return motifs
