load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/egfr_covalent/reference/1m14_egfr_apo.pdb, apo
load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/egfr_covalent/boltz_cif/EGFR_FRAG1_model_0.cif, holo
hide everything
show cartoon, apo or holo
color grey80, apo
color skyblue, holo
align apo and chain A, holo and chain EGFR
select motif_catalytic_Lys, (apo or holo) and resi 50
color red, motif_catalytic_Lys
select motif_alphaC_Glu, (apo or holo) and resi 67
color orange, motif_alphaC_Glu
select motif_gatekeeper, (apo or holo) and resi 95
color yellow, motif_gatekeeper
select motif_hinge, (apo or holo) and resi 96+97+98
color green, motif_hinge
select motif_catalytic_loop, (apo or holo) and resi 140+141+142
color cyan, motif_catalytic_loop
select motif_DFG, (apo or holo) and resi 160+161+162
color blue, motif_DFG
select motif_pocket_scaffold, (apo or holo) and resi 21+22+23+24+25+26+27+28+29+30+31+32+33+47+48+49+51+52+63+64+65+66+68+69+70+71+72+73+74+75+77+78+79+80+81+82+83+84+85+92+93+94+99+100+101+102+103+104+105+106+107+108+109+132+133+134+135+136+137+138+139+143+144+145+146+147+148+149+150+158+159+163+164
color purple, motif_pocket_scaffold
set label_size, 16
set label_color, black
zoom apo or holo
