load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/5ht2_gq_panel/boltz_cif/H2BAP_model_0.cif, apo
load /Users/dellboy/Documents/Vibe_Coding/BoltzMaker/examples/5ht2_gq_panel/boltz_cif/H2BNG_BALO_model_0.cif, holo
hide everything
show cartoon, apo or holo
color grey80, apo
color skyblue, holo
align apo and chain H2BAP, holo and chain H2BNG
select motif_ECL2, (apo or holo) and resi 4+10+207+208+209+303+305+410+422+423+426+463
color red, motif_ECL2
label holo and resi 305 and name CA, "ECL2 (11.2 A)"
select motif_ICL3, (apo or holo) and resi 22+28+38+47+198+200
color orange, motif_ICL3
label holo and resi 47 and name CA, "ICL3 (18.2 A)"
select motif_TM1, (apo or holo) and resi 53+54+55+56+57+58+59+60+61+62+64+65+66+67+68+69+70+71+72+73+74+75+76+77+78+79+80+81+82
color yellow, motif_TM1
select motif_ICL1, (apo or holo) and resi 83+84+85+86
color green, motif_ICL1
select motif_TM2, (apo or holo) and resi 87+88+89+90+91+92+93+94+95+96+97+98+99+100+101+102+103+104+105+107+108+109+110+111+112+113+114+115+116+117
color cyan, motif_TM2
select motif_ECL1, (apo or holo) and resi 120+121+122+123
color blue, motif_ECL1
label holo and resi 122 and name CA, "ECL1 (2.3 A)"
select motif_TM3, (apo or holo) and resi 124+125+126+127+128+129+130+131+132+133+134+135+136+137+138+139+140+141+142+143+144+145+146+147+148+149+150+151+152+153+154+155+156+157+158+159
color purple, motif_TM3
select motif_ICL2, (apo or holo) and resi 160+161+162+163+164+165+166+167+436+443+450+479+481
color magenta, motif_ICL2
label holo and resi 166 and name CA, "ICL2 (8.2 A)"
select motif_TM4, (apo or holo) and resi 168+169+170+171+172+173+174+175+176+177+178+179+180+181+182+183+184+185+186+187+188+189+190+191+192+193+194
color salmon, motif_TM4
select motif_TM5, (apo or holo) and resi 214+215+216+217+218+219+220+221+222+223+224+226+227+228+229+230+231+232+233+234+235+236+237+238+239+240+241+242+243+244+245+246+247+248+249+250+251+252+253+254+255
color olive, motif_TM5
select motif_TM6, (apo or holo) and resi 313+314+315+316+317+318+319+320+321+322+323+324+325+326+327+328+329+330+331+332+333+334+335+336+337+338+339+340+341+342+343+344+345+346+347+348+349+350
color teal, motif_TM6
select motif_TM7, (apo or holo) and resi 354+355+356+357+358+359+360+361+362+363+364+365+366+367+368+369+370+371+372+373+374+375+376+377+378+379+380+381+382+383
color violet, motif_TM7
select motif_H8, (apo or holo) and resi 384+385+386+387+388+389+390+391+392+393+394+395
color brown, motif_H8
select motif_ECL3, (apo or holo) and resi 397
color pink, motif_ECL3
set label_size, 16
set label_color, black
zoom apo or holo
