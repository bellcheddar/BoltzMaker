# Example: beta-2 adrenergic receptor + Gs alpha, agonist vs antagonist panel
#
# Two Protein blocks sharing one sequence, each scoped to one ligand via
# Ligands: -- not a single family crossed with both, deliberately. Gs
# protein only forms a stable ternary complex with an *active*,
# agonist-bound receptor (the entire structural basis of the Rasmussen
# 2011 active-state structure this example cites, PDB 3SN6); an
# antagonist-bound receptor does not engage G-protein in reality. Boltz
# has no explicit constraint enforcing that, so co-folding Gs with BOTH
# ligands (an earlier version of this example did exactly that) makes it
# predict a near-identical active-like conformation for both regardless
# of ligand identity -- confirmed directly: superposing the two resulting
# holo structures on each other gave 0.38 Angstrom RMSD, essentially the
# same fold, silently defeating the point of comparing an agonist against
# an antagonist at all. Splitting into two blocks -- ADRB2+Gs for the
# agonist, ADRB2 alone for the antagonist, matching what each ligand
# would actually form in solution -- is what lets `compare-sse` show a
# real, biologically meaningful difference between the two.
#
# ADRB2 (beta-2 adrenergic receptor, UniProt P07550) + Gs alpha (GNAS,
# UniProt P63092) is one of the most extensively published GPCR/G-protein
# systems in structural biology. Isoproterenol (agonist) and propranolol
# (antagonist) are both long-public, well-known drugs.

Settings:
Output folder: ./boltz_yamls
Predict affinity: yes

Protein: ADRB2
Sequence: MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL
Partners: GNAS
Ligands: ISO1
# Real apo (inactive-state) beta2-adrenergic receptor, PDB 2RH1 (Cherezov et al.
# 2007, T4-lysozyme fusion in place of ICL3) -- used by `compare-sse` to compare
# this agonist-bound (+Gs) prediction against the unliganded, inactive state.
# GPCRdb assigns TM1-7/H8/loop generic numbers from this structure.
Apo structure: reference/2rh1_adrb2_apo.pdb
Family type: gpcr
Group: ADRB2

# Same receptor, antagonist-bound: deliberately no Partners: line -- propranolol
# does not stabilize a Gs-competent state, so it isn't co-folded here. 5-char id
# limit (see boltz_input.md format docs below) means it can't just be "ADRB2"
# again anyway; AR2NG = "ADRB2, No Gs".

Protein: AR2NG
Sequence: MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL
Ligands: PRO1
Apo structure: reference/2rh1_adrb2_apo.pdb
Family type: gpcr
Group: ADRB2

Partner: GNAS
Sequence: MGCLGNSKTEDQRNEEKAQREANKKIEKQLQKDKQVYRATHRLLLLGAGESGKSTIVKQMRILHVNGFNGEGGEEDPQAARSNSDGEKATKVQDIKNNLKEAIETIVAAMSNLVPPVELANPENQFRVDYILSVMNVPDFDFPPEFYEHAKALWEDEGVRACYERSNEYQLIDCAQYFLDKIDVIKQADYVPSDQDLLRCRVLTSGIFETKFQVDKVNFHMFDVGGQRDERRKWIQCFNDVTAIIFVVASSSYNMVIREDNQTNRLQEALNLFKSIWNNRWLRTISVILFLNKQDLLAEKVLAGKSKIEDYFPEFARYTTPEDATPEPGEDPRVTRAKYFIRDEFLRISTASGDGRHYCYPHFTCAVDTENIRRVFNDCRDIIQRMHLRQYELL

Ligand: ISO1
SMILES: CC(C)NCC(O)c1ccc(O)c(O)c1
Role: agonist

Ligand: PRO1
SMILES: CC(C)NCC(O)COc1cccc2ccccc12
Role: antagonist
