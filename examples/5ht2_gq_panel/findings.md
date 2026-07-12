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
| Apo (receptor alone, no ligand) | 0.67 | 0.01 | 3 |
| Receptor + ligand, no Gq | 0.79 | 0.02 | 6 |
| Receptor + ligand + Gq heterotrimer | 0.82 | 0.01 | 6 |

Monotonic and consistent across all three receptors: more physiological context (ligand,
then Gq) correlates with higher Boltz confidence, not lower — i.e. the larger, more
complex Gq-bound assemblies are not being predicted less confidently despite being
harder targets computationally (see the MPS chunking work below).

## 2. Affinity predictions

| Ligand | Receptor | Agonist/Antagonist | Binder probability (no Gq / with Gq) | Affinity (pIC50) (no Gq / with Gq) | Read |
|---|---|---|---|---|---|
| Psilocin (PSIL) | 5HT2A | Agonist | 0.97 / 0.97 | 9.15 / 8.96 | Confident binder |
| Risperidone (RISP) | 5HT2A | Antagonist | 1.00 / 0.99 | 12.99 / 12.60 | Confident binder |
| LSD (LSD1) | 5HT2B | Agonist | 0.95 / 0.96 | 11.17 / 11.59 | Confident binder |
| Balovaptan (BALO) | 5HT2B | Antagonist | 0.49 / 0.52 | 9.28 / 9.49 | **Ambiguous** — near coin-flip in both conditions |
| Lorcaserin (LORC) | 5HT2C | Agonist | 0.97 / 0.97 | 9.96 / 9.88 | Confident binder |
| SB-242084 (SB24) | 5HT2C | Antagonist | 0.71 / 0.76 | 10.84 / 11.02 | Binder, moderate confidence |

Balovaptan is the one ligand whose binder-probability call doesn't clear ~0.5 either way,
consistent regardless of Gq co-folding — worth flagging as the weakest affinity call in
the panel rather than a pipeline issue (its confidence/ipTM scores are unremarkable, so
this looks like a genuine borderline prediction, not a broken input).

<div style="display:flex; flex-wrap:wrap; gap:16px; margin:16px 0;">
<img src="confidence_vs_affinity.png?v=3" alt="pIC50 vs confidence score: each point is one target, coloured by confidence tier (green >= 0.7, amber >= 0.5, red below, shown on the colour-bar legend) and shaped by pharmacology (circle = agonist, diamond = antagonist)" style="width:calc(50% - 8px); min-width:260px; height:auto;">
<img src="pic50_vs_binder.png?v=3" alt="Binder probability vs pIC50: coloured by affinity tier (green >= 0.7, amber >= 0.3, red below, shown on the colour-bar legend) and shaped by pharmacology (circle = agonist, diamond = antagonist)" style="width:calc(50% - 8px); min-width:260px; height:auto;">
</div>

Both charts use the same tier colours (now with a colour-bar legend, like the Family x
ligand selectivity heatmap above) and agonist/antagonist shapes as the interactive
dashboard (bullseye/shield icon colours in the Summary table). Neither shows an
agonist/antagonist cluster separate from Gq-bound status -- points scatter by receptor
and ligand, not by pharmacological class, consistent with section 4's statistical result.

## 3. SSE motif shifts: TM6 is the consistent, robust signal

`compare-sse` superposes each receptor's predicted-apo structure onto every ligand-bound
prediction and reports per-motif Ca centroid shift. Restricting to the three
binding-site-adjacent motifs (TM6, TM7, ECL2) and comparing the Gq-bound vs. no-Gq
condition for each receptor/ligand pair (6 pairs total):

<div class="emd-table-wrap"><table class="emd-data-table">
<thead>
<tr><th rowspan="2">Motif</th><th colspan="3">Ca centroid shift</th><th rowspan="2">SD</th><th rowspan="2">Directionally consistent?</th></tr>
<tr><th>No Gq</th><th>Gq</th><th>&Delta; (Gq &minus; no Gq)</th></tr>
</thead>
<tbody>
<tr>
<td data-label="Motif"><strong>TM6</strong></td>
<td data-label="No Gq"><strong>0.74 A</strong></td>
<td data-label="Gq"><strong>2.14 A</strong></td>
<td data-label="Delta"><strong>+1.40 A</strong></td>
<td data-label="SD"><strong>0.30</strong></td>
<td data-label="Directionally consistent?"><strong>6/6 pairs</strong> &mdash; always larger with Gq</td>
</tr>
<tr>
<td data-label="Motif">TM7</td>
<td data-label="No Gq">0.87 A</td>
<td data-label="Gq">1.32 A</td>
<td data-label="Delta">+0.45 A</td>
<td data-label="SD">0.52</td>
<td data-label="Directionally consistent?">5/6 pairs</td>
</tr>
<tr>
<td data-label="Motif">ECL2</td>
<td data-label="No Gq">7.98 A</td>
<td data-label="Gq">12.58 A</td>
<td data-label="Delta">+4.61 A</td>
<td data-label="SD">4.55</td>
<td data-label="Directionally consistent?">5/6 pairs, but highly variable</td>
</tr>
</tbody>
</table></div>

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

## 4. Agonist vs antagonist: no signal beyond Gq co-folding status

Each receptor contributes one matched agonist/antagonist pair (5-HT2A: Psilocin vs.
Risperidone; 5-HT2B: LSD vs. Balovaptan; 5-HT2C: Lorcaserin vs. SB-242084), so agonist and
antagonist can be compared directly, paired by receptor (n=3 pairs), separately for the
Gq-bound and no-Gq conditions (paired t-test). **Declaratively: this method cannot
currently be used to bin a compound as agonist or antagonist** — no metric below reaches
statistical significance at this sample size, and the one metric that comes close (TM6
shift without Gq) stops separating the two classes entirely once Gq is co-folded.

<div class="emd-table-wrap"><table class="emd-data-table">
<thead>
<tr><th rowspan="2">Metric</th><th colspan="4">No Gq</th><th colspan="4">Gq</th></tr>
<tr><th>Agonist</th><th>Antagonist</th><th>&Delta;</th><th>p</th><th>Agonist</th><th>Antagonist</th><th>&Delta;</th><th>p</th></tr>
</thead>
<tbody>
<tr>
<td data-label="Metric">TM6 centroid shift (A)</td>
<td data-label="No Gq Agonist">0.85</td>
<td data-label="No Gq Antagonist">0.63</td>
<td data-label="No Gq Delta">0.23</td>
<td data-label="No Gq p">0.09</td>
<td data-label="Gq Agonist">2.17</td>
<td data-label="Gq Antagonist">2.10</td>
<td data-label="Gq Delta">0.07</td>
<td data-label="Gq p">0.77</td>
</tr>
<tr>
<td data-label="Metric">confidence_score</td>
<td data-label="No Gq Agonist">0.79</td>
<td data-label="No Gq Antagonist">0.78</td>
<td data-label="No Gq Delta">0.01</td>
<td data-label="No Gq p">0.41</td>
<td data-label="Gq Agonist">0.82</td>
<td data-label="Gq Antagonist">0.82</td>
<td data-label="Gq Delta">0.00</td>
<td data-label="Gq p">0.29</td>
</tr>
<tr>
<td data-label="Metric">Binder probability</td>
<td data-label="No Gq Agonist">0.96</td>
<td data-label="No Gq Antagonist">0.73</td>
<td data-label="No Gq Delta">0.23</td>
<td data-label="No Gq p">0.24</td>
<td data-label="Gq Agonist">0.97</td>
<td data-label="Gq Antagonist">0.76</td>
<td data-label="Gq Delta">0.21</td>
<td data-label="Gq p">0.25</td>
</tr>
</tbody>
</table></div>

None of these reach conventional significance at n=3 receptor pairs — a paired t-test with
3 pairs only has power to detect a very large, near-universal effect, so this is "no
evidence of a difference," not "evidence of no difference." The closest thing to a trend
is TM6 shift without Gq: the agonist shows a numerically larger shift than its paired
antagonist in all 3/3 receptors (5-HT2A +0.09 A, 5-HT2B +0.33 A, 5-HT2C +0.27 A) —
consistent in direction but not reaching p < 0.05. That trend disappears once Gq is
co-folded (p = 0.77, and the direction even reverses for 5-HT2A), consistent with
section 3's finding that Gq co-folding, not ligand identity, is the dominant driver of TM6
conformation in this panel. Confidence score and binder probability show no consistent
agonist/antagonist pattern in either condition — Balovaptan's weak binder-probability call
(section 2) looks like a compound-specific effect rather than a systematic antagonist
trait, since the panel's other antagonist, SB-242084, scores much higher (0.71-0.76).

## 5. How the MPS crash and OOM errors were fixed

This campaign's six large Gq-heterotrimer targets (~1250-1280 tokens each) originally
couldn't complete on Apple Silicon at all. Two distinct issues were involved, fixed by
two separate mechanisms:

**The crash (root cause, fixed once, applies to every future campaign):** boltz's
triangular attention computes the whole complex's row-wise QK^T attention-score matrix
in one unchunked matmul, which scales as tokens x heads x tokens x tokens. Past ~1250
residues this single tensor exceeds Apple's MPS backend's tensor-size ceiling and
crashes the process with a SIGSEGV inside PyTorch's internal tiled-bmm fallback. Since
each row's attention is computed independently, chunking the matmul along that row axis
is mathematically exact, not an approximation. BoltzMaker patches this directly into the
installed `boltz` package at `setup` time -- idempotent, and checked against boltz's
known source before patching, so a future `boltz` upgrade that changes this function
can't be silently mis-patched.

**The OOM (a separate, run-specific failure, now recovered automatically):** even with
the crash fixed, running all six large targets back to back in one long-running process
hit a genuine memory-pressure OOM partway through this campaign's own run
(`WARNING: ran out of memory, skipping batch` -- boltz's own clean-fail path, not a
crash) for 2 of the 6 targets, which then took 2 more already-succeeded targets down
with them when the subsequent affinity phase crashed trying to load a missing
intermediate file. `run`/`all` now automatically retries any target that doesn't
complete, isolating every still-incomplete target to its own single-target
`boltz predict` invocation from the first retry onward -- a crashed/OOM'd subprocess's
MPS memory is only released once it fully exits, so isolating to one target per process
is what actually recovered this exact cascade.

Both fixes are permanent, general-purpose BoltzMaker behaviour, not one-off workarounds
for this campaign specifically: the chunking patch applies to any future large complex
on Apple Silicon, and the auto-retry applies to any future OOM, on any campaign.

## 6. Technical notes

- All six large Gq-heterotrimer targets (~1250-1280 tokens each) complete reliably now
  -- see section 5 above for the fix, and `CHANGELOG.md` for the full technical detail.
- No genuinely apo experimental structure exists for any of the three receptors (checked
  entity-by-entity across all 59 deposited structures) — the apo reference used here is a
  Boltz prediction of the receptor alone, not an experimental structure. The SSE findings
  above should be read as *relative* shifts against a computational reference, not against
  ground truth.

<h2>📊 Interactive dashboard</h2>
<p>Full confidence/affinity charts, per-target binding-site views, ligand structures, and the complete SSE motif-shift tables are embedded below &mdash; or open it directly: <a href="boltz_dashboard.html" target="_blank" rel="noopener noreferrer">boltz_dashboard.html &#8599;</a></p>
<div style="margin:16px 0;">
<iframe id="boltz-dashboard-iframe" src="boltz_dashboard.html" title="5ht2_gq_panel interactive dashboard" loading="lazy" style="width:100%;height:1200px;border:1px solid #dde4ed;border-radius:8px;display:block;overflow:hidden;"></iframe>
</div>
<script>
(function () {
  var iframe = document.getElementById('boltz-dashboard-iframe');
  if (!iframe) return;
  window.addEventListener('message', function (e) {
    if (e.data && e.data.source === 'boltzmaker-dashboard' && typeof e.data.height === 'number') {
      iframe.style.height = e.data.height + 'px';
    }
  });
})();
</script>
