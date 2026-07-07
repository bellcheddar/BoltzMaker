# Fixture: pocket contact constraints

Exercises the "Pocket contact:" statement (specific residue tokens) instead
of the whole-chain default.

Settings:
Output folder: ./boltz_yamls
Predict affinity: yes

Protein: TESTR
Sequence: MDILCEENTSLSSTTNSLMQLNDDTRLYSNDFNSGEANTSDAFNWTVDSENRT
Partners: PTNA

Partner: PTNA
Sequence: MSELDQLRQEAEQLKNQIRDARKACADATLSQITNNIDPVGRIQMRTRRTLRGH

Ligand: LIG1
SMILES: CC(=O)Oc1ccccc1C(=O)O

Ligand: LIG2
SMILES: CN1C=NC2=C1C(=O)N(C(=O)N2C)C

Pocket contact: TESTR residue 42
Pocket contact: TESTR residue 45
