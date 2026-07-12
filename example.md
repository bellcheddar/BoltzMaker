# BoltzMaker campaign template
#
# Copy this file to boltz_input.md and edit, or run `python3 BoltzMaker.py
# new` to generate a starting file by answering plain questions instead.
# Every block below is "Label: value" lines with a blank line between
# blocks -- no markdown, no YAML, no brackets, no quoting. Two rules
# matter most and are easy to miss:
#   1. Every Protein/Partner/Ligand short name shares ONE namespace across
#      the whole file (a protein and a ligand can't reuse the same id) and
#      must be 5 characters or fewer -- Boltz truncates longer ids
#      internally and crashes later with a confusing error, so get this
#      right up front (`preflight` also checks it).
#   2. A block ends at the next genuinely blank line -- always leave one
#      blank line between blocks.
# This file shows only the fields most campaigns actually need. Every
# optional field is documented, with its exact syntax, in the "Optional
# fields reference" section at the very bottom -- copy a line from there
# into the block it applies to and delete the leading "#" to switch it
# on. See the README's "boltz_input.md format" section for a shorter
# annotated version of this same reference.

Settings:
Output folder: ./boltz_yamls  # where generated per-target YAMLs are written
Predict affinity: no          # heavier prediction pass -- turn on when you need Kd/pIC50

# ===================== Proteins =====================
# One block per protein chain. Sequence is the only required field.

Protein: RECP1                     # short name, max 5 characters, unique across the whole file
Sequence: MDILCEENTSLSSTTNSLMQ...  # the full amino acid sequence
Partners: CHNX, CHNY               # optional: co-folded chains, defined as their own
                                   # Partner: blocks below

# A second protein -- repeat the whole block as needed:

Protein: RECP2
Sequence: MTLESIMACCLSEEAKEARR...
Partners: CHNX, CHNY

# ===================== Partners =====================
# Co-folded chains referenced by a Protein's Partners: field, above.
# Sequence is the only required field.

Partner: CHNX
Sequence: MTLESIMACCLSEEAKEARR...

Partner: CHNY
Sequence: MSELDQLRQEAEQLKNQIRD...

# ===================== Ligands =====================
# Exactly one of SMILES/CCD is required per ligand.

Ligand: LIG1
SMILES: FC(F)CNC(C1=CC=CC=C1)=O  # exactly one of SMILES/CCD is required

Ligand: LIG2
CCD: GOL  # a Chemical Component Dictionary code (e.g. common crystallization
          # additives/ions) instead of a SMILES

# Every protein is crossed with every ligand -- {protein}_{ligand}.yaml per
# pair -- that's the whole campaign.

# ===================== Constraints (optional) =====================
# Standalone sentences naming the protein they belong to, written anywhere
# in the file (uncomment one to try it):

# Covalent bond: RECP1 residue 44 atom SG to LIG1 residue 1 atom C3
# Pocket contact: RECP1 residue 148
# Distance constraint: RECP1 residue 10 to RECP1 residue 80 within 8.0 Angstrom

# ===================== Optional fields reference =====================
# Every optional field, shown with its exact syntax and a short
# explanation. Copy a line into the matching block above and delete the
# leading "#" to switch it on. (Settings: has no optional fields beyond
# the two already shown above, so there's no entry for it here.)

# --- Protein: block -----------------------------------------------------

# Ligands: LIG1, LIG3            # optional: restrict this protein to a ligand
                                  # subset. Omitting this field (the default)
                                  # crosses this protein with every ligand
                                  # below; "Ligands: none" is a third, distinct
                                  # option -- a ligand-free/apo target.

# Modifications: SEP:5           # optional: CCD:position tokens for modified
                                  # residues (e.g. phosphoserine)

# Cyclic: yes                    # optional: cyclic polymer (e.g. a cyclic peptide)

# MSA: empty                     # optional: path to a precomputed MSA, or "empty"
                                  # for single-sequence mode (skip MSA generation)

# Templates: reference_structure.cif
                                  # optional: structural template file(s), applied
                                  # to all protein chains (no per-chain mapping --
                                  # hand-edit the generated YAML for that rarer case)

# Apo structure: reference/apo.pdb
                                  # optional: a reference apo/unbound structure, used only
                                  # by `compare-sse`, never by generate/run. No genuinely
                                  # apo experimental structure? Predict one: give another
                                  # Protein: block the same Sequence: and Ligands: none
                                  # (above), run the campaign once, then point this at
                                  # its output in boltz_cif/{that_protein}_model_0.cif.

# Apo chain: A                    # optional: explicit chain id in the apo structure above
                                  # (omit to auto-detect via sequence identity)

# Family type: gpcr               # optional: gpcr / kinase / auto (default) -- selects
                                  # `compare-sse`'s motif annotator

# Group: RECP1                    # optional: shared display/report name for multiple
                                  # Protein: blocks that are the same underlying receptor
                                  # (e.g. with/without a partner, or a predicted apo
                                  # variant) -- defaults to this block's own name if unset

# --- Partner: block -------------------------------------------------------

# Type: dna              # optional: protein (default) / dna / rna

# Copies: X1, X2         # optional: homo-oligomer chain-id override -- this one
                          # partner sequence becomes multiple chains

# Modifications / Cyclic / MSA: same optional fields as Protein blocks, above

# --- Ligand: block ---------------------------------------------------------

# Role: agonist                  # optional: agonist / antagonist -- reporting only
                                  # (dashboard chart shapes), never affects generate/run
