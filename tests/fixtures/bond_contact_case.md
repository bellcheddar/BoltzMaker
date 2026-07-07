# Fixture: covalent bond and distance constraint

Exercises "Covalent bond:" (covalent linkage) and "Distance constraint:"
(arbitrary residue-residue distance constraint).

Settings:
Output folder: ./boltz_yamls
Predict affinity: no

Protein: COVP
Sequence: MSELDQLQECAEQLKNQIRDARKACADATLSQITNNIDPVGRIQMRTRRTLRGH

Ligand: FRAG1
SMILES: C=CC(=O)Nc1ccccc1

Covalent bond: COVP residue 10 atom SG to FRAG1 residue 1 atom C12
Distance constraint: COVP residue 5 to COVP residue 15 within 8.0 Angstrom
