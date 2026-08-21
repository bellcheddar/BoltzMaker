"""GPCRdb-backed motif annotator.

GPCRdb has no sequence-input generic-numbering endpoint -- verified directly against
the live API (https://gpcrdb.org/services/): the only generic-numbering service is
POST /services/structure/assign_generic_numbers, which takes an uploaded PDB file and
returns a PDB file back. GPCRdb encodes each assigned residue's Ballesteros-Weinstein /
GPCRdb generic number directly into that returned PDB's B-factor column as
"<segment>.<position>" (e.g. 1.28 = TM1 position 28, 12.50 = ICL1 position 50) --
confirmed empirically by uploading the real PDB 2RH1 (beta2AR/T4L fusion) and observing
consecutive TM1 residues increment by exactly 0.01 per residue, with unassigned
residues (including the entire T4L insert) retaining large, real-looking crystallographic
B-factors. Residues without an assignment are never confused with real low B-factors
because GPCRdb's segment codes are a small closed set (1-8, or two-digit loop codes)
that essentially never collides with genuine crystallographic values.

Because this endpoint is structure-based, annotate() needs the apo structure's own
file, not just a bare sequence -- MotifAnnotator.annotate()'s optional structure_path
parameter exists specifically for this.
"""

import re
import sys
import tempfile
from pathlib import Path

import gemmi
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from BoltzMaker import SCRIPT_DIR, _align_positions  # noqa: E402

from ..cache import cache_key, cached_lookup
from ..motifs import Motif, MotifAnnotator

GPCRDB_ENDPOINT = "https://gpcrdb.org/services/structure/assign_generic_numbers"

_HELIX_SEGMENTS = {"1": "TM1", "2": "TM2", "3": "TM3", "4": "TM4", "5": "TM5", "6": "TM6", "7": "TM7", "8": "H8"}
_LOOP_SEGMENTS = {"12": "ICL1", "23": "ECL1", "34": "ICL2", "45": "ECL2", "56": "ICL3", "67": "ECL3", "78": "H8loop"}
_ALL_SEGMENTS = {**_HELIX_SEGMENTS, **_LOOP_SEGMENTS}
_BINDING_SITE_ADJACENT = {"TM6", "TM7", "ECL2"}


def _decode_generic_number(bfactor: float) -> tuple:
    text = f"{bfactor:.2f}"
    if text.startswith("-"):
        return None, None
    int_part, _, frac_part = text.partition(".")
    segment = _ALL_SEGMENTS.get(int_part)
    if segment is None:
        return None, None
    return segment, f"{int_part}.{frac_part}"


def _parse_generic_number_pdb(pdb_text: str) -> dict:
    """Returns {resnum: [segment_label, generic_number_str]} from a GPCRdb response."""
    result = {}
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        try:
            resnum = int(line[22:26])
            bfactor = float(line[60:66])
        except ValueError:
            continue
        segment, generic = _decode_generic_number(bfactor)
        if segment is not None:
            result[str(resnum)] = [segment, generic]
    return result


class GPCRdbClient:
    def __init__(self, cache_dir: object = None, timeout: float = 60.0):
        self.cache_dir = cache_dir or (SCRIPT_DIR / ".sse_cache" / "gpcrdb")
        self.timeout = timeout

    def assign_generic_numbers(self, pdb_path: Path, refresh: bool = False) -> object:
        """Returns {resnum: (segment_label, generic_number_str)}, or None on failure."""
        pdb_bytes = Path(pdb_path).read_bytes()
        key = cache_key(pdb_bytes.hex())

        def fetch():
            resp = requests.post(GPCRDB_ENDPOINT, files={"pdb_file": ("structure.pdb", pdb_bytes)},
                                  timeout=self.timeout)
            resp.raise_for_status()
            parsed = _parse_generic_number_pdb(resp.text)
            if not parsed:
                raise ValueError("no generic numbers assigned -- not a recognizable GPCR structure")
            return parsed

        result = cached_lookup(self.cache_dir, key, fetch, refresh=refresh)
        return {int(k): tuple(v) for k, v in result.items()} if result else None


#: Kyte-Doolittle hydropathy. Used for a crude span count, not for a real topology
#: prediction -- the question here is only "is this a polytopic membrane protein",
#: and the answer is checked properly by GPCRdb straight afterwards.
_KD = {"A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5,
       "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
       "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2}

#: A 19-residue window is about the length of a membrane-spanning helix.
_TM_WINDOW = 19
#: Mean hydropathy a window must reach to count. Tuned on the sequences these
#: campaigns actually contain, where 1.4 separates cleanly with a wide margin:
#: GLP1R 9 spans, GIPR 7, ADRB2 6, against 0 for GNAS, GNB1, GNG2 and T4 lysozyme.
#: At 1.6 -- the first value tried -- GIPR scored 4 and would still have been
#: excluded, which is the whole failure this replaces.
_TM_HYDROPATHY = 1.4
#: Seven for a GPCR, with two spare: a predicted receptor can bury one helix badly
#: enough to miss the threshold, and this filter should not be the thing that
#: decides. Below five it is not a 7TM protein at all.
_MIN_TM_SPANS = 5


def _count_membrane_spans(sequence: str) -> int:
    """Non-overlapping hydrophobic windows long enough to cross a membrane."""
    scores = [_KD.get(residue, 0.0) for residue in sequence.upper()]
    if len(scores) < _TM_WINDOW:
        return 0
    spans, index = 0, 0
    total = sum(scores[:_TM_WINDOW])
    while index + _TM_WINDOW <= len(scores):
        if total / _TM_WINDOW >= _TM_HYDROPATHY:
            spans += 1
            # Skip past this helix so one long hydrophobic stretch counts once.
            index += _TM_WINDOW
            if index + _TM_WINDOW > len(scores):
                break
            total = sum(scores[index:index + _TM_WINDOW])
            continue
        total += scores[index + _TM_WINDOW] - scores[index] if index + _TM_WINDOW < len(scores) else 0
        index += 1
    return spans


class GPCRdbAnnotator(MotifAnnotator):
    family_type = "gpcr"

    def __init__(self, client: object = None):
        self.client = client or GPCRdbClient()

    def applies_to(self, sequence: str) -> bool:
        """Cheap, network-free plausibility pre-filter for `Family type: auto`.

        Counts membrane-spanning stretches rather than looking for DRY and NPxxY.
        Those two are **class A** signatures, and gating on them quietly excluded
        every other class GPCRdb covers: GLP1R and GIPR are class B, have no NPxxY,
        and so never reached the real check at all. The campaign fell through to the
        Pfam fallback, which returns the single `7tm_2` domain -- one motif for the
        whole seven-helix bundle, no loops, and nothing anywhere saying the receptor
        had been annotated as a featureless blob.

        The authoritative test is `annotate()`, which asks GPCRdb to assign generic
        numbers to the actual structure and yields TM1-TM7, ICL1-3, ECL1-3 and H8.
        This only has to be cheap and to reject soluble proteins, so a false positive
        costs one request that returns nothing.
        """
        # Class B and C carry large extracellular domains (GLP1R 463, mGluR ~900), so
        # the old 600-residue ceiling excluded them on length alone as well.
        if not (250 <= len(sequence) <= 1200):
            return False
        return _count_membrane_spans(sequence) >= _MIN_TM_SPANS

    def annotate(self, sequence: str, pdb_id: object = None, structure_path: object = None,
                 name_hint: object = None, chain_id: object = None) -> list:
        if structure_path is None:
            return []
        try:
            from .. import structures as _structures
            st = _structures.load_and_clean(structure_path)
            chain = _structures.resolve_protein_chain(st, chain_id, sequence)
            polymer = chain.get_polymer()
            apo_seq = _structures.one_letter_sequence(polymer)
            apo_resnum_to_pos = {res.seqid.num: i for i, res in enumerate(polymer)}
            # ref=family sequence, target=apo sequence -- maps family position -> apo position.
            # Identity filter, not just "aligned": global alignment must consume the apo
            # chain end to end, so an unrelated fusion-partner insert (T4L/BRIL) can get
            # smeared across mediocre matches instead of cleanly gapped out -- see the
            # identical, empirically-verified issue and fix in pfam.py.
            fam_to_apo = _align_positions(sequence, apo_seq)
            apo_to_fam = {apo_pos: fam_pos for fam_pos, apo_pos in fam_to_apo.items()
                           if sequence[fam_pos] == apo_seq[apo_pos]}

            with tempfile.TemporaryDirectory() as tmp:
                tmp_pdb = Path(tmp) / "apo_chain.pdb"
                tmp_st = gemmi.Structure()
                tmp_st.add_model(gemmi.Model("1"))
                tmp_st[0].add_chain(chain)
                # Legacy PDB's chain-id column is 1 character -- BoltzMaker's own chain ids
                # (the family stem, e.g. "H2AAP") are frequently longer, so rename to a
                # short placeholder for this temporary upload only. GPCRdb's response is
                # matched back purely by residue number (_parse_generic_number_pdb), never
                # by chain name, so this is safe.
                tmp_st[0][0].name = "A"
                tmp_st.setup_entities()
                tmp_st.write_pdb(str(tmp_pdb))
                generic = self.client.assign_generic_numbers(tmp_pdb)
        except Exception as exc:
            print(f"BoltzMaker: WARNING: GPCRdb annotation failed ({exc})")
            return []

        if not generic:
            return []

        by_segment = {}
        for resnum, (segment_label, _generic_str) in generic.items():
            apo_pos = apo_resnum_to_pos.get(resnum)
            if apo_pos is None:
                continue
            fam_pos = apo_to_fam.get(apo_pos)
            if fam_pos is None:
                continue  # e.g. a fusion-construct residue that never aligns to the family sequence
            by_segment.setdefault(segment_label, []).append(fam_pos)

        motifs = []
        for segment_label, positions in by_segment.items():
            positions = sorted(set(positions))
            kind = "helix" if segment_label.startswith("TM") or segment_label == "H8" else "loop"
            motifs.append(Motif(name=segment_label, kind=kind, residues=positions,
                                 is_binding_site_adjacent=segment_label in _BINDING_SITE_ADJACENT))
        return motifs
