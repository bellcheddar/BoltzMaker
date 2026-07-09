# Example: beta-2 adrenergic receptor + Gs alpha, agonist vs antagonist panel
#
# Demonstrates the family x partners x ligand cross-product: one receptor
# family, one co-folded partner, two ligands -> 2 generated targets. This
# is the same campaign *shape* as a real multi-ligand selectivity/SAR
# panel, built entirely from public data (no proprietary content of any
# kind).
#
# ADRB2 (beta-2 adrenergic receptor, UniProt P07550) + Gs alpha (GNAS,
# UniProt P63092) is one of the most extensively published GPCR/G-protein
# systems in structural biology (e.g. PDB 3SN6 and its many descendants).
# Isoproterenol (agonist) and propranolol (antagonist) are both
# long-public, well-known drugs.

Settings:
Output folder: ./boltz_yamls
Predict affinity: yes

Protein: ADRB2
Sequence: MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL
Partners: GNAS
# Real apo (inactive-state) beta2-adrenergic receptor, PDB 2RH1 (Cherezov et al.
# 2007, T4-lysozyme fusion in place of ICL3) -- used by `compare-sse` to compare
# both agonist- and antagonist-bound predictions against the unliganded, inactive
# state. GPCRdb assigns TM1-7/H8/loop generic numbers from this structure.
Apo structure: reference/2rh1_adrb2_apo.pdb
Family type: gpcr

Partner: GNAS
Sequence: MGCLGNSKTEDQRNEEKAQREANKKIEKQLQKDKQVYRATHRLLLLGAGESGKSTIVKQMRILHVNGFNGEGGEEDPQAARSNSDGEKATKVQDIKNNLKEAIETIVAAMSNLVPPVELANPENQFRVDYILSVMNVPDFDFPPEFYEHAKALWEDEGVRACYERSNEYQLIDCAQYFLDKIDVIKQADYVPSDQDLLRCRVLTSGIFETKFQVDKVNFHMFDVGGQRDERRKWIQCFNDVTAIIFVVASSSYNMVIREDNQTNRLQEALNLFKSIWNNRWLRTISVILFLNKQDLLAEKVLAGKSKIEDYFPEFARYTTPEDATPEPGEDPRVTRAKYFIRDEFLRISTASGDGRHYCYPHFTCAVDTENIRRVFNDCRDIIQRMHLRQYELL

Ligand: ISO1
SMILES: CC(C)NCC(O)c1ccc(O)c(O)c1

Ligand: PRO1
SMILES: CC(C)NCC(O)COc1cccc2ccccc12
