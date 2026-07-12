# 🧬 BoltzMaker

> **BoltzMaker: Boltz2 campaign-scale structure and affinity prediction, binding analysis, and run control, orchestrated end to end from a single spec file.**

![python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white) ![boltz](https://img.shields.io/badge/boltz-2-00897B) ![plip](https://img.shields.io/badge/PLIP-interactions-9b51e0) ![pymol](https://img.shields.io/badge/PyMOL-visualisation-ff6900) ![rdkit](https://img.shields.io/badge/RDKit-cheminformatics-00d084) ![plotly](https://img.shields.io/badge/Plotly-charts-3F4F75?logo=plotly&logoColor=white) ![3dmoljs](https://img.shields.io/badge/3Dmol.js-3D%20viewer-fcb900) ![pytest](https://img.shields.io/badge/pytest-tested-0A9EDC?logo=pytest&logoColor=white) ![licence](https://img.shields.io/badge/licence-MIT-467FF7) ![author](https://img.shields.io/badge/author-Marc%20C.%20Deller%2C%20D.Phil.-1C244B)

<table>
<tr>
<td>🌐 <b>Website</b></td><td><a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">marcdeller.com</a></td>
<td>✉️ <b>Contact</b></td><td><a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a></td>
<td>🐙 <b>GitHub</b></td><td><a href="https://github.com/bellcheddar/BoltzMaker" target="_blank" rel="noopener noreferrer">bellcheddar/BoltzMaker</a></td>
</tr>
</table>

---

A single script that manages a Boltz-2 batch campaign end to end: parse a `boltz_input.md`
spec, generate the per-target Boltz YAML files, preflight the environment and inputs, run
`boltz predict` with a live progress bar (with resume support), and analyze the results into
a CSV, an XLSX workbook, and an HTML dashboard -- optionally enriched with real
protein-ligand interaction analysis via [cif2plip](https://github.com/bellcheddar/cif2plip).

Why it matters: hand-running a Boltz-2 campaign means writing dozens of near-identical YAML
files by hand, remembering the right CLI flags for the hardware you're on, and manually
digging through prediction JSONs afterwards, all repetitive, error-prone steps that don't
need a human. BoltzMaker turns a single annotated spec into the full pipeline: generated
inputs, environment/input validation (including ligand-chemistry sanity checks --
undefined stereocentres, ambiguous protonation states, stray salts -- so bad input
chemistry is caught before hours of compute, not silently mispredicted), a monitored run
with Mac-safe memory defaults, and a ready-to-read report. It is useful for: structural
biologists and drug-discovery scientists
running Boltz-2 structure/affinity panels (single targets, covalent-linkage studies, or
multi-chain SAR/selectivity campaigns) who want a repeatable, resumable, well-documented
pipeline instead of a pile of hand-edited scripts.

Don't want to hand-write the spec at all? `BoltzMaker.py new` interviews you in plain
English -- proteins, partners, ligands, and the constraint sentences -- and writes a
valid `boltz_input.md` for you. If you've already got a reference co-crystal or homology
structure for a protein, it can even suggest pocket-contact residues automatically,
remapped onto your target's own numbering via sequence alignment, instead of you reading
them off a structure viewer by hand.

BoltzMaker grew out of five smaller, single-purpose tools written earlier:
[generate_yaml](https://github.com/bellcheddar/generate_yaml) for building the input
YAMLs, [simple-zsh-script-to-run-boltz2](https://github.com/bellcheddar/simple-zsh-script-to-run-boltz2)
for driving the actual `boltz predict` runs, [analyze-boltz2-results](https://github.com/bellcheddar/analyze-boltz2-results)
for the post-run analysis, [cif2plip](https://github.com/bellcheddar/cif2plip) for
protein-ligand interaction profiling, and [smiles2grid](https://github.com/bellcheddar/smiles2grid)
for rendering a ligand set into a boxed grid of 2D structures. BoltzMaker consolidates
all five into one spec-driven pipeline sharing a single campaign format, so the same
input file drives every stage instead of juggling separate scripts and re-typing target
names between them.

And yes, the name is a nod to [Boltmaker](https://www.timothytaylor.co.uk/beer/boltmaker),
Timothy Taylor's Champion Beer of Britain and one of the author's favourites.

See [CHANGELOG.md](CHANGELOG.md) for what's changed recently, and
[PROJECT_PLAN.md](PROJECT_PLAN.md) for the roadmap behind the To-Do list below.

## 🧩 Architecture

```
+----------------+     +----------+     +-----------+     +-----+     +---------+
| boltz_input.md | --> | generate | --> | preflight | --> | run | --> | analyze |
+----------------+     +----------+     +-----------+     +-----+     +---------+
```

| Stage | Command | Produces |
|---|---|---|
| 1. Input | -- | `boltz_input.md` -- the family x partners x ligand DSL spec |
| 2. Generate | `generate` | `boltz_yamls/*.yaml` + manifest |
| 3. Preflight | `preflight` | PASS/WARN/FAIL: CLI, GPU/MPS, disk, iCloud, YAML/SMILES/chain-id/chemistry, memory |
| 4. Predict | `run` | `boltz predict` -> `boltz_output/`, live progress + memory monitor, resumable |
| 5. Analyze | `analyze` | `boltz_summary.csv`/`.xlsx`, `boltz_dashboard.html`, `boltz_cif/`, plus interaction files if `setup-plip` has run, plus `boltz_sse_comparison.csv`/`.html` for any family with an `Apo structure:` set (see **compare-sse** below) |

Each stage reads only the manifest + files the previous stage wrote, so any stage can be
re-run on its own (`generate`, `preflight`, `run`, or `analyze` individually) without
repeating the others: `all` simply chains all four.

## 🔧 One-time setup

```sh
python3 BoltzMaker.py setup
```

Creates a dedicated `.venv` (Python 3.12: boltz pins `numpy<2.0`, which has no prebuilt
wheel for newer Pythons) next to `BoltzMaker.py` and installs `boltz`, `rich`, `pandas`,
`openpyxl`, `pyyaml`, `rdkit`, `matplotlib`, `psutil`, `scipy`, `gemmi`, `biopython`,
`plotly`, `reportlab`, and `requests` into it. This pulls PyTorch (~2-3 GB) and, the first time
`boltz predict` actually runs, Boltz downloads several GB of model weights over the
network. Every other command below transparently relaunches itself under this managed
environment, so you can keep
invoking the script with whatever `python3` is on your PATH.

Re-run with `--force` to recreate the venv from scratch, or `-y/--yes` to skip the download
confirmation prompt.

### Optional: `setup-plip` (protein-ligand interaction analysis)

```sh
python3 BoltzMaker.py setup-plip
```

Entirely optional and separate from the venv above. Builds a `.plip_env` (via a
self-downloaded [micromamba](https://micro.mamba.pm), ~1-1.5GB, mostly PyMOL's own Qt/
Cairo/HDF5 dependencies) and vendors a pinned commit of
[cif2plip](https://github.com/bellcheddar/cif2plip), which converts a Boltz ModelCIF into
a strict PDB and runs [PLIP](https://github.com/pharmai/plip) on it for real
protein-ligand interaction fingerprints (H-bonds, salt bridges, pi-stacking, halogen
bonds, metal coordination, etc.). A conda-forge-based environment is used deliberately
here rather than pip: PLIP requires OpenBabel and PyMOL as in-process Python imports (not
subprocess calls), and empirically, `plip`'s own installer forces a broken from-source
OpenBabel build unless a working OpenBabel is already present, while the standalone PyPI
`pymol-open-source` wheel has a hardcoded broken library path on this platform --
conda-forge's builds have neither problem.

If `.plip_env` isn't present, everything below degrades gracefully: `analyze` skips
interaction analysis (dashboard looks exactly as it did before this feature), and the `new`
wizard simply doesn't ask about reference structures. Nothing else in BoltzMaker requires
it. `preflight`'s `plip_env` check always reports which mode you're in.

### Optional: `mkdssp`/`dssp` (for `compare-sse`'s SSE-boundary-shift metric)

Not bundled or installed by any BoltzMaker command -- a small external binary you may
already have (`brew install dssp` on macOS, or `conda install -c salilab dssp`). Only
needed for one specific `compare-sse` metric (secondary-structure-element boundary
shift, used when a structure has no deposited HELIX/SHEET records -- true for every
Boltz-predicted structure). Every other `compare-sse` metric works without it.

## 🧪 Examples

Four entirely public-domain campaigns in `examples/`, run any of them with
`python3 BoltzMaker.py all examples/<name>/boltz_input.md`:

| Example | Demonstrates | Dashboard | Input |
|---|---|---|---|
| `t4_lysozyme` | One protein (T4 lysozyme L99A, UniProt P00720) + one ligand (benzene). No partners, no pocket_contacts. The minimal shape; smallest/fastest smoke test. | [boltz_dashboard.html](https://bellcheddar.github.io/BoltzMaker/examples/t4_lysozyme/boltz_dashboard.html) | [boltz_input.md](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/t4_lysozyme/boltz_input.md) |
| `egfr_covalent` | EGFR kinase domain (UniProt P00533) + a generic covalent fragment, linked via `bond_constraints` at Cys797. Demonstrates covalent-linkage modelling. | [boltz_dashboard.html](https://bellcheddar.github.io/BoltzMaker/examples/egfr_covalent/boltz_dashboard.html) | [boltz_input.md](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/egfr_covalent/boltz_input.md) |
| `adrb2_gs_panel` | Beta-2 adrenergic receptor (UniProt P07550), agonist vs antagonist, as two separate `Protein:` blocks sharing one sequence rather than one family crossed with both ligands: the agonist target co-folds a Gs alpha partner (UniProt P63092), the antagonist target doesn't (Gs only forms a stable complex with the active, agonist-bound receptor in reality -- co-folding it with the antagonist too made Boltz predict a near-identical active-like fold for both, 0.38 Angstrom apart; splitting them out gets a real conformational difference, 1.28 Angstrom apart, TM6 shift roughly doubled for the agonist). Demonstrates `compare-sse` (see below) and why co-folded partners should match each ligand's real biology, not just get crossed with everything. | [boltz_dashboard.html](https://bellcheddar.github.io/BoltzMaker/examples/adrb2_gs_panel/boltz_dashboard.html) | [boltz_input.md](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/adrb2_gs_panel/boltz_input.md) |
| `5ht2_gq_panel` | Three serotonin receptors (5-HT2A/2B/2C, UniProt P28223/P41595/P28335), each with a real agonist/antagonist pair (Psilocin/Risperidone, LSD/Balovaptan, Lorcaserin/SB-242084), each predicted both with and without the Gq heterotrimer (GNAQ+GNB1+GNG2) co-folded -- a 3x2x2 panel, plus a native ligand-free (`Ligands: none`) apo target per receptor, used as each receptor's `compare-sse` reference since no genuinely apo experimental structure exists for any of the three (checked entity-by-entity across all 59 deposited structures). Demonstrates `Ligands: none`, a larger size-heterogeneous campaign in one manifest, Apple Silicon MPS support for large multi-chain complexes (see below), and `compare-sse` against a *predicted* rather than experimental apo reference -- TM6 centroid shift comes out consistently larger for the Gq-bound targets than their no-Gq counterparts across all three receptors, the expected activation signal (see [findings.md](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/5ht2_gq_panel/findings.md) for the full statistical write-up). | [boltz_dashboard.html](https://bellcheddar.github.io/BoltzMaker/examples/5ht2_gq_panel/boltz_dashboard.html) | [boltz_input.md](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/5ht2_gq_panel/boltz_input.md) |

**Verified end-to-end** (`generate` -> `preflight` -> real `boltz predict` -> `analyze`,
including cif2plip interaction analysis) on an Apple M1 Max, 64GB:

| Example | Targets | Total time | Result |
|---|---|---|---|
| `t4_lysozyme` | 1 | 3m 16s | confidence 0.98, pIC50 8.9, 7 hydrophobic contacts matching the known L99A cavity residues |
| `egfr_covalent` | 1 | 5m 31s | confidence 0.92, covalent Cys797 SG-to-fragment bond confirmed at 1.75 Angstrom |
| `adrb2_gs_panel` | 2 | 1h 28m 36s (`ADRB2_ISO1`, agonist+Gs) + 25m 6s (`AR2NG_PRO1`, antagonist alone) | confidence 0.79 (`ADRB2_ISO1`) / 0.83 (`AR2NG_PRO1`) |
| `5ht2_gq_panel` | 15 | 9 small targets (apo + receptor-alone) ~4-5m each; 6 large receptor+Gq-heterotrimer complexes ~43-48m each | All 15 completed successfully (12 ligand-bound + 3 apo); confidence 0.66-0.81, iPTM up to 0.99 for the ligand-bound complexes |

Run time scales with complex size, not just target count: `ADRB2_ISO1`'s two-chain
receptor+Gs-partner complex took disproportionately longer than the single-chain
examples, since attention-style operations scale worse than linearly with sequence
length -- confirmed directly by `AR2NG_PRO1` (same receptor, no partner) finishing in a
fraction of the time. One contributing factor on Apple Silicon specifically:
`torch.linalg.svd` (used in the diffusion step) has no MPS implementation and silently
falls back to CPU -- worth budgeting for on large multi-chain campaigns.

`5ht2_gq_panel`'s six large 4-chain receptor+Gq-heterotrimer targets (~1250-1280 tokens)
originally crashed on Apple Silicon: boltz's triangular attention computes the full
row-wise QK^T score matrix for the whole complex in one unchunked matmul, which exceeds
MPS's single-tensor size ceiling past roughly 1250 residues and crashes the process
inside PyTorch's internal tiled-bmm fallback. Each row's attention is independent, so
chunking along that axis is exact, not an approximation -- `setup` now patches this
directly into the installed `boltz` package (idempotent, and checked against boltz's
exact source so a future upgrade can't be silently mis-patched). `run` also wraps
`boltz predict` with `caffeinate` automatically (macOS only, silently skipped if
unavailable) as general sleep-prevention hygiene for long GPU jobs. All 15
`5ht2_gq_panel` targets, including the six large complexes, now complete successfully --
see [CHANGELOG.md](CHANGELOG.md) for the fix in full.

## 🧭 boltz_input.md format

Plain labelled text -- no markdown, no YAML, no brackets, no quoting. One rule: blocks
are `Label: value` lines with a blank line between them; comments start with `#`. Field
names are plain English (`Output folder`, `Predict affinity`, `Pocket contact`) rather
than Boltz-internal snake_case. Don't want to hand-write it at all? Run `python3
BoltzMaker.py new` and answer plain questions instead -- see **Commands** below.

The format has two layers: a **family x partners x ligand cross-product** (the ergonomic
layer: write each protein/ligand once, get every combination as a separate target), and
standalone **constraint sentences** for the two/three-ended relationships (covalent
bonds, distance constraints) that don't fit inside one block -- each names the protein it
belongs to and can be written anywhere in the file.

```
Settings:
Output folder: ./boltz_yamls    # where generated per-target YAMLs are written
Predict affinity: no            # off by default -- it's a heavier prediction pass

Protein: RECP1                  # short name, MAX 5 CHARACTERS (Boltz stores chain names
                                # in a fixed 5-char field internally and silently
                                # truncates longer ones, which then crashes later with a
                                # confusing error -- `preflight` catches this for you).
                                # Also names the output file: {protein}_{ligand}.yaml
Sequence: MDILC...              # required
Partners: CHNX, CHNY            # optional: co-folded chains, defined as their own
                                # Partner: blocks below
# Ligands: LIG1, LIG3           # optional: restrict this protein to a ligand subset
                                # (default: crossed with every ligand below)
# Ligands: none                 # optional: ligand-free (apo) target -- no ligand entity,
                                # no pocket constraint, no affinity property, whatever
                                # `Predict affinity:` says. Stem is just the protein name
                                # (e.g. `RECP1.yaml`, not `RECP1_LIG1.yaml`), runs through
                                # the same generate/preflight/run/analyze pipeline and the
                                # same staged `boltz predict` batch as every other target.
# Modifications: SEP:5          # optional: CCD:position tokens for modified residues
                                # (e.g. phosphoserine)
# Cyclic: yes                   # optional: cyclic polymer (e.g. a cyclic peptide)
# MSA: empty                    # optional: path to a precomputed MSA, or "empty" for
                                # single-sequence mode (skip MSA generation)
# Templates: reference_structure.cif
                                # optional: structural template file(s), applied to all
                                # protein chains (no per-chain mapping -- hand-edit the
                                # generated YAML for that rarer case)
# Apo structure: reference/apo.pdb
                                # optional: a reference apo/unbound structure, used only
                                # by `compare-sse` (see below), never by generate/run.
                                # No genuinely apo experimental structure? Predict one:
                                # give another `Protein:` block the same `Sequence:` and
                                # `Ligands: none` (see above), run the campaign once, then
                                # point `Apo structure:` at its output in `boltz_cif/`.
# Apo chain: A                 # optional: explicit chain id in the apo structure above
                                # (omit to auto-detect via sequence identity)
# Family type: gpcr            # optional: gpcr / kinase / auto (default) -- selects
                                # `compare-sse`'s motif annotator
# Group: RECP1                  # optional: shared display/report name for multiple
                                # `Protein:` blocks that are the same underlying receptor
                                # (e.g. with/without a partner, or a predicted apo
                                # variant) -- defaults to this block's own name if unset

Partner: CHNX
Sequence: MTLES...
# Type: dna                     # optional: protein (default) / dna / rna
# Copies: X1, X2                # optional: homo-oligomer chain-id override -- this one partner
                                # sequence becomes multiple chains

Ligand: LIG1
SMILES: FC(F)CNC(...)=O         # exactly one of SMILES/CCD is required
# Role: agonist                 # optional: agonist / antagonist -- reporting only (dashboard
                                # chart shapes), never affects generate/run

Ligand: LIG2
CCD: GOL                        # a Chemical Component Dictionary code (e.g. common crystallization
                                # additives/ions) instead of a SMILES

Covalent bond: RECP1 residue 44 atom SG to LIG1 residue 1 atom C3
Pocket contact: RECP1 residue 148
Distance constraint: RECP1 residue 10 to RECP1 residue 80 within 8.0 Angstrom
```

Every protein is crossed with every ligand (unless a protein sets `Ligands:` to scope
itself to a subset, or `Ligands: none` for a single ligand-free/apo target), producing
one `{protein}_{ligand}.yaml` per pair. See `example.md` for the full copy-paste
template and `examples/` for complete working campaigns.

## 🚀 Commands

```sh
python3 BoltzMaker.py new      [boltz_input.md]  # write a new campaign by answering plain questions
python3 BoltzMaker.py format   boltz_input.md    # auto-align comments/blank-lines (cosmetic only)
python3 BoltzMaker.py generate boltz_input.md    # write the target YAMLs + manifest
python3 BoltzMaker.py preflight boltz_input.md   # environment + input sanity checks
python3 BoltzMaker.py run      boltz_input.md    # boltz predict, live progress, resumable
python3 BoltzMaker.py analyze  boltz_input.md    # CSV / XLSX / HTML dashboard
python3 BoltzMaker.py all      boltz_input.md    # generate -> preflight -> run -> analyze
python3 BoltzMaker.py boltz_input.md             # same as `all` (subcommand is optional)
python3 BoltzMaker.py compare-sse boltz_input.md # apo-vs-holo secondary-structure motif shifts (see below)
```

`new` interviews you (proteins, partners, ligands, and the three constraint sentence
types) and writes the file for you -- it won't overwrite an existing file without asking
first. It covers the common case only; rarer fields (modifications, cyclic, MSA
override, templates, homo-oligomer copies) are left for hand-editing the file it writes.
If `setup-plip` has been run, it also asks whether you have a reference structure with a
ligand already bound (a co-crystal or homology model) for each protein -- if so, it runs
cif2plip on it, lets you pick the relevant ligand if more than one is detected, and
suggests the contacted residues as `Pocket contact:` constraints, remapped onto your
target's own numbering via sequence alignment (BLOSUM62 + affine gaps) so the reference
structure's residue numbers don't have to match your target's.

`format` re-aligns trailing comments to a clean column and normalizes blank-line spacing
around section/record boundaries, purely cosmetic (it validates the file parses first,
and never changes meaning). Pass `--check` to report whether reformatting is needed
without writing anything (exit 1 if so, e.g. for a pre-commit check).

Any field BoltzMaker doesn't recognize (a typo like `Predict afinity:` instead of
`Predict affinity:`) prints a `WARNING` naming the block, its name, and the line number,
and is otherwise silently dropped, so a misspelled field never just vanishes without a
trace.

**Common options:**

| Option | Default | Description |
|---|---|---|
| `--output-dir` | `settings.output_dir` | Override where generated YAMLs are written |
| `--out-dir` | `./boltz_output` | Boltz's own `--out_dir`, next to the md file |
| `--accelerator` | `auto` | `auto` / `gpu` / `cpu` |
| `--limit N` | none | Cap how many pending targets `run` submits (smoke test before a full batch) |
| `--max-retries` | `2` | Auto-retry a target that doesn't complete (e.g. an OOM), isolating to one target at a time -- see "Memory on Mac" below (`0` disables) |
| `--strict` | off | Promote preflight WARN to FAIL |
| `--skip-interactions` | off | Skip cif2plip interaction analysis during `analyze`, even if `setup-plip` has been run |
| `--skip-sse` | off | Skip compare-sse apo-vs-holo analysis during `analyze`, even if a family has `Apo structure:` set |

**Memory-control options** (see below for why these matter on Mac/unified-memory hardware):

| Option | Default | Description |
|---|---|---|
| `--workers` | `2` | Matches Boltz's own default |
| `--mps-watermark` | `1.0` | `PYTORCH_MPS_HIGH_WATERMARK_RATIO` cap |
| `--max-parallel-samples` | `1` | Boltz `--max_parallel_samples` |
| `--recycling-steps` | Boltz default | Passthrough |
| `--sampling-steps` | Boltz default | Passthrough |
| `--diffusion-samples-affinity` | Boltz default | Passthrough |
| `--sampling-steps-affinity` | Boltz default | Passthrough |
| `--max-msa-seqs` | Boltz default | Passthrough |
| `--memory-warn-tokens` | `1000` | Preflight size-heuristic WARN threshold |

`run` is idempotent: targets with a complete prediction (cif + confidence json, and an
affinity json if `predict_affinity` is on) are skipped on re-run, so an interrupted batch
can just be re-run as-is.

**`compare-sse` options** (see the section below for what it does -- it now also runs
automatically as part of `analyze`/`all` for every family with an `Apo structure:` set;
the standalone command below is for re-running just this analysis on its own, e.g.
after adding an apo structure without re-running `boltz predict`):

| Option | Default | Description |
|---|---|---|
| `--family` | every family with `Apo structure:` set | Restrict to one `Protein` family id |
| `--target` | every target for the selected family | Restrict to one target stem |
| `--out-dir` | alongside `boltz_input.md` | Where to write the CSV/HTML/PyMOL scripts |
| `--phi-psi-threshold` | `30` (degrees) | Per-residue phi/psi delta above this is flagged |
| `--dfg-distance-threshold` | `8.0` (Angstrom) | DFG-Asp to catalytic-Lys Ca-Ca distance below this is classified DFG-in |
| `--alphac-distance-threshold` | `10.0` (Angstrom) | alphaC-Glu to catalytic-Lys Ca-Ca distance below this is classified alphaC-in |
| `--no-pymol` | off | Skip writing `.pml` session scripts |
| `--refresh-cache` | off | Bypass the GPCRdb/KLIFS/PDBe disk cache for this run |

## 🛠️ Memory on Mac (unified-memory) hardware

A real 4-chain GPCR+G-protein complex (~1250 combined residues/atoms) used **~65GB RAM on
a 64GB M1 Max** during testing and swap-thrashed for 20+ minutes with zero progress before
being killed, worth knowing about before running anything large. Mitigations built in:

- `--mps-watermark` sets `PYTORCH_MPS_HIGH_WATERMARK_RATIO`, which caps how much memory
  MPS will allocate relative to the device's recommended maximum. At the default `1.0`, an
  oversized complex now raises a clean MPS out-of-memory error in the log instead of
  silently spilling into swap.
- `--workers` defaults to 2 and `--max-parallel-samples` to 1: both trade a little
  parallelism for a much smaller memory footprint, which matters more on unified memory
  than on a dedicated-VRAM GPU.
- `preflight`'s `memory_heuristic` check WARNs when a target's total residue+ligand-atom
  count crosses `--memory-warn-tokens` (default 1000), citing the empirical data point
  above. It's a rough heuristic, not a precise memory model.
- `run`'s progress bar shows live memory usage (RSS summed across the whole `boltz
  predict` process tree), and logs a warning if usage stays above 90% of system RAM for
  60+ seconds with no new completed target: a sign of thrashing, not genuine progress.
- `run`/`all` auto-retries (`--max-retries`, default 2) any target that doesn't
  complete, isolating every still-incomplete target to its own single-target `boltz
  predict` invocation from the first retry onward -- a real 4-target cascade on
  `5ht2_gq_panel` (an OOM on 2 of 6 large targets run together crashed the shared
  affinity phase for 2 more that had already succeeded) recovered cleanly this way. This
  means a large campaign can be started and left unattended: a transient OOM no longer
  needs a human to notice, wait, and manually re-run just the affected targets.

If a target still fails after every automatic retry, that's a real finding (this
hardware may not be viable for a complex that size), not something to force through.

## ⚙️ Progress bar

Two rows during `run`: the outer bar shows targets done/total, elapsed time, an ETA, and
live memory usage. The inner row shows which **phase** Boltz is in (MSA generation /
structure prediction / affinity prediction) and that phase's own progress, parsed from
Boltz's own log output. Note: Boltz doesn't expose diffusion- or recycling-step-level
progress anywhere in its output (verified against the installed package's source), so this
is the finest granularity actually available, not a per-step diffusion counter.

## 📊 Outputs

Written next to `boltz_input.md`:

| Output | Description |
|---|---|
| `boltz_run_<timestamp>.log` | Raw `boltz predict` output for the run |
| `boltz_output/` | Boltz's own prediction output tree |
| `boltz_cif/` | Every completed target's `*_model_0.cif`, flattened into one folder |
| `boltz_summary.csv` / `boltz_summary.xlsx` | One row per target: every scalar field from the confidence/affinity JSONs, computed pIC50, the input ligand SMILES, and `flags`/`notes` columns (`LOW_CONFIDENCE`, `HIGH_CONFIDENCE_POOR_AFFINITY`, `LOW_CONFIDENCE_STRONG_AFFINITY`, `LOW_POCKET_PLDDT`, `MISSING_OUTPUTS`). The XLSX adds a `selectivity` sheet (ligand x family pIC50 pivot) whenever a campaign spans more than one protein family. When `setup-plip` has run, also gets a `plip_status` column (`ok` / `no_interactions` / `failed` / `ambiguous_ligand` / `skipped_no_env`) and a `plip_<type>_count` column per interaction type detected (hydrophobic, hydrogen_bonds, salt_bridges, etc.). |
| `boltz_summary_view.csv` | The same columns shown in the dashboard's "Summary table" (see below) -- a trimmed, renamed subset of `boltz_summary.csv`, for anyone who wants the at-a-glance view in a spreadsheet rather than every raw field |
| `boltz_ligand_grid.pdf` (optional) | A print/share-friendly PDF of the dashboard's "Ligand structures" grid -- same 5x5 pagination, same rendered structures, severity borders and scaffold highlighting as the on-screen version, in the style of [smiles2grid](https://github.com/bellcheddar/smiles2grid)'s own PDF output. Only written when a campaign has at least one SMILES ligand to render. |
| `boltz_plip/` (optional) | Per-target cif2plip output: the converted PDB, PLIP's XML/TXT reports, the ray-traced binding-site PNG, and the PyMOL `.pse` session -- cached here so re-running `analyze` doesn't re-profile a target that's already been done |
| `boltz_interactions.csv` (optional) | Long format, one row per detected contact across every target: interaction type, residue, distance -- the raw data behind the dashboard's fingerprint heatmap and per-target contact tables |
| `boltz_dashboard_sessions/` (optional) | Each target's PyMOL `.pse` session, copied here and linked from the dashboard -- this is the one thing that makes `boltz_dashboard.html` no longer a single self-contained file once interaction analysis has run; without `setup-plip`, the dashboard stays exactly as self-contained as before |
| `boltz_dashboard.html` | Posts its own real content height to any parent window via `postMessage` on load and resize, so a page embedding it in an iframe (e.g. `findings.md`'s "Interactive dashboard" section) can size the iframe to fit the actual content instead of guessing a fixed height -- a cross-origin iframe can't otherwise be measured/resized from the embedding page's own JS. A campaign summary table with a third "Details" column alongside Field/Value -- a linked path to the input file, each protein/partner's id and sequence length, each ligand's id and SMILES-vs-CCD source, the full list of target stems, which specific ligands got flagged in ligand-chemistry review (linking to the card below), and a plain-English gloss for each of the more cryptic run parameters (accelerator, MPS watermark, recycling/sampling steps, etc.) -- tracked across every `run` invocation in a small hidden sidecar file. Then a "Summary table" directly below it: grouped into named column bands (Identity, Confidence, Affinity, Interactions, Structure) with short human headers instead of raw JSON field names, redundant/granular columns (per-chain and per-chain-pair confidence breakdowns, individual ensemble sub-model values) hidden by regex pattern rather than a fixed list -- so it scales correctly to campaigns with more than two chains -- and two download links, one for the full underlying CSV and one for a CSV matching just this trimmed/renamed view. The "Target" column shows a `{group}_{partners}_{ligand}` display name (e.g. `5HT2A_GNAQ+GNB1+GNG2_RISP`, partners omitted when there are none, `apo` in place of a ligand for a ligand-free target) rather than the internal per-variant family id/stem (`H2ANG_RISP`, `H2AAP`) -- and this isn't just a table label: the same display name (or its family-level `{group}_{partners}` form, with no ligand, for whole-family contexts) replaces the internal id in every chart tick/legend/point label (ranked pIC50, ranked confidence, the pIC50-vs-confidence-score and pIC50-vs-binder-probability scatters, interaction counts, the residue-interaction fingerprint heatmap), every per-target/per-family card title, the campaign-summary target list, and the selectivity pivot's columns (both the dashboard heatmap and the XLSX `selectivity` sheet) -- see **compare-sse** below for the same treatment there. The raw per-variant ids stay alongside the display name in every underlying CSV/XLSX `targets` sheet, for cross-referencing against real output filenames. A "Partner" column lists each target's co-folded partner chain(s) (hidden when the campaign has none), and rows are grouped by `Group:`/family id with a blue top border marking each new group -- the same blue used for column-group boundaries, just rotated. The "Flags" column is renamed "Summary" and icon-based: a bullseye (affinity) and a shield (confidence) icon per row, each tinted green/amber/red by tier (exact value and interpretation on hover), reusing the existing `LOW_CONFIDENCE_THRESHOLD` and a symmetric buffer around Boltz's documented 0.5 binder decision boundary -- Boltz's own docs define these metrics' [0, 1] range but publish no official tri-colour bands. A `MISSING_OUTPUTS` failure collapses the cell to a single red cross; a legend to the right of the download links spells out all six tier/icon combinations. Always shown now (previously hidden entirely when nothing was flagged), so a clean campaign reads as a row of green icons rather than a column that silently disappears. A ligand-free (apo) target's ligand/affinity/interface/interaction columns (including the bullseye) show an explicit `N/A` rather than a blank cell or a misleading `0.00`, since there's no ligand or inter-chain interface for those to describe. Then a "Ligand preparation" card (the same stereocentre/protonation-state/disconnected-fragment checks as `preflight`'s `ligand_preparation` check, shown per-ligand rather than as a single summary line), then a "Ligand structures" card: a paginated 5x5 grid of every ligand's rendered 2D structure (building on [smiles2grid](https://github.com/bellcheddar/smiles2grid)'s design, adapted for a single campaign's scale), with stereocentre/ionizable-group findings highlighted directly on each structure, ligands sharing a Bemis-Murcko scaffold (or, failing that, a verified whole-group maximum-common-substructure) grouped and colour-highlighted together with their depictions aligned to a common orientation, and a captioned legend (badge-by-badge: what S/A/N/Ph/SO3/salt each mean, plus the cluster colour key) stating exactly what was found and on how many ligands -- never an unexplained highlight -- plus "Download PDF" (the same grid as a print/share-friendly file, `boltz_ligand_grid.pdf`) and "Download SMILES" (`boltz_ligands.csv`: ID, SMILES, stereocentre/ionizable-group/fragment findings, MW, cLogP, TPSA) links side by side on one line, matching the Summary table's own download-links style. Then interactive [Plotly](https://plotly.com/javascript/) charts in a grid (ranked pIC50, ranked confidence, a "pIC50 vs confidence score" scatter, interaction counts by type, then a "pIC50 vs binder probability" scatter (binder probability on x, pIC50 on y) -- hover/zoom/pan; plotly.js itself is vendored and inlined into the file rather than CDN-loaded, so the dashboard has no runtime dependency on an external script host). The two scatter charts colour each point by tier via a continuous colourscale + colorbar legend (the same style as the Family x ligand selectivity heatmap's own colorbar) -- confidence tier (matching the Summary table's shield icon) for pIC50-vs-confidence-score, affinity tier (matching the bullseye icon) for pIC50-vs-binder-probability -- and, when a `Ligand:` block sets the optional `Role: agonist`/`Role: antagonist` field, shape-code points by pharmacology (circle = agonist, diamond = antagonist) with a legend positioned inside the plot area's top-left corner (not Plotly's default outside-right position, which would otherwise collide with the colorbar); campaigns that don't set `Role:` see a single unshaped trace, unchanged from before. When `setup-plip` has run: a per-family residue-interaction fingerprint heatmap (also interactive Plotly -- shown for every family with interaction data, even a single ligand, though the similarity-based reordering that helps SAR ranking within a series only kicks in from 3+ ligands) and, per target, its binding-site image (residues labelled and interaction distances shown -- PLIP's own images have neither, so these are re-rendered from its PyMOL session with both added, with a "Download image" link of its own) next to an interactive, auto-rotating [3Dmol.js](https://3dmol.org) view of the same predicted structure (built directly from the mmCIF, ligand highlighted), side by side with a table of that target's contacts (with its own "Download CSV" link) plus a download link for the full PyMOL session. Finally, a "Secondary structure shifts" card (see **compare-sse** below): a "Family coverage" table (every protein family in the campaign, with its status -- `OK` and a target/motif count, or a plain-English reason it was skipped, e.g. "No apo structure configured"), an "Overall shift statistics" summary, and, when there's data, the full per-motif table plus its own Plotly charts. |
| `boltz_sse_comparison.csv` / `.html` | Written automatically by `analyze`/`all` whenever any family has `Apo structure:` set (or on demand via the standalone `compare-sse` command). One row per family/target/motif: Ca RMSD, centroid shift, helix-axis rotation/kink angles, SSE boundary shift, flagged phi/psi residues, and (kinases) DFG-in/out and alphaC-in/out states -- a metric that genuinely wasn't computed for a motif shows as `N/A`, not a blank cell. The Family/Target columns, chart legends, and family-coverage table all show the same `{group}_{partners}` / `{group}_{partners}_{ligand}` display names used throughout the main dashboard; the CSV also keeps the raw `family_id`/`target_stem` columns alongside for cross-referencing. The HTML is a standalone dashboard (family coverage, overall shift statistics, Plotly bar chart + motif x target heatmap); the same content is also embedded directly into `boltz_dashboard.html` (see below) |
| `boltz_sse_family_status.json` | One entry per protein family: `ok` (with a target/motif count) / `no_apo_structure` / `apo_not_found` / `annotation_failed` / `no_predicted_structures` -- the machine-readable form of the dashboard's "Family coverage" table, so a family with no `Apo structure:` configured reads as "not configured" rather than silently missing |
| `boltz_sse_comparison_sessions/` (optional) | A plain-text PyMOL `.pml` script per target -- colours/labels each motif, highlights the ones with a significant shift |

## 🔬 Ligand validation & scaffold highlighting

Two related but distinct checks run over every SMILES ligand before you commit hours of
`boltz predict` time to them, and both surface directly in the dashboard.

**Why this exists:** Boltz folds whatever chemistry it's given -- an undefined
stereocentre, an unintended protonation state, or a stray counterion left in a SMILES
string doesn't raise an error, it just silently changes the predicted pose and affinity.
These are exactly the mistakes a non-specialist (or a tired specialist) makes typing
SMILES by hand, and they're invisible until you're staring at a confusing result with no
idea the input was ever wrong.

### Ligand preparation (validity checks)

At parse time, every ligand SMILES is canonicalized (RDKit) so the same molecule is
represented consistently everywhere downstream -- the generated YAML, the summary table,
and cif2plip's own ligand-matching (see the InChIKey-based matching note in
[CHANGELOG.md](CHANGELOG.md)). Then, both at `preflight` (as the `ligand_preparation`
check) and again in the dashboard's "Ligand preparation" card, each ligand is checked for:

| Check | How | What it means |
|---|---|---|
| Undefined stereocentres | `Chem.FindMolChiralCenters(includeUnassigned=True)` | A stereocentre exists in the molecule but the SMILES doesn't specify which enantiomer/diastereomer -- Boltz will fold *some* version of it, possibly not the one you intended |
| Disconnected fragments | `Chem.GetMolFrags()` returns more than one fragment | Likely a salt or counterion left in the SMILES (e.g. a sodium carboxylate written as two components) |
| Ionizable groups | SMARTS match: carboxylic acid, primary/secondary amine, phenol, sulfonic acid | The group's protonation state at physiological pH isn't specified by a plain SMILES -- worth a deliberate choice, not a default assumption |

All of this is advisory, not a hard failure -- these can be legitimate, deliberate
modelling choices -- but they're the kind of thing worth a second look before trusting
downstream numbers.

### Scaffold highlighting (the "Ligand structures" grid)

Separately, the dashboard's ligand grid tries to answer a different question: *do any of
these ligands share a chemical core?* This matters most for SAR (structure-activity
relationship) campaigns, where a chemist is usually testing close analogues on purpose,
and seeing the shared scaffold at a glance (with the parts that differ jumping out) is
more useful than reading each SMILES individually. Two tiers, in order, and nothing is
highlighted unless one of them actually finds something real:

1. **Exact Bemis-Murcko scaffold match** -- ligands whose ring systems + connecting
   linkers are chemically identical are grouped, threshold-free. This is the dominant
   case for a real SAR series.
2. **Fallback for near-analogues:** ligands left over are grouped by Morgan/Tanimoto
   fingerprint similarity, then a maximum common substructure (MCS) is computed across
   the *whole* group and verified to actually match every member -- so the claim is a
   proven substructure match, not just an assigned similarity score.

Small or trivial shared fragments (below 8 heavy atoms -- e.g. "they all contain a
benzene ring") are deliberately not highlighted; a group has to share something
structurally meaningful to be called out. Ligands in the same scaffold group also have
their 2D depiction aligned to a common orientation, so the shared core is drawn in the
same position across cells and visually "snaps together."

**What's highlighted and how**, directly on each rendered structure -- the same badges
shown on each ligand cell and spelled out in the panel's own legend:

| Badge | Colour | Meaning |
|---|---|---|
| `S` | 🟪 Magenta | Undefined stereocentre (RDKit also draws its own `(?)` marker at the atom) |
| `A` | 🟧 Amber | Carboxylic acid -- protonation state not specified |
| `N` | 🟧 Amber | Primary/secondary amine -- protonation state not specified |
| `Ph` | 🟧 Amber | Phenol -- protonation state not specified |
| `SO3` | 🟧 Amber | Sulfonic acid -- protonation state not specified |
| `salt` | 🟥 Red | Disconnected fragment (salt/counterion) -- flagged on the border and badge only, not atom-highlighted (there's no single meaningful atom to point at) |
| -- | one of six colour-blind-safe palette colours | Atoms in a shared scaffold/substructure -- consistent per group, with a legend entry naming the group and how many ligands share it (e.g. "shared scaffold -- 3/5 ligands") |

A specific finding (stereocentre, ionizable group) always takes priority over the softer
scaffold highlight if they overlap on the same atom, since it's the more actionable
signal. If no ligand shares a real scaffold with any other, the panel says so plainly
("no shared scaffold or substructure detected") rather than forcing a highlight onto
something coincidental. CCD-code ligands have no SMILES to render and show a plain
placeholder instead of an empty cell.

## 🧬 compare-sse: apo vs holo secondary-structure shifts

**Why this exists:** a confidence score tells you *what* Boltz predicted, not *how the
protein moved* in response to ligand binding -- a real structural question whenever you
have both a reference apo (unbound) structure and a predicted holo one for the same
protein. `compare-sse` answers it in terms a structural biologist actually reasons in
("TM6 swung out 4.2 Angstrom", "the DFG motif flipped from in to out"), not raw DSSP
fragment coordinates.

It's a core part of `analyze`/`all`: any family with an `Apo structure:` field set (see
**boltz_input.md format** above) gets compared automatically, no separate command
needed, and the result is embedded directly into `boltz_dashboard.html`. A family with
no apo structure configured isn't silently skipped either -- the dashboard's "Family
coverage" table says so explicitly, alongside any family that *was* compared. Pass
`--skip-sse` to `analyze`/`all` to opt out, or use the standalone `compare-sse` command
below to re-run just this analysis on its own (its own `--family`/`--target` flags let
you target one family/target instead of the whole campaign).

Motifs are annotated by one of three pluggable sources, auto-selected per family (or set
explicitly with `Family type:`):

| Family type | Motifs | Source |
|---|---|---|
| `gpcr` | TM1-7, H8, ECL1-3, ICL1-3 | [GPCRdb](https://gpcrdb.org)'s structure-based generic-numbering service (Ballesteros-Weinstein / GPCRdb schemes) |
| `kinase` | hinge, gatekeeper, catalytic loop (HRD), DFG motif, alphaC-Glu, catalytic Lys | [KLIFS](https://klifs.net)'s public REST API (its fixed 85-residue pocket alignment) |
| `auto` (default) | whichever of the above applies, else... | ...falls back to Pfam domain boundaries via [PDBe](https://www.ebi.ac.uk/pdbe)'s SIFTS residue mapping -- the universal last resort for any protein outside the two families above |

Apo is superposed onto holo using only the family's stable, non-binding-site-adjacent
residues (via gemmi's `superpose_positions`), so a ligand-induced local shift can't skew
the global fit. Each motif then gets:

| Metric | What it means |
|---|---|
| Ca RMSD / centroid shift | How far the motif moved, post-superposition |
| Helix-axis rotation angle | For helical motifs -- e.g. the classic TM6 "outward swing" on GPCR activation |
| Helix kink angle (apo/holo/delta) | Whether a helix straightened or kinked more |
| SSE boundary shift | Did the helix/strand get longer or shorter -- needs deposited HELIX/SHEET records, or an optional external `mkdssp`/`dssp` binary as a fallback (see **One-time setup** above); every other metric works without it |
| Flagged phi/psi residues | Per-residue backbone dihedral outliers above `--phi-psi-threshold` |
| DFG-in/out, alphaC-in/out (kinases only) | A coarse Ca-Ca distance classifier, not a full dihedral model -- good for detecting a state *change* between apo and holo, not publication-grade conformational classification |

A metric that genuinely wasn't computed for a given motif (e.g. axis rotation for a
loop, DFG state for a non-kinase family, boundary shift with no DSSP data available)
shows as an explicit `N/A` in both the CSV and every dashboard table, not a blank cell.

Above the per-motif table, both `boltz_dashboard.html`'s embedded card and the
standalone `boltz_sse_comparison.html` show:

| Section | Content |
|---|---|
| Family coverage | One row per protein family: `OK` (with a target/motif count) / `No apo structure configured` / `Apo structure file not found` / `No motif annotation available` / `No predicted (holo) structures yet` |
| Overall shift statistics | Targets/motifs compared; mean/median/max Ca RMSD (and which target + motif had the largest shift); mean centroid shift; total flagged phi/psi residues; kinase DFG/alphaC state-change counts |

```sh
python3 BoltzMaker.py compare-sse boltz_input.md
```

Writes, next to `boltz_input.md` (or `--out-dir`): `boltz_sse_comparison.csv` (one row
per family/target/motif) and `boltz_sse_family_status.json` (the family-coverage table
above, machine-readable), a standalone self-contained `boltz_sse_comparison.html`
(Plotly bar chart + motif x target heatmap, vendored the same way as the main
dashboard), and `boltz_sse_comparison_sessions/<target>.pml` -- a plain-text PyMOL
script per target that colours/labels each motif and highlights the ones with a
significant shift. It's just text: opens in any local PyMOL install, no `pymol`
dependency in BoltzMaker's own venv.

When auto-run by `analyze`/`all`, a campaign with no apo structures configured
anywhere just gets a dashboard section saying so -- it never aborts the rest of the
pipeline over an optional, additive feature. The standalone command above still exits
with a clear error if you explicitly pass a `--family`/`--target` that matches
nothing, since that's a real mistake worth stopping for.

## 🩹 Troubleshooting / FAQ

| Problem | Fix |
|---|---|
| `setup-plip` fails, or `pip install plip` tries to build OpenBabel from source | This is expected without conda-forge -- `plip`'s own installer forces a from-source OpenBabel rebuild unless OpenBabel is already importable *inside pip's build sandbox*, and the standalone PyPI `pymol-open-source` wheel has a hardcoded broken library path on at least some machines. `setup-plip` works around both by building a conda-forge env via a self-downloaded micromamba -- just re-run `python3 BoltzMaker.py setup-plip --force` if a previous attempt left a half-built `.plip_env`. |
| A `preflight`/`analyze` step involving `.plip_env` errors with `ModuleNotFoundError: No module named 'chatmol'` (or similar) | A stray `~/.pymolrc.py` on your machine (e.g. from an unrelated PyMOL plugin) is being loaded by the bundled PyMOL. BoltzMaker already overrides `HOME` for these subprocess calls so this shouldn't reach you, but if it does, check `~/.pymolrc.py` for anything referencing a package not installed in `.plip_env`. |
| `run` seems to hang with no progress, or your Mac gets extremely slow | Check the memory-usage figure in the progress bar and see "Memory on Mac" earlier in this document -- this is very likely swap-thrashing, not a genuine stall. Re-run with a lower `--mps-watermark`, `--workers 1`, and `--max-parallel-samples 1`. |
| A target's YAML/CIF exists on disk but BoltzMaker says it's missing, or `preflight` hangs | Check for iCloud "Optimize Mac Storage" dataless files -- `preflight`'s `icloud_materialize` check handles this automatically, but a very large campaign can take a while to force-download everything on first run. |
| `boltz` fails during `setup` with a `numpy` build error | You're likely on Python 3.13+. `boltz` pins `numpy<2.0`, which has no prebuilt wheel past cp312 -- `_find_boltz_python()` already looks for a `python3.12` specifically; install one (`brew install python@3.12`) if it can't find one. |
| A target fails preflight with a chain-id-length error | Boltz truncates chain IDs to 5 characters internally (a fixed-width field in its own schema) and silently corrupts longer ones rather than erroring at parse time -- shorten the protein/partner/ligand name in `boltz_input.md`. |
| The dashboard's charts (or the binding-site 3D view) don't render, or look unstyled | plotly.js and 3Dmol.js are both vendored and inlined (not CDN-loaded), so this shouldn't happen from a missing network connection -- Google Fonts is still loaded from a CDN for styling, though, so the page needs internet access at least once for the fonts to look right (falls back to a generic sans-serif otherwise; charts, 3D views, and data are unaffected). If they genuinely don't render, check that `vendor/plotly-2.35.2.min.js` and `vendor/3Dmol-2.5.5-min.js` exist next to `BoltzMaker.py` -- `analyze` prints a warning and falls back to the relevant CDN (which is known not to work in some HTML-preview contexts) if either is missing. |

## 🧫 Testing

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/
```

27 tests covering `compare-sse`'s annotators against real fixture data (a real apo EGFR
kinase-domain structure vs the `egfr_covalent` example's real holo prediction; a real
apo beta2-adrenergic-receptor structure vs `adrb2_gs_panel`'s real holo predictions),
with GPCRdb/KLIFS/PDBe network calls swapped for an injectable fake client seeded with
real, previously-verified API responses -- fully offline and fast (~2s). Plus grammar
and CLI-resolution tests for the parser fields above.

## 📚 Citation

> Passaro, S., Corso, G., Wohlwend, J., Reveiz, M., Thaler, S., Somnath, V.R., Getz, N., Portnoi, T., Roy, J., Stark, H., Kwabi-Addo, D., Beaini, D., Jaakkola, T., Barzilay, R. (2025). Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction. *bioRxiv*. https://doi.org/10.1101/2025.06.14.659707

> Mirdita, M., Schütze, K., Moriwaki, Y., Heo, L., Ovchinnikov, S., Steinegger, M. (2022). ColabFold: making protein folding accessible to all. *Nature Methods*. https://doi.org/10.1038/s41592-022-01488-1

> Schake, P., Bolz, S.N. et al. (2025). PLIP 2025: introducing protein-protein interactions to the protein-ligand interaction profiler. *Nucleic Acids Research*, gkaf361. https://doi.org/10.1093/nar/gkaf361

> The PyMOL Molecular Graphics System, Version 3.1, Schrödinger, LLC.

> Rego, N., Koes, D. (2015). 3Dmol.js: molecular visualization with WebGL. *Bioinformatics*, 31(8), 1322-1324. https://doi.org/10.1093/bioinformatics/btu829

## 📄 License

[MIT](LICENSE) &copy; Marc C. Deller

## 📋 To do

- [ ] Share pip cache between the two environments (`PIP_CACHE_DIR`) so `setup-plip` doesn't re-download wheels the main venv already fetched
- [ ] Pin exact dependency versions in both installers and add a cached/offline install mode for reproducible installs
- [ ] Add `BoltzMaker.py doctor` -- a post-install check that imports boltz/rdkit/plip/openbabel/pymol in-process and reports exactly which env/feature is broken
- [ ] Add an explicit Boltz model-weights cache dir + a `preflight` check for it (ties into the existing iCloud dataless-file eviction check)
- [ ] Detect the MPS `torch.linalg.svd` CPU-fallback at `preflight` and warn with an estimated runtime multiplier for large multi-chain complexes
- [ ] Add a residue/chain-count-based runtime pre-estimator, plus a toggle to log which ops fall back to CPU on MPS
- [ ] Checkpoint `run` at the per-sample level (not just per-target) so an interrupted multi-hour complex resumes without recomputing completed diffusion samples
- [ ] Add a cross-target selectivity/triage view to the dashboard (confidence-vs-affinity quadrant flags for "high-confidence, high-affinity" hits)
- [x] Bundle Plotly.js locally instead of via CDN so the dashboard renders fully offline/air-gapped
- [ ] Add a smoke-test suite: an end-to-end fixture run in CI plus unit tests for the `boltz_input.md` parser and JSON-metric flattening
- [x] Add a ligand-preparation/validation step (canonicalization, stereocentre/protonation-state flagging, disconnected-fragment detection) so bad input chemistry is caught before hours of compute, not silently mispredicted
- [ ] Add a retrospective `benchmark` mode: pull known actives/co-crystal data for a target family (ChEMBL/BindingDB/PDB) and report predicted-vs-measured pIC50 correlation + pose RMSD, so a user has a per-target-family trust score before committing to a real campaign
- [x] Add a 3Dmol.js rotating structure view to each target's binding-site panel, placed next to the existing static PyMOL image (keep the static image, add a "Download image" link for it -- doesn't exist yet -- and add the interactive 3Dmol.js view alongside rather than replacing anything)

---

## 👤 Author

**Marc C. Deller, D.Phil.**
Structural biologist & drug discovery scientist

<table>
<tr>
<td>🌐</td><td><a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">marcdeller.com</a></td>
<td>✉️</td><td><a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a></td>
<td>🐙</td><td><a href="https://github.com/bellcheddar/BoltzMaker" target="_blank" rel="noopener noreferrer">github.com/bellcheddar/BoltzMaker</a></td>
</tr>
</table>
