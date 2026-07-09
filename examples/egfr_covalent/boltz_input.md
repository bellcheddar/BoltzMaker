# Example: EGFR kinase domain + a generic covalent fragment
#
# Demonstrates the "Covalent bond:" statement -- a covalent linkage
# between a ligand atom and a specific protein atom, the feature
# covalent-inhibitor work actually needs. The fragment here
# (N-phenylacrylamide, a generic acrylamide/Michael-acceptor warhead) is
# simple, public, textbook chemistry, not tied to any real proprietary
# compound.
#
# EGFR (epidermal growth factor receptor, UniProt P00533) Cys797 is the
# well-known covalent-inhibitor target residue used by several approved
# drugs (osimertinib, afatinib, etc. -- public pharmacology knowledge).
# This uses only the kinase domain (full-length residues ~696-1022) to
# keep the target small; residue numbering below is LOCAL to this
# truncated sequence, where local position 102 = EGFR Cys797 in
# full-length UniProt numbering (verified: this truncation's residue 102
# is 'C').

Settings:
Output folder: ./boltz_yamls
Predict affinity: yes

Protein: EGFR
Sequence: GEAPNQALLRILKETEFKKIKVLGSGAFGTVYKGLWIPEGEKVKIPVAIKELREATSPKANKEILDEAYVMASVDNPHVCRLLGICLTSTVQLITQLMPFGCLLDYVREHKDNIGSQYLLNWCVQIAKGMNYLEDRRLVHRDLAARNVLVKTPQHVKITDFGLAKLLGAEEKEYHAEGGKVPIKWMALESILHRIYTHQSDVWSYGVTVWELMTFGSKPYDGIPASEISSILEKGERLPQPPICTIDVYMIMVKCWMIDADSRPKFRELIIEFSKMARDPQRYLVIQGDERMHLPSPTDSNFYRALMDEEDMDDVVDADEYLIPQQG
# Real apo (ligand-free) EGFR kinase domain, PDB 1M14 (Stamos et al. 2002) -- used
# by `compare-sse` to compare this covalent-fragment prediction against the
# unliganded state. KLIFS identifies the kinase pocket motifs (hinge, gatekeeper
# T790, DFG, catalytic Lys745, alphaC-Glu762) from the "EGFR" name below.
Apo structure: reference/1m14_egfr_apo.pdb
Family type: kinase

# N-phenylacrylamide: a generic acrylamide (Michael-acceptor) warhead
# fragment. Atom name C12 is the terminal vinyl carbon -- the
# electrophilic site a cysteine thiol attacks in a real covalent reaction.

Ligand: FRAG1
SMILES: C=CC(=O)Nc1ccccc1

# Covalent bond: ligand atom C12 (the terminal =CH2 of the acrylamide
# warhead, computed via Boltz's own canonical-atom-naming scheme) bonded
# to Cys797's side-chain sulfur (SG), residue 102 in this local numbering.
Covalent bond: EGFR residue 102 atom SG to FRAG1 residue 1 atom C12
