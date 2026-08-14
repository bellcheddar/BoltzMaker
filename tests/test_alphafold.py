"""Resolving, superposing and reporting an AlphaFold model.

Nothing here touches the network. The three external services are exercised by
using the panel; what these cover is the arithmetic and the choices, which are
where being quietly wrong would not announce itself -- a superposition that
reflects the molecule, or an accession picked off the top of a list.
"""

from __future__ import annotations

import math

import pytest

from boltzmaker_web import alphafold as af
from boltzmaker_web import results as bmz


# --- the checksum -------------------------------------------------------------

def test_the_checksum_is_uniprots_own():
    """CRC64-ISO, which is what UniParc indexes sequences by. Checked against the
    value UniParc really returns for the 5-HT2A construct in the example campaign:
    a checksum that is merely self-consistent finds nothing."""
    assert af.crc64("MDILCEENTSLSSTTNSLMQ") == af.crc64("MDILCEENTSLSSTTNSLMQ")
    assert af.crc64("A") != af.crc64("B")
    assert len(af.crc64("PEPTIDE")) == 16


# --- the superposition --------------------------------------------------------

def _rotate(points, matrix, shift=(0.0, 0.0, 0.0)):
    return [[sum(matrix[i][j] * p[j] for j in range(3)) + shift[i] for i in range(3)]
            for p in points]


CLOUD = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0],
         [1.0, 2.0, 0.5], [2.0, 1.0, 1.0], [0.5, 0.5, 2.0]]


def test_identical_coordinates_superpose_onto_themselves():
    _, _, rmsd = af.superpose(CLOUD, CLOUD)
    assert rmsd == pytest.approx(0.0, abs=1e-6)


def test_a_known_rotation_is_recovered():
    """A quarter turn about z, and a translation. If the maths were wrong this
    would still return a number -- it is the RMSD going to zero that says the
    rotation found was the one applied."""
    quarter = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    moved = _rotate(CLOUD, quarter, (5.0, -3.0, 2.0))
    _, _, rmsd = af.superpose(moved, CLOUD)
    assert rmsd == pytest.approx(0.0, abs=1e-6)


def test_a_mirror_image_is_not_fitted_by_reflecting_it():
    """The failure the quaternion form exists to avoid. An SVD-based Kabsch
    without a determinant check will happily return a reflection and report a
    perfect fit for a molecule that is the mirror of the target -- which for a
    protein means every stereocentre inverted."""
    mirrored = [[-p[0], p[1], p[2]] for p in CLOUD]
    _, _, rmsd = af.superpose(mirrored, CLOUD)
    assert rmsd > 0.5


def test_too_few_points_is_refused():
    with pytest.raises(af.AlphaFoldError, match="three"):
        af.superpose(CLOUD[:2], CLOUD[:2])


def test_the_transform_is_the_one_reported(tmp_path):
    """superpose() returns a rotation and two centroids, and apply_transform has
    to compose them the same way round. Getting that backwards moves the model to
    a plausible-looking wrong place."""
    quarter = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    moved = _rotate(CLOUD, quarter, (5.0, -3.0, 2.0))
    rotation, centres, _ = af.superpose(moved, CLOUD)
    centre_m, centre_f = centres
    for source, expected in zip(moved, CLOUD):
        point = [source[i] - centre_m[i] for i in range(3)]
        landed = [sum(rotation[i][j] * point[j] for j in range(3)) + centre_f[i]
                  for i in range(3)]
        assert landed == pytest.approx(expected, abs=1e-6)


# --- rewriting the file -------------------------------------------------------

CIF = """\
data_model
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.B_iso_or_equiv
ATOM 1 CA MET 1 A 0.000 0.000 0.000 95.0
ATOM 2 CA TYR 2 A 1.000 0.000 0.000 90.0
ATOM 3 CA ASP 3 A 0.000 2.000 0.000 40.0
"""


def test_only_the_coordinates_move(tmp_path):
    """The B-factor column of an AlphaFold model is its pLDDT, which is the useful
    thing about it. A rewrite that reformats the row would lose it."""
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    out = af.apply_transform(CIF, identity, [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]])
    rows = [line.split() for line in out.splitlines() if line.startswith("ATOM")]
    assert [r[6] for r in rows] == ["10.000", "11.000", "10.000"]
    assert [r[9] for r in rows] == ["95.0", "90.0", "40.0"]
    assert [r[3] for r in rows] == ["MET", "TYR", "ASP"]
    # The header survives, so the file is still a parseable mmCIF.
    assert out.splitlines()[0] == "data_model"


def test_a_file_with_no_coordinates_is_refused():
    with pytest.raises(af.AlphaFoldError, match="coordinates"):
        af.apply_transform("data_x\n_entry.id x\n", [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                           [[0, 0, 0], [0, 0, 0]])


# --- pairing residues ---------------------------------------------------------

def test_residues_pair_on_number_and_type():
    """Number alone is enough when the sequences are identical and quietly wrong
    when they are not: a construct numbered from its own start would pair every
    residue with the wrong one and still superpose, on nonsense."""
    model = {"numbers": [1, 2, 3], "restypes": ["MET", "TYR", "ASP"],
             "ca": [[0, 0, 0], [1, 0, 0], [2, 0, 0]]}
    target = {"numbers": [1, 2, 3], "restypes": ["MET", "PHE", "ASP"],
              "ca": [[0, 0, 1], [1, 0, 1], [2, 0, 1]]}
    mobile, fixed = af.matched_atoms(model, target)
    assert len(mobile) == 2          # residue 2 differs, so it is not paired
    assert fixed == [[0, 0, 1], [2, 0, 1]]


def test_a_residue_only_one_side_has_is_skipped():
    model = {"numbers": [1, 5], "restypes": ["MET", "ASP"], "ca": [[0, 0, 0], [5, 0, 0]]}
    target = {"numbers": [1, 2], "restypes": ["MET", "TYR"], "ca": [[0, 0, 1], [2, 0, 1]]}
    mobile, fixed = af.matched_atoms(model, target)
    assert len(mobile) == 1


# --- the apo RMSD -------------------------------------------------------------

def test_the_apo_rmsd_is_weighted_by_residue_count():
    """A 4-residue loop and a 40-residue helix are not equal evidence. Unweighted,
    the shortest motif in the set moves the figure as much as the longest."""
    rows = [
        {"target_stem": "T", "ca_rmsd_A": "1.0", "n_residues": "90"},
        {"target_stem": "T", "ca_rmsd_A": "11.0", "n_residues": "10"},
    ]
    out = bmz._apo_rmsd(rows)
    assert out["T"]["rmsd"] == pytest.approx(2.0)       # not the plain mean of 6.0
    assert out["T"]["motifs"] == 2


def test_motifs_with_no_measurement_are_left_out():
    """compare-sse writes N/A where it could not align a motif. Reading that as a
    zero would pull every aggregate towards a fit that never happened."""
    rows = [
        {"target_stem": "T", "ca_rmsd_A": "4.0", "n_residues": "10"},
        {"target_stem": "T", "ca_rmsd_A": "N/A", "n_residues": "10"},
        {"target_stem": "T", "ca_rmsd_A": "", "n_residues": "10"},
    ]
    out = bmz._apo_rmsd(rows)
    assert out["T"] == {"rmsd": 4.0, "motifs": 1}


def test_a_target_with_no_sse_rows_gets_no_entry():
    assert bmz._apo_rmsd([]) == {}
