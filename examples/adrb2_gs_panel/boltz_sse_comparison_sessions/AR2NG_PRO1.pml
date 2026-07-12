load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/adrb2_gs_panel/reference/2rh1_adrb2_apo.pdb, apo
load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/adrb2_gs_panel/boltz_cif/AR2NG_PRO1_model_0.cif, holo
hide everything
show cartoon, apo or holo
color grey80, apo
color skyblue, holo
align apo and chain A, holo and chain AR2NG
select motif_TM1, (apo or holo) and resi 29+30+31+32+33+34+35+36+37+38+39+40+41+42+43+44+45+46+47+48+49+50+51+52+53+54+55+56+57+58+59+60+61
color red, motif_TM1
select motif_ICL1, (apo or holo) and resi 62+63+64+65
color orange, motif_ICL1
select motif_TM2, (apo or holo) and resi 66+67+68+69+70+71+72+73+74+75+76+77+78+79+80+81+82+83+84+86+87+88+89+90+91+92+93+94+95+96+97
color yellow, motif_TM2
select motif_ECL1, (apo or holo) and resi 98+99+100+101
color green, motif_ECL1
select motif_TM3, (apo or holo) and resi 102+103+104+105+106+107+108+109+110+111+112+113+114+115+116+117+118+119+120+121+122+123+124+125+126+127+128+129+130+131+132+133+134+135+136+137
color cyan, motif_TM3
select motif_ICL2, (apo or holo) and resi 138+139+140+141+142+143+144+145
color blue, motif_ICL2
label holo and resi 142 and name CA, "ICL2 (5.6 A)"
select motif_TM4, (apo or holo) and resi 146+147+148+149+150+151+152+153+154+155+156+157+158+159+160+161+162+163+164+165+166+167+168+169+170+171+172
color purple, motif_TM4
select motif_H8loop, (apo or holo) and resi 186+302
color magenta, motif_H8loop
select motif_ECL2, (apo or holo) and resi 191+192+193
color salmon, motif_ECL2
select motif_TM5, (apo or holo) and resi 196+197+198+199+200+201+202+203+204+205+206+208+209+210+211+212+213+214+215+216+217+218+219+220+221+222+223+224+225+226+227+228+229+230
color olive, motif_TM5
select motif_ECL3, (apo or holo) and resi 239
color teal, motif_ECL3
label holo and resi 239 and name CA, "ECL3 (24.8 A)"
select motif_TM6, (apo or holo) and resi 263+264+265+266+267+268+269+270+271+272+273+274+275+276+277+278+279+280+281+282+283+284+285+286+287+288+289+290+291+292+293+294+295+296+297+298+299
color violet, motif_TM6
label holo and resi 281 and name CA, "TM6 (3.1 A)"
select motif_TM7, (apo or holo) and resi 304+305+306+307+308+309+310+311+312+313+314+315+316+317+318+319+320+321+322+323+324+325+326+327+328
color brown, motif_TM7
select motif_H8, (apo or holo) and resi 329+330+331+332+333+334+335+336+337+338+339+340+341
color pink, motif_H8
set label_size, 16
set label_color, black
zoom apo or holo
