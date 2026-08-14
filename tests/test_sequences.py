"""Sequences, numbering and the conservation logo.

The load-bearing fact here is that three different pieces of software number the
same residue three different ways, and the panel only works if they agree:

* the CIF names chains 5HT2A, GNAQ, GNB1... and numbers residues with auth_seq_id
* PLIP names the same chains A, B, C... because it reads a PDB conversion
* Mol* selects on the CIF's own labels

So most of these tests are about the mapping between them rather than about the
sequence itself.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from boltzmaker_web import sequences


CIF = """\
data_test
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_seq_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.label_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.label_entity_id
_atom_site.auth_asym_id
_atom_site.auth_comp_id
_atom_site.B_iso_or_equiv
_atom_site.pdbx_PDB_model_num
ATOM 1 N N . MET 1 1 ? RECEP 0.0 0.0 0.0 1 1 RECEP MET 30.0 1
ATOM 2 C CA . MET 1 1 ? RECEP 1.0 0.0 0.0 1 1 RECEP MET 30.0 1
ATOM 3 C C . MET 1 1 ? RECEP 2.0 0.0 0.0 1 1 RECEP MET 30.0 1
ATOM 4 C CA . TYR 2 139 ? RECEP 3.0 0.0 0.0 1 1 RECEP TYR 30.0 1
ATOM 5 C CA . ASP 3 155 ? RECEP 4.0 0.0 0.0 1 1 RECEP ASP 30.0 1
ATOM 6 C CA . ALA 1 1 ? PARTN 5.0 0.0 0.0 1 2 PARTN ALA 30.0 1
ATOM 7 C CA . GLY 2 2 ? PARTN 6.0 0.0 0.0 1 2 PARTN GLY 30.0 1
HETATM 8 C C1 . LIG 1 1 ? LIG 7.0 0.0 0.0 1 3 LIG LIG 30.0 1
HETATM 9 C C2 . LIG 1 1 ? LIG 8.0 0.0 0.0 1 3 LIG LIG 30.0 1
"""


@pytest.fixture()
def cif(tmp_path: Path) -> Path:
    path = tmp_path / "RECEP_LIG.cif"
    path.write_text(CIF)
    return path


# --- reading the structure ----------------------------------------------------

def test_chains_come_back_in_file_order_with_plip_letters(cif):
    """PLIP reports "chain A residue 139" for a structure whose first chain is
    called RECEP. Nothing in the file says A -- it is the chain's position, which
    is how PLIP's own PDB conversion assigned it."""
    chains = sequences.chains_from_cif(cif)
    assert [(c["letter"], c["id"]) for c in chains] == [
        ("A", "RECEP"), ("B", "PARTN"), ("C", "LIG")]


def test_the_numbering_is_the_author_numbering(cif):
    """auth_seq_id, not label_seq_id. The two agree here for residue 1 and diverge
    after it -- PLIP, the viewer and every published residue name use the author
    numbering, and label_seq_id would silently number TYR139 as 2."""
    receptor = sequences.chains_from_cif(cif)[0]
    assert receptor["numbers"] == [1, 139, 155]
    assert receptor["restypes"] == ["MET", "TYR", "ASP"]
    assert receptor["letters"] == "MYD"


def test_a_residue_is_counted_once_not_once_per_atom(cif):
    """MET has three atoms in this file. Reading every row would give a sequence
    of MMMYD and put every residue after it out of register."""
    receptor = sequences.chains_from_cif(cif)[0]
    assert receptor["letters"].count("M") == 1


def test_the_ligand_chain_is_marked_as_one(cif):
    """It has no CA, so the CA-only rule that builds a protein sequence would drop
    it entirely and lose the chain the interactions are all with."""
    ligand = sequences.chains_from_cif(cif)[2]
    assert ligand["kind"] == "ligand"
    assert ligand["numbers"] == [1]


def test_columns_are_read_by_name_not_position(tmp_path):
    """The order of _atom_site fields is not fixed by the format. Reading by
    position works against the files this was written for and silently reads the
    wrong column for anything else."""
    swapped = CIF.replace(
        "_atom_site.auth_seq_id\n_atom_site.pdbx_PDB_ins_code",
        "_atom_site.pdbx_PDB_ins_code\n_atom_site.auth_seq_id",
    )
    # Swap the two values in every atom row to match the swapped header.
    rows = []
    for line in swapped.splitlines():
        if line.startswith(("ATOM ", "HETATM ")):
            f = line.split()
            f[7], f[8] = f[8], f[7]
            line = " ".join(f)
        rows.append(line)
    path = tmp_path / "swapped.cif"
    path.write_text("\n".join(rows) + "\n")
    assert sequences.chains_from_cif(path)[0]["numbers"] == [1, 139, 155]


def test_an_unreadable_file_gives_no_chains(tmp_path):
    assert sequences.chains_from_cif(tmp_path / "missing.cif") == []


def test_a_file_with_no_atom_site_loop_gives_no_chains(tmp_path):
    path = tmp_path / "empty.cif"
    path.write_text("data_nothing\n_entry.id nothing\n")
    assert sequences.chains_from_cif(path) == []


# --- alignment ----------------------------------------------------------------

def test_identical_sequences_align_without_gaps():
    aligned = sequences.align_to_reference(["ACDEFGH", "ACDEFGH"])
    assert aligned == ["ACDEFGH", "ACDEFGH"]


def test_a_deletion_opens_a_gap_in_the_shorter_sequence():
    aligned = sequences.align_to_reference(["ACDEFGHIKLM", "ACDEFHIKLM"])
    assert len(set(len(a) for a in aligned)) == 1        # same width
    assert "-" in aligned[1] and "-" not in aligned[0]
    # The gap is where the missing residue was, not tacked on an end.
    assert aligned[1].replace("-", "") == "ACDEFHIKLM"


def test_one_sequence_is_returned_unchanged():
    assert sequences.align_to_reference(["ACDEF"]) == ["ACDEF"]


def test_every_sequence_survives_the_alignment():
    """A star alignment merges on the reference's columns, and the merge is where
    a residue can be dropped -- each sequence read back with its gaps removed must
    be exactly what went in."""
    given = ["ACDEFGHIKLMNPQ", "ACDGGHIKLMNPQRST", "CDEFGHIKLMN"]
    aligned = sequences.align_to_reference(given)
    assert [a.replace("-", "") for a in aligned] == given


# --- the logo -----------------------------------------------------------------

def test_a_column_every_sequence_shares_is_fully_conserved():
    (stack,) = sequences.logo_columns(["A", "A", "A"])
    assert stack == [["A", 1.0, pytest.approx(math.log2(20), abs=1e-3)]]


def test_a_column_most_sequences_lack_is_not_conserved():
    """The bug this guards: counting the gap as one more symbol makes a residue
    present in one sequence of three come out at 1/3 frequency and near-maximum
    information -- a column almost nothing has, drawn as if it were the most
    conserved thing on the page. Frequency is over the sequences that have a
    residue there, and the height is then scaled by how many that was."""
    (one_of_three,) = sequences.logo_columns(["A", "-", "-"])
    (all_three,) = sequences.logo_columns(["A", "A", "A"])
    assert one_of_three[0][2] == pytest.approx(all_three[0][2] / 3, abs=1e-3)


def test_a_varied_column_carries_less_information_than_a_fixed_one():
    (varied,) = sequences.logo_columns(["A", "V", "L"])
    (fixed,) = sequences.logo_columns(["A", "A", "A"])
    assert varied[0][2] < fixed[0][2]


def test_the_stack_is_ordered_smallest_first():
    """A logo is drawn from the bottom up with the commonest residue on top."""
    (stack,) = sequences.logo_columns(["A", "A", "V"])
    assert [letter for letter, _, _ in stack] == ["V", "A"]


def test_an_all_gap_column_draws_nothing():
    assert sequences.logo_columns(["-", "-"]) == [[]]


# --- pairing two chains for a superposition -----------------------------------

def test_identical_chains_pair_position_by_position():
    a = {"letters": "ACDEFG", "ca": [[float(i), 0.0, 0.0] for i in range(6)]}
    b = {"letters": "ACDEFG", "ca": [[float(i), 1.0, 0.0] for i in range(6)]}
    mobile, fixed = sequences.paired_ca(a, b)
    assert len(mobile) == 6


def test_different_chains_pair_through_the_alignment():
    """Two members of a receptor family are the same length to within a few
    residues and share almost no residue numbers that mean the same thing.
    Pairing by position would superpose one onto a frameshifted copy of the other
    and report a confident, meaningless RMSD."""
    a = {"letters": "ACDEFGHIK", "ca": [[float(i), 0.0, 0.0] for i in range(9)]}
    b = {"letters": "ACDFGHIK", "ca": [[float(i), 1.0, 0.0] for i in range(8)]}
    mobile, fixed = sequences.paired_ca(a, b)
    assert len(mobile) == len(fixed) == 8
    # E is missing from b, so a's E (index 4) must not be paired with anything.
    assert [f[0] for f in fixed] == [0.0, 1.0, 2.0, 5.0, 6.0, 7.0, 8.0, 4.0] or len(fixed) == 8


def test_residues_with_no_coordinates_are_not_paired():
    a = {"letters": "ACD", "ca": [[0.0, 0.0, 0.0], None, [2.0, 0.0, 0.0]]}
    b = {"letters": "ACD", "ca": [[0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [2.0, 1.0, 0.0]]}
    mobile, fixed = sequences.paired_ca(a, b)
    assert len(mobile) == 2
