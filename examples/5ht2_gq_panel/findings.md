# Findings: 5-HT2A/2B/2C Gq-coupling panel

Campaign: `examples/5ht2_gq_panel/boltz_input.md` — 15 targets (12 ligand-bound + 3
predicted-apo), run end to end via `python3 BoltzMaker.py all` on Apple Silicon (M1 Max).
Full per-target metrics: [boltz_summary.csv](boltz_summary.csv),
[boltz_dashboard.html](boltz_dashboard.html); SSE motif-shift data:
[boltz_sse_comparison.csv](boltz_sse_comparison.csv).

## Summary

All 15 targets completed successfully with no crashes. Structural confidence increases
monotonically with co-folding context (apo < receptor-alone < receptor+Gq), affinity
predictions are directionally sensible for 5 of 6 ligands, and the TM6 outward-swing
signal — the textbook hallmark of GPCR activation — is reproduced consistently across
all three receptors and both ligands per receptor.

## 1. Structural confidence tracks co-folding context

| Condition | Mean confidence_score | SD | n |
|---|---|---|---|
| Apo (receptor alone, no ligand) | 0.669 | 0.010 | 3 |
| Receptor + ligand, no Gq | 0.789 | 0.016 | 6 |
| Receptor + ligand + Gq heterotrimer | 0.821 | 0.011 | 6 |

Monotonic and consistent across all three receptors: more physiological context (ligand,
then Gq) correlates with higher Boltz confidence, not lower — i.e. the larger, more
complex Gq-bound assemblies are not being predicted less confidently despite being
harder targets computationally (see the MPS chunking work below).

## 2. Affinity predictions

| Ligand | Receptor | Binder probability (no Gq / with Gq) | Read |
|---|---|---|---|
| Risperidone (RISP) | 5HT2A | 0.997 / 0.991 | Confident binder |
| Psilocin (PSIL) | 5HT2A | 0.972 / 0.974 | Confident binder |
| LSD (LSD1) | 5HT2B | 0.946 / 0.964 | Confident binder |
| Balovaptan (BALO) | 5HT2B | 0.487 / 0.518 | **Ambiguous** — near coin-flip in both conditions |
| Lorcaserin (LORC) | 5HT2C | 0.967 / 0.970 | Confident binder |
| SB-242084 (SB24) | 5HT2C | 0.708 / 0.764 | Binder, moderate confidence |

Balovaptan is the one ligand whose binder-probability call doesn't clear ~0.5 either way,
consistent regardless of Gq co-folding — worth flagging as the weakest affinity call in
the panel rather than a pipeline issue (its confidence/ipTM scores are unremarkable, so
this looks like a genuine borderline prediction, not a broken input).

## 3. SSE motif shifts: TM6 is the consistent, robust signal

`compare-sse` superposes each receptor's predicted-apo structure onto every ligand-bound
prediction and reports per-motif Ca centroid shift. Restricting to the three
binding-site-adjacent motifs (TM6, TM7, ECL2) and comparing the Gq-bound vs. no-Gq
condition for each receptor/ligand pair (6 pairs total):

| Motif | Mean centroid-shift delta (Gq − no Gq) | SD | Directionally consistent? |
|---|---|---|---|
| **TM6** | **+1.40 A** | **0.30** | **6/6 pairs** — always larger with Gq |
| TM7 | +0.45 A | 0.52 | 5/6 pairs |
| ECL2 | +4.61 A | 4.55 | 5/6 pairs, but highly variable |

TM6 is the clean result: every single receptor/ligand combination shows a larger TM6
centroid shift when Gq is co-folded, with a tight spread (0.30 A SD on a ~1.4 A mean
effect) — exactly the expected GPCR activation mechanism (TM6 swings outward to open the
intracellular G-protein-binding cavity), reproduced independently across three distinct
receptors and six different ligands. TM6's axis-rotation angle, by contrast, does **not**
show the same clean pattern (it decreases with Gq for 5-HT2A but increases for 5-HT2B/2C),
so centroid shift — not rotation angle — is the reliable metric here.

ECL2 shows a much larger mean effect but with SD exceeding the mean, driven mostly by two
large values in 5-HT2C (9.3 A and 10.6 A delta, vs. 1-3 A for the other two receptors).
ECL2 is a long, flexible extracellular loop with no fixed secondary structure across the
three receptors' generic-numbering assignment, so both genuine biological flexibility and
prediction/superposition noise are plausible contributors — this is reported as an
observation worth a closer look (e.g. inspecting the actual predicted loop conformations
in PyMOL via `boltz_sse_comparison_sessions/`), not a confirmed finding on the same
footing as TM6.

## 4. Technical notes

- This campaign was the one that originally exposed BoltzMaker's Apple-Silicon MPS
  large-complex crash (unchunked triangular-attention matmul exceeding MPS's tensor-size
  ceiling past ~1250 residues) — now fixed; all six large Gq-heterotrimer targets
  (~1250-1280 tokens each) complete reliably. See `CHANGELOG.md` for the fix and
  `run`/`all`'s automatic per-target retry behaviour, which recovered a transient OOM
  during this campaign's own run without manual intervention.
- No genuinely apo experimental structure exists for any of the three receptors (checked
  entity-by-entity across all 59 deposited structures) — the apo reference used here is a
  Boltz prediction of the receptor alone, not an experimental structure. The SSE findings
  above should be read as *relative* shifts against a computational reference, not against
  ground truth.
