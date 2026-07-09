"""Per-motif apo/holo comparison metrics, computed on the already-superposed pair
(alignment.build_comparison_frame) over residues mapped through the family sequence
(never raw seqid.num).
"""

import math

import gemmi
import numpy as np


def _ca_coords(polymer, positions: list) -> np.ndarray:
    return np.array([[polymer[i].sole_atom("CA").pos.x, polymer[i].sole_atom("CA").pos.y,
                       polymer[i].sole_atom("CA").pos.z] for i in positions])


def _apply_transform(coords: np.ndarray, transform: "gemmi.Transform") -> np.ndarray:
    out = np.empty_like(coords)
    for i, row in enumerate(coords):
        p = transform.apply(gemmi.Position(*row))
        out[i] = (p.x, p.y, p.z)
    return out


def ca_rmsd(apo_coords: np.ndarray, holo_coords: np.ndarray) -> float:
    diff = apo_coords - holo_coords
    return float(np.sqrt(np.mean(np.sum(diff ** 2, axis=1))))


def centroid_shift(apo_coords: np.ndarray, holo_coords: np.ndarray) -> float:
    return float(np.linalg.norm(apo_coords.mean(axis=0) - holo_coords.mean(axis=0)))


def helix_axis(coords: np.ndarray) -> object:
    """First principal component of the CA positions, sign-corrected to point N->C.
    None if there aren't enough points to define an axis.
    """
    if len(coords) < 2:
        return None
    centered = coords - coords.mean(axis=0)
    _, _, vt = np.linalg.svd(centered)
    axis = vt[0]
    direction = coords[-1] - coords[0]
    if np.dot(axis, direction) < 0:
        axis = -axis
    return axis


def _angle_between(axis1: object, axis2: object) -> object:
    if axis1 is None or axis2 is None:
        return None
    cos_angle = float(np.clip(np.dot(axis1, axis2), -1.0, 1.0))
    return math.degrees(math.acos(cos_angle))


def axis_rotation_angle(apo_coords: np.ndarray, holo_coords: np.ndarray) -> object:
    return _angle_between(helix_axis(apo_coords), helix_axis(holo_coords))


def kink_angle(coords: np.ndarray, min_half: int = 4) -> object:
    """Splits the CA run into N-/C-terminal halves and returns the angle between
    their two PCA axes. None (undefined) if either half has fewer than min_half
    residues.
    """
    n = len(coords)
    mid = n // 2
    if mid < min_half or (n - mid) < min_half:
        return None
    return _angle_between(helix_axis(coords[:mid]), helix_axis(coords[mid:]))


def _nearest_sse_boundary(positions: list, elements: list) -> object:
    """positions are the motif's structure-native polymer indices (already sorted);
    elements is a LoadedStructure.helices/.sheets list (SSEElement, seqid-numbered).
    Returns (start_seqid, end_seqid) of whichever element overlaps the motif the most,
    or None if there's no overlap (e.g. no deposited/DSSP annotation for this region).
    """
    if not positions or not elements:
        return None
    lo, hi = positions[0], positions[-1]
    best, best_overlap = None, 0
    for el in elements:
        overlap = min(hi, el.end_seqid) - max(lo, el.start_seqid)
        if overlap > best_overlap:
            best, best_overlap = el, overlap
    return (best.start_seqid, best.end_seqid) if best else None


def sse_boundary_shift(apo: object, holo: object, apo_positions: list, holo_positions: list) -> tuple:
    """Returns (start_delta, end_delta) in residue counts (holo - apo), or (None, None)
    if either structure has no SS annotation for this motif.
    """
    if apo.ss_source == "none" or holo.ss_source == "none":
        return None, None
    apo_elements = apo.helices + apo.sheets
    holo_elements = holo.helices + holo.sheets
    apo_bounds = _nearest_sse_boundary(sorted(apo_positions), apo_elements)
    holo_bounds = _nearest_sse_boundary(sorted(holo_positions), holo_elements)
    if apo_bounds is None or holo_bounds is None:
        return None, None
    return holo_bounds[0] - apo_bounds[0], holo_bounds[1] - apo_bounds[1]


def phi_psi_flags(structure: object, positions: list, threshold_deg: float) -> object:
    """positions are the structure-native polymer indices for one structure's copy of
    a motif. Returns {polymer_index: (phi_deg, psi_deg)}, skipping any residue whose
    phi/psi can't be computed (chain terminus, missing neighbor atoms).
    """
    polymer = structure.polymer
    out = {}
    for i in positions:
        if i <= 0 or i >= len(polymer) - 1:
            continue
        try:
            phi, psi = gemmi.calculate_phi_psi(polymer[i - 1], polymer[i], polymer[i + 1])
        except Exception:
            continue
        out[i] = (math.degrees(phi), math.degrees(psi))
    return out


def _circular_delta(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 360.0
    return min(d, 360.0 - d)


def phi_psi_deltas(frame: object, motif: object, threshold_deg: float) -> tuple:
    """Returns (n_flagged, flagged_residue_family_positions) for one motif -- phi/psi
    computed independently within each structure's own chain (prev/next never cross
    apo/holo), then compared per family-sequence position.
    """
    apo_positions = [frame.fam_to_apo[p] for p in motif.residues if p in frame.fam_to_apo]
    holo_positions = [frame.fam_to_holo[p] for p in motif.residues if p in frame.fam_to_holo]
    apo_angles = phi_psi_flags(frame.apo, apo_positions, threshold_deg)
    holo_angles = phi_psi_flags(frame.holo, holo_positions, threshold_deg)

    flagged = []
    for fam_pos in motif.residues:
        apo_i = frame.fam_to_apo.get(fam_pos)
        holo_i = frame.fam_to_holo.get(fam_pos)
        if apo_i not in apo_angles or holo_i not in holo_angles:
            continue
        phi_a, psi_a = apo_angles[apo_i]
        phi_h, psi_h = holo_angles[holo_i]
        if _circular_delta(phi_a, phi_h) > threshold_deg or _circular_delta(psi_a, psi_h) > threshold_deg:
            flagged.append(fam_pos)
    return len(flagged), flagged


def _residue_distance(structure: object, fam_to_pos: dict, fam_pos: object) -> object:
    i = fam_to_pos.get(fam_pos) if fam_pos is not None else None
    if i is None:
        return None
    try:
        return structure.polymer[i].sole_atom("CA").pos
    except Exception:
        return None


def classify_state(frame: object, anchor1_fam_pos: object, anchor2_fam_pos: object,
                    threshold: float) -> tuple:
    """Generic "in"/"out" distance classifier shared by DFG and alphaC states: measures
    the CA-CA distance between two named anchor residues (e.g. DFG-Asp and the
    catalytic Lys) in both structures. A coarse geometric proxy for *shift detection*
    (did the state change between apo and holo), not a publication-grade dihedral
    classifier. Returns (state_apo, state_holo, changed) with None entries where an
    anchor residue couldn't be resolved in that structure.
    """
    apo_p1 = _residue_distance(frame.apo, frame.fam_to_apo, anchor1_fam_pos)
    apo_p2 = _residue_distance(frame.apo, frame.fam_to_apo, anchor2_fam_pos)
    holo_p1 = _residue_distance(frame.holo, frame.fam_to_holo, anchor1_fam_pos)
    holo_p2 = _residue_distance(frame.holo, frame.fam_to_holo, anchor2_fam_pos)

    def _state(p1, p2):
        if p1 is None or p2 is None:
            return None
        return "in" if p1.dist(p2) < threshold else "out"

    state_apo, state_holo = _state(apo_p1, apo_p2), _state(holo_p1, holo_p2)
    changed = None if (state_apo is None or state_holo is None) else state_apo != state_holo
    return state_apo, state_holo, changed


def compute_motif_row(frame: object, motif: object, phi_psi_threshold: float = 30.0) -> object:
    """Returns a dict of every per-motif metric for one (family, target, motif) row,
    or None if the motif has too few residues resolvable in both apo and holo to
    compute anything meaningful.
    """
    apo_positions = sorted(frame.fam_to_apo[p] for p in motif.residues if p in frame.fam_to_apo)
    holo_positions = sorted(frame.fam_to_holo[p] for p in motif.residues if p in frame.fam_to_holo)
    common_fam = [p for p in motif.residues if p in frame.fam_to_apo and p in frame.fam_to_holo]
    if not common_fam:
        return None

    apo_coords_raw = _ca_coords(frame.apo.polymer, [frame.fam_to_apo[p] for p in common_fam])
    holo_coords = _ca_coords(frame.holo.polymer, [frame.fam_to_holo[p] for p in common_fam])
    apo_coords = _apply_transform(apo_coords_raw, frame.sup.transform)

    is_helical = motif.kind == "helix"
    boundary_start_delta, boundary_end_delta = sse_boundary_shift(frame.apo, frame.holo,
                                                                    apo_positions, holo_positions)
    n_flagged, flagged = phi_psi_deltas(frame, motif, phi_psi_threshold)

    kink_apo = kink_angle(apo_coords) if is_helical else None
    kink_holo = kink_angle(holo_coords) if is_helical else None
    kink_delta = kink_holo - kink_apo if (kink_apo is not None and kink_holo is not None) else None

    return {
        "motif_name": motif.name,
        "motif_kind": motif.kind,
        "n_residues": len(common_fam),
        "ca_rmsd_A": ca_rmsd(apo_coords, holo_coords),
        "centroid_shift_A": centroid_shift(apo_coords, holo_coords),
        "axis_rotation_deg": axis_rotation_angle(apo_coords, holo_coords) if is_helical else None,
        "kink_angle_apo_deg": kink_apo,
        "kink_angle_holo_deg": kink_holo,
        "kink_angle_delta_deg": kink_delta,
        "boundary_start_delta": boundary_start_delta,
        "boundary_end_delta": boundary_end_delta,
        "n_flagged_phipsi_residues": n_flagged,
        "flagged_residues": flagged,
    }
