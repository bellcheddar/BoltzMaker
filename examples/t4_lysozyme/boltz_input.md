# Example: T4 lysozyme L99A + benzene
#
# The simplest possible campaign shape: one protein, no partners, no
# pocket contacts (unconstrained folding), one ligand -> a single target.
# Good first smoke test: small (164 residues + benzene), fast, low memory.
#
# T4 lysozyme (bacteriophage T4 endolysin, UniProt P00720) with the classic
# L99A cavity mutation is one of the most studied model systems in
# structural biology for engineered hydrophobic-cavity ligand binding
# (Matthews lab and decades of follow-on work) -- entirely public domain
# science, no proprietary data of any kind.

Settings:
Output folder: ./boltz_yamls
Predict affinity: yes

# UniProt P00720, canonical sequence, with the single L99A substitution
# (position 99: Leu -> Ala) that creates the buried hydrophobic cavity
# benzene is famous for occupying.

Protein: T4L
Sequence: MNIFEMLRIDERLRLKIYKDTEGYYTIGIGHLLTKSPSLNAAKSELDKAIGRNCNGVITKDEAEKLFNQDVDAAVRGILRNAKLKPVYDSLDAVRRCAAINMVFQMGETGVAGFTNSLRMLQQKRWDEAAVNLAKSIWYNQTPNRAKRVITTFRTGTWDAYKNL
# Real apo (ligand-free) wild-type T4 lysozyme, PDB 2LZM (1.7 Angstrom, Weaver &
# Matthews 1987) -- used by `compare-sse` to compare this L99A+benzene prediction
# against the unliganded state. T4L is neither a GPCR nor a kinase, so this uses
# the Pfam-domain fallback annotator (Family type left at its "auto" default).
Apo structure: reference/2lzm_t4l_apo.pdb

Ligand: BNZ1
SMILES: c1ccccc1
