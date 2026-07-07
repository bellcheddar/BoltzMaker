# 🧬 BoltzMaker

> **BoltzMaker: Boltz2 campaign-scale structure and affinity prediction, binding analysis, and run control, orchestrated end to end from a single spec file.**

![python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white) ![boltz](https://img.shields.io/badge/boltz-2-00897B) ![plip](https://img.shields.io/badge/PLIP-interactions-9b51e0) ![pymol](https://img.shields.io/badge/PyMOL-visualisation-ff6900) ![rdkit](https://img.shields.io/badge/RDKit-cheminformatics-00d084) ![plotly](https://img.shields.io/badge/Plotly-charts-3F4F75?logo=plotly&logoColor=white) ![licence](https://img.shields.io/badge/licence-MIT-467FF7) ![author](https://img.shields.io/badge/author-Marc%20C.%20Deller%2C%20D.Phil.-1C244B)

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

BoltzMaker grew out of four smaller, single-purpose tools written earlier:
[generate_yaml](https://github.com/bellcheddar/generate_yaml) for building the input
YAMLs, [simple-zsh-script-to-run-boltz2](https://github.com/bellcheddar/simple-zsh-script-to-run-boltz2)
for driving the actual `boltz predict` runs, [analyze-boltz2-results](https://github.com/bellcheddar/analyze-boltz2-results)
for the post-run analysis, and [cif2plip](https://github.com/bellcheddar/cif2plip) for
protein-ligand interaction profiling. BoltzMaker consolidates all four into one
spec-driven pipeline sharing a single campaign format, so the same input file drives
every stage instead of juggling separate scripts and re-typing target names between them.

(And yes, the name is a nod to [Boltmaker](https://www.timothytaylor.co.uk/beer/boltmaker),
Timothy Taylor's Champion Beer of Britain and one of the author's favourites.)

See [CHANGELOG.md](CHANGELOG.md) for what's changed recently.

## 🧩 Architecture

| Stage | Command | Produces |
|---|---|---|
| 1. Input | -- | `boltz_input.md`: the family x partners x ligand DSL spec |
| 2. Generate | `generate` | `boltz_yamls/*.yaml` + `.boltzmaker_manifest.json` |
| 3. Preflight | `preflight` | PASS / WARN / FAIL checks: boltz CLI, GPU/MPS, disk, iCloud, YAML/SMILES/chain-id, ligand chemistry, memory heuristic |
| 4. Predict | `run` (resumable) | Managed `.venv` -> `boltz predict` -> `boltz_output/predictions/`, live 2-row progress bar + memory monitor |
| 5. Analyze | `analyze` | `boltz_summary.csv` / `.xlsx`, `boltz_dashboard.html`, `boltz_cif/`, and (if `setup-plip` has been run) `boltz_interactions.csv` + `boltz_plip/` |

Each stage reads only the manifest + files the previous stage wrote, so any stage can be
re-run on its own (`generate`, `preflight`, `run`, or `analyze` individually) without
repeating the others: `all` simply chains all four.

## 🔧 One-time setup

```sh
python3 BoltzMaker.py setup
```

Creates a dedicated `.venv` (Python 3.12: boltz pins `numpy<2.0`, which has no prebuilt
wheel for newer Pythons) next to `BoltzMaker.py` and installs `boltz`, `rich`, `pandas`,
`openpyxl`, `pyyaml`, `rdkit`, `matplotlib`, `psutil`, `scipy`, `gemmi`, `biopython`, and
`plotly` into it. This pulls PyTorch (~2-3 GB) and, the first time `boltz predict` actually
runs, Boltz downloads several GB of model weights over the network. Every other command
below transparently relaunches itself under this managed environment, so you can keep
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

## 🧪 Examples

Three small, entirely public-domain campaigns in `examples/`, run any of them with
`python3 BoltzMaker.py all examples/<name>/boltz_input.md`:

| Example | Demonstrates | Dashboard |
|---|---|---|
| `t4_lysozyme` | One protein (T4 lysozyme L99A, UniProt P00720) + one ligand (benzene). No partners, no pocket_contacts. The minimal shape; smallest/fastest smoke test. | [boltz_dashboard.html](https://htmlpreview.github.io/?https://github.com/bellcheddar/BoltzMaker/blob/main/examples/t4_lysozyme/boltz_dashboard.html) |
| `egfr_covalent` | EGFR kinase domain (UniProt P00533) + a generic covalent fragment, linked via `bond_constraints` at Cys797. Demonstrates covalent-linkage modelling. | [boltz_dashboard.html](https://htmlpreview.github.io/?https://github.com/bellcheddar/BoltzMaker/blob/main/examples/egfr_covalent/boltz_dashboard.html) |
| `adrb2_gs_panel` | Beta-2 adrenergic receptor (UniProt P07550) + Gs alpha partner (UniProt P63092) crossed with two ligands (agonist + antagonist), giving 2 targets. Demonstrates the family x partners x ligand cross-product. | [boltz_dashboard.html](https://htmlpreview.github.io/?https://github.com/bellcheddar/BoltzMaker/blob/main/examples/adrb2_gs_panel/boltz_dashboard.html) |

**Verified end-to-end** (`generate` -> `preflight` -> real `boltz predict` -> `analyze`,
including cif2plip interaction analysis) on an Apple M1 Max, 64GB:

| Example | Targets | Total time | Result |
|---|---|---|---|
| `t4_lysozyme` | 1 | 3m 16s | confidence 0.98, pIC50 8.9, 7 hydrophobic contacts matching the known L99A cavity residues |
| `egfr_covalent` | 1 | 5m 31s | confidence 0.92, covalent Cys797 SG-to-fragment bond confirmed at 1.75 Angstrom |
| `adrb2_gs_panel` | 2 | 1h 28m 36s | confidence 0.79 / 0.80 |

Run time scales with complex size, not just target count: `adrb2_gs_panel`'s two-chain
receptor+partner complex (crossed with 2 ligands) took disproportionately longer than the
single-chain examples, since attention-style operations scale worse than linearly with
sequence length. One contributing factor on Apple Silicon specifically: `torch.linalg.svd`
(used in the diffusion step) has no MPS implementation and silently falls back to CPU --
worth budgeting for on large multi-chain campaigns.

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
Output folder: ./boltz_yamls   # where generated per-target YAMLs are written
Predict affinity: no           # off by default -- it's a heavier prediction pass

Protein: RECP1                 # short name, MAX 5 CHARACTERS (Boltz stores chain names
                                # in a fixed 5-char field internally and silently
                                # truncates longer ones, which then crashes later with a
                                # confusing error -- `preflight` catches this for you).
                                # Also names the output file: {protein}_{ligand}.yaml
Sequence: MDILC...              # required
Partners: CHNX, CHNY            # optional: co-folded chains, defined as their own
                                 # Partner: blocks below
# Ligands: LIG1, LIG3            # optional: restrict this protein to a ligand subset
                                  # (default: crossed with every ligand below)
# Modifications: SEP:5           # optional: CCD:position tokens for modified residues
                                  # (e.g. phosphoserine)
# Cyclic: yes                    # optional: cyclic polymer (e.g. a cyclic peptide)
# MSA: empty                     # optional: path to a precomputed MSA, or "empty" for
                                  # single-sequence mode (skip MSA generation)
# Templates: reference_structure.cif
                                  # optional: structural template file(s), applied to all
                                  # protein chains (no per-chain mapping -- hand-edit the
                                  # generated YAML for that rarer case)

Partner: CHNX
Sequence: MTLES...
# Type: dna              # optional: protein (default) / dna / rna
# Copies: X1, X2         # optional: homo-oligomer chain-id override -- this one partner
                          # sequence becomes multiple chains

Ligand: LIG1
SMILES: FC(F)CNC(...)=O   # exactly one of SMILES/CCD is required

Ligand: LIG2
CCD: GOL   # a Chemical Component Dictionary code (e.g. common crystallization
           # additives/ions) instead of a SMILES

Covalent bond: RECP1 residue 44 atom SG to LIG1 residue 1 atom C3
Pocket contact: RECP1 residue 148
Distance constraint: RECP1 residue 10 to RECP1 residue 80 within 8.0 Angstrom
```

Every protein is crossed with every ligand (unless a protein sets `Ligands:` to scope
itself to a subset), producing one `{protein}_{ligand}.yaml` per pair. See `example.md`
for the full copy-paste template and `examples/` for complete working campaigns.

## 🚀 Commands

```sh
python3 BoltzMaker.py new      [boltz_input.md]   # write a new campaign by answering plain questions
python3 BoltzMaker.py format   boltz_input.md    # auto-align comments/blank-lines (cosmetic only)
python3 BoltzMaker.py generate  boltz_input.md    # write the target YAMLs + manifest
python3 BoltzMaker.py preflight boltz_input.md    # environment + input sanity checks
python3 BoltzMaker.py run       boltz_input.md    # boltz predict, live progress, resumable
python3 BoltzMaker.py analyze   boltz_input.md    # CSV / XLSX / HTML dashboard
python3 BoltzMaker.py all       boltz_input.md    # generate -> preflight -> run -> analyze
python3 BoltzMaker.py boltz_input.md              # same as `all` (subcommand is optional)
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
| `--strict` | off | Promote preflight WARN to FAIL |
| `--skip-interactions` | off | Skip cif2plip interaction analysis during `analyze`, even if `setup-plip` has been run |

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

If a target still thrashes even with all of the above at their safest settings, that's a
real finding (this hardware may not be viable for a complex that size), not something to
force through.

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
| `boltz_plip/` (optional) | Per-target cif2plip output: the converted PDB, PLIP's XML/TXT reports, the ray-traced binding-site PNG, and the PyMOL `.pse` session -- cached here so re-running `analyze` doesn't re-profile a target that's already been done |
| `boltz_interactions.csv` (optional) | Long format, one row per detected contact across every target: interaction type, residue, distance -- the raw data behind the dashboard's fingerprint heatmap and per-target contact tables |
| `boltz_dashboard_sessions/` (optional) | Each target's PyMOL `.pse` session, copied here and linked from the dashboard -- this is the one thing that makes `boltz_dashboard.html` no longer a single self-contained file once interaction analysis has run; without `setup-plip`, the dashboard stays exactly as self-contained as before |
| `boltz_dashboard.html` | A campaign summary table (input file, protein/partner/ligand/target counts, predict-affinity setting, a one-line ligand-chemistry flag count, and -- once a `run` has happened -- boltz predict runtime and the run parameters used, tracked across every `run` invocation in a small hidden sidecar file), then a "Ligand preparation" card (the same stereocentre/protonation-state/disconnected-fragment checks as `preflight`'s `ligand_preparation` check, shown per-ligand rather than as a single summary line), then the full results table (rounded to 2 decimal places for display, with a subset of noisy/redundant columns hidden and a download link to the underlying CSV), then four interactive [Plotly](https://plotly.com/javascript/) charts in a 2x2 grid (ranked pIC50, ranked confidence, confidence-vs-affinity scatter, interaction counts by type -- hover/zoom/pan, loaded via the plotly.js CDN). When `setup-plip` has run: a per-family residue-interaction fingerprint heatmap (ligands clustered by similarity -- useful for SAR ranking within a series) and, per target, its binding-site image (residues labelled and interaction distances shown -- PLIP's own images have neither, so these are re-rendered from its PyMOL session with both added) side by side with a table of that target's contacts, plus a link to the full PyMOL session. |

## 🩹 Troubleshooting / FAQ

| Problem | Fix |
|---|---|
| `setup-plip` fails, or `pip install plip` tries to build OpenBabel from source | This is expected without conda-forge -- `plip`'s own installer forces a from-source OpenBabel rebuild unless OpenBabel is already importable *inside pip's build sandbox*, and the standalone PyPI `pymol-open-source` wheel has a hardcoded broken library path on at least some machines. `setup-plip` works around both by building a conda-forge env via a self-downloaded micromamba -- just re-run `python3 BoltzMaker.py setup-plip --force` if a previous attempt left a half-built `.plip_env`. |
| A `preflight`/`analyze` step involving `.plip_env` errors with `ModuleNotFoundError: No module named 'chatmol'` (or similar) | A stray `~/.pymolrc.py` on your machine (e.g. from an unrelated PyMOL plugin) is being loaded by the bundled PyMOL. BoltzMaker already overrides `HOME` for these subprocess calls so this shouldn't reach you, but if it does, check `~/.pymolrc.py` for anything referencing a package not installed in `.plip_env`. |
| `run` seems to hang with no progress, or your Mac gets extremely slow | Check the memory-usage figure in the progress bar and see "Memory on Mac" earlier in this document -- this is very likely swap-thrashing, not a genuine stall. Re-run with a lower `--mps-watermark`, `--workers 1`, and `--max-parallel-samples 1`. |
| A target's YAML/CIF exists on disk but BoltzMaker says it's missing, or `preflight` hangs | Check for iCloud "Optimize Mac Storage" dataless files -- `preflight`'s `icloud_materialize` check handles this automatically, but a very large campaign can take a while to force-download everything on first run. |
| `boltz` fails during `setup` with a `numpy` build error | You're likely on Python 3.13+. `boltz` pins `numpy<2.0`, which has no prebuilt wheel past cp312 -- `_find_boltz_python()` already looks for a `python3.12` specifically; install one (`brew install python@3.12`) if it can't find one. |
| A target fails preflight with a chain-id-length error | Boltz truncates chain IDs to 5 characters internally (a fixed-width field in its own schema) and silently corrupts longer ones rather than erroring at parse time -- shorten the protein/partner/ligand name in `boltz_input.md`. |
| The dashboard's charts don't render, or look unstyled | The dashboard loads Google Fonts and plotly.js from CDNs -- it needs internet access the first time it's opened (results and cached fonts/scripts may work offline afterwards depending on your browser, but this isn't guaranteed). |

## 📚 Citation

BoltzMaker itself has no publication -- if you use it, please cite the underlying tools it
orchestrates instead:

```bibtex
@article{passaro2025boltz2,
  author = {Passaro, Saro and Corso, Gabriele and Wohlwend, Jeremy and Reveiz, Mateo and Thaler, Stephan and Somnath, Vignesh Ram and Getz, Noah and Portnoi, Tally and Roy, Julien and Stark, Hannes and Kwabi-Addo, David and Beaini, Dominique and Jaakkola, Tommi and Barzilay, Regina},
  title = {Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction},
  year = {2025},
  doi = {10.1101/2025.06.14.659707},
  journal = {bioRxiv}
}
```

If your campaign uses BoltzMaker's default automatic MSA generation (`--use_msa_server`),
also cite ColabFold:

```bibtex
@article{mirdita2022colabfold,
  title={ColabFold: making protein folding accessible to all},
  author={Mirdita, Milot and Sch{\"u}tze, Konstantin and Moriwaki, Yoshitaka and Heo, Lim and Ovchinnikov, Sergey and Steinegger, Martin},
  journal={Nature methods},
  year={2022}
}
```

If your campaign has run `setup-plip` and used cif2plip's interaction analysis, also cite PLIP:

> Schake, P., Bolz, S.N. et al. (2025). PLIP 2025: introducing protein-protein interactions
> to the protein-ligand interaction profiler. *Nucleic Acids Research*, gkaf361.
> https://doi.org/10.1093/nar/gkaf361

`setup-plip` also generates each binding-site image and `.pse` session with PyMOL, which
(having no journal paper of its own) is conventionally cited as:

> The PyMOL Molecular Graphics System, Version 3.1, Schrödinger, LLC.

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
- [ ] Bundle Plotly.js locally instead of via CDN so the dashboard renders fully offline/air-gapped
- [ ] Add a smoke-test suite: an end-to-end fixture run in CI plus unit tests for the `boltz_input.md` parser and JSON-metric flattening
- [x] Add a ligand-preparation/validation step (canonicalization, stereocentre/protonation-state flagging, disconnected-fragment detection) so bad input chemistry is caught before hours of compute, not silently mispredicted
- [ ] Add a retrospective `benchmark` mode: pull known actives/co-crystal data for a target family (ChEMBL/BindingDB/PDB) and report predicted-vs-measured pIC50 correlation + pose RMSD, so a user has a per-target-family trust score before committing to a real campaign

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
