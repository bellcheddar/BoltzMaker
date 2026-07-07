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

Ligand: BNZ1
SMILES: c1ccccc1
