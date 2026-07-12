load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/5ht2_gq_panel/boltz_cif/H2CAP_model_0.cif, apo
load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/5ht2_gq_panel/boltz_cif/5HT2C_SB24_model_0.cif, holo
hide everything
show cartoon, apo or holo
color grey80, apo
color skyblue, holo
align apo and chain H2CAP, holo and chain 5HT2C
select motif_ICL3, (apo or holo) and resi 14+298
color red, motif_ICL3
label holo and resi 298 and name CA, "ICL3 (23.7 A)"
select motif_ECL2, (apo or holo) and resi 31+32+207+208+209+266+267+268+270+277
color orange, motif_ECL2
label holo and resi 266 and name CA, "ECL2 (27.5 A)"
select motif_ICL2, (apo or holo) and resi 41+159+160+161+162+163+164+165+166+392+395+397+399+401+405+409+410+411+415+423
color yellow, motif_ICL2
label holo and resi 395 and name CA, "ICL2 (19.3 A)"
select motif_TM1, (apo or holo) and resi 54+55+56+57+58+59+60+61+62+63+64+65+66+67+68+69+70+71+72+73+74+75+76+77+78+79+80+81
color green, motif_TM1
select motif_ICL1, (apo or holo) and resi 82+83+84+85
color cyan, motif_ICL1
label holo and resi 84 and name CA, "ICL1 (2.3 A)"
select motif_TM2, (apo or holo) and resi 86+87+88+89+90+91+92+93+94+95+96+97+98+99+100+101+102+103+104+106+107+108+109+110+111+112+113+114+115+116+117
color blue, motif_TM2
select motif_ECL1, (apo or holo) and resi 119+120+121+122
color purple, motif_ECL1
label holo and resi 121 and name CA, "ECL1 (2.2 A)"
select motif_TM3, (apo or holo) and resi 123+124+125+126+127+128+129+130+131+132+133+134+135+136+137+138+139+140+141+142+143+144+145+146+147+148+149+150+151+152+153+154+155+156+157+158
color magenta, motif_TM3
label holo and resi 141 and name CA, "TM3 (2.1 A)"
select motif_TM4, (apo or holo) and resi 167+168+169+170+171+172+173+174+175+176+177+178+179+180+181+182+183+184+185+186+187+188+189+190+191+192+193+194+195+196
color salmon, motif_TM4
label holo and resi 182 and name CA, "TM4 (2.2 A)"
select motif_TM5, (apo or holo) and resi 211+212+213+214+215+216+217+218+219+220+221+223+224+225+226+227+228+229+230+231+232+233+234+235+236+237+238+239+240+241+242+243+244+245+246+247+248+249+250
color olive, motif_TM5
label holo and resi 231 and name CA, "TM5 (2.8 A)"
select motif_TM6, (apo or holo) and resi 300+301+302+303+304+305+306+307+308+309+310+311+312+313+314+315+316+317+318+319+320+321+322+323+324+325+326+327+328+329+330+331+332+333+334+335+336+337
color teal, motif_TM6
label holo and resi 319 and name CA, "TM6 (2.6 A)"
select motif_TM7, (apo or holo) and resi 342+343+344+345+346+347+348+349+350+351+352+353+354+355+356+357+358+359+360+361+362+363+364+365+366+367+368+369+370+371
color violet, motif_TM7
select motif_H8, (apo or holo) and resi 372+373+374+375+376+377+378+379+380+381+382+383+384+385
color brown, motif_H8
label holo and resi 379 and name CA, "H8 (3.4 A)"
set label_size, 16
set label_color, black
zoom apo or holo
