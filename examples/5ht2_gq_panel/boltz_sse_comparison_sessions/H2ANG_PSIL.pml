load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/5ht2_gq_panel/boltz_cif/H2AAP_model_0.cif, apo
load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/5ht2_gq_panel/boltz_cif/H2ANG_PSIL_model_0.cif, holo
hide everything
show cartoon, apo or holo
color grey80, apo
color skyblue, holo
align apo and chain H2AAP, holo and chain H2ANG
select motif_ICL2, (apo or holo) and resi 20+56+61+180+181+182+183+184+185+186+187+299+442+447+449
color red, motif_ICL2
label holo and resi 184 and name CA, "ICL2 (14.6 A)"
select motif_TM1, (apo or holo) and resi 69+70+71+72+73+74+75+76+77+78+79+80+81+82+83+84+85+86+87+88+89+90+91+92+93+94+95+96+97+98+99+100+101+102
color orange, motif_TM1
select motif_ICL1, (apo or holo) and resi 103+104+105+106
color yellow, motif_ICL1
select motif_TM2, (apo or holo) and resi 107+108+109+110+111+112+113+114+115+116+117+118+119+120+121+122+123+124+125+127+128+129+130+131+132+133+134+135+136+137+138
color green, motif_TM2
select motif_ECL1, (apo or holo) and resi 140+141+142+143
color cyan, motif_ECL1
select motif_TM3, (apo or holo) and resi 144+145+146+147+148+149+150+151+152+153+154+155+156+157+158+159+160+161+162+163+164+165+166+167+168+169+170+171+172+173+174+175+176+177+178+179
color blue, motif_TM3
select motif_TM4, (apo or holo) and resi 188+189+190+191+192+193+194+195+196+197+198+199+200+201+202+203+204+205+206+207+208+209+210+211+212+213+214+215+216+217
color purple, motif_TM4
select motif_H8loop, (apo or holo) and resi 222
color magenta, motif_H8loop
select motif_ECL2, (apo or holo) and resi 227+228+229+284+290+293+305+402+404+405+434+457+462+463+467+468
color salmon, motif_ECL2
label holo and resi 404 and name CA, "ECL2 (18.3 A)"
select motif_ECL3, (apo or holo) and resi 230
color olive, motif_ECL3
select motif_TM5, (apo or holo) and resi 231+232+233+234+235+236+237+238+239+240+241+243+244+245+246+247+248+249+250+251+252+253+254+255+256+257+258+259+260+261+262+263+264+265+266+267+268+269+270+271+272
color teal, motif_TM5
select motif_TM6, (apo or holo) and resi 312+313+314+315+316+317+318+319+320+321+322+323+324+325+326+327+328+329+330+331+332+333+334+335+336+337+338+339+340+341+342+343+344+345+346+347+348+349
color violet, motif_TM6
label holo and resi 331 and name CA, "TM6 (2.5 A)"
select motif_TM7, (apo or holo) and resi 354+355+356+357+358+359+360+361+362+363+364+365+366+367+368+369+370+371+372+373+374+375+376+377+378+379+380+381+382+383
color brown, motif_TM7
select motif_H8, (apo or holo) and resi 384+385+386+387+388+389+390+391+392+393+394+395+396+397
color pink, motif_H8
set label_size, 16
set label_color, black
zoom apo or holo
