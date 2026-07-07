# BoltzMaker campaign template
#
# Copy this file to boltz_input.md and edit, or run `python3 BoltzMaker.py
# new` to generate a starting file by answering plain questions instead.
# Every block below is "Label: value" lines with a blank line between
# blocks -- no markdown, no YAML, no brackets, no quoting. Optional fields
# are shown commented out (delete the leading "#" to switch one on). See
# the README's "boltz_input.md format" section for a shorter annotated
# version of this same reference.

Settings:
Output folder: ./boltz_yamls  # where generated per-target YAMLs are written
Predict affinity: no          # heavier prediction pass -- turn on when you need Kd/pIC50

Protein: RECP1                     # short name, MAX 5 CHARACTERS (Boltz truncates
                                   # longer chain ids internally and crashes later --
                                   # `preflight` catches this). Also names the output
                                   # file: {family_id}_{ligand_id}.yaml
Sequence: MDILCEENTSLSSTTNSLMQ...  # the full amino acid sequence
Partners: CHNX, CHNY               # optional: co-folded chains, defined as their own
                                   # Partner: blocks below

# Ligands: LIG1, LIG3            # optional: restrict this protein to a ligand
                                  # subset (default: crossed with every ligand below)

# Modifications: SEP:5           # optional: CCD:position tokens for modified
                                  # residues (e.g. phosphoserine)

# Cyclic: yes                    # optional: cyclic polymer (e.g. a cyclic peptide)

# MSA: empty                     # optional: path to a precomputed MSA, or "empty"
                                  # for single-sequence mode (skip MSA generation)

# Templates: reference_structure.cif
                                  # optional: structural template file(s), applied
                                  # to all protein chains (no per-chain mapping --
                                  # hand-edit the generated YAML for that rarer case)

# A second protein -- repeat the whole block as needed:

Protein: RECP2
Sequence: MTLESIMACCLSEEAKEARR...
Partners: CHNX, CHNY

Partner: CHNX
Sequence: MTLESIMACCLSEEAKEARR...
# Type: dna              # optional: protein (default) / dna / rna
# Copies: X1, X2         # optional: homo-oligomer chain-id override -- this one
                          # partner sequence becomes multiple chains
# Modifications / Cyclic / MSA: same optional fields as Protein blocks, above

Partner: CHNY
Sequence: MSELDQLRQEAEQLKNQIRD...

Ligand: LIG1
SMILES: FC(F)CNC(C1=CC=CC=C1)=O  # exactly one of SMILES/CCD is required

Ligand: LIG2
CCD: GOL  # a Chemical Component Dictionary code (e.g. common crystallization
          # additives/ions) instead of a SMILES

# Every protein is crossed with every ligand -- {protein}_{ligand}.yaml per
# pair -- that's the whole campaign. Constraints are standalone sentences
# naming the protein they belong to, written anywhere in the file
# (uncomment one to try it):

# Covalent bond: RECP1 residue 44 atom SG to LIG1 residue 1 atom C3
# Pocket contact: RECP1 residue 148
# Distance constraint: RECP1 residue 10 to RECP1 residue 80 within 8.0 Angstrom
