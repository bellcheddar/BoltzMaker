# 🧬 BoltzMaker

> **BoltzMaker: Boltz2 campaign-scale structure and affinity prediction, binding analysis, and run control, orchestrated end to end from a single spec file.**

[![live](https://img.shields.io/badge/live-boltzmaker.mdeller.com-00d084?logo=icloud&logoColor=white)](https://boltzmaker.mdeller.com) ![python](https://img.shields.io/badge/python-3.12.3-3776AB?logo=python&logoColor=white) ![flask](https://img.shields.io/badge/flask-3.1.3-000000?logo=flask&logoColor=white) ![gunicorn](https://img.shields.io/badge/gunicorn-26.0.0-499848?logo=gunicorn&logoColor=white) ![nginx](https://img.shields.io/badge/nginx-1.24.0-009639?logo=nginx&logoColor=white) ![boltz](https://img.shields.io/badge/boltz-2-00897B) ![rdkit](https://img.shields.io/badge/RDKit-2026.03-00d084) ![gemmi](https://img.shields.io/badge/gemmi-0.6.5-8a3ffc) ![biopython](https://img.shields.io/badge/Biopython-1.84-1a6b8f) ![plip](https://img.shields.io/badge/PLIP-2025-9b51e0) ![pymol](https://img.shields.io/badge/PyMOL-3.1-ff6900) ![plotly](https://img.shields.io/badge/Plotly.js-2.35.2-3F4F75?logo=plotly&logoColor=white) ![3dmoljs](https://img.shields.io/badge/3Dmol.js-3D%20viewer-fcb900) ![molstar](https://img.shields.io/badge/Mol*-4.9.0-1a6b8f) ![pytest](https://img.shields.io/badge/pytest-286%20passing-0A9EDC?logo=pytest&logoColor=white) ![data](https://img.shields.io/badge/data-GPCRdb%20%C2%B7%20KLIFS%20%C2%B7%20PDBe-467FF7) ![licence](https://img.shields.io/badge/licence-MIT-467FF7) ![author](https://img.shields.io/badge/author-Marc%20C.%20Deller%2C%20D.Phil.-1C244B)

<table>
<tr>
<td>🌐 <b>Website</b></td><td><a href="https://boltzmaker.mdeller.com" target="_blank" rel="noopener noreferrer">boltzmaker.mdeller.com</a></td>
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
The non-GPU stages -- the `new` wizard, `generate`, `preflight`, and full `analyze`
(including PLIP interaction detection and compare-sse) -- are also available with no local
install at **[boltzmaker.mdeller.com](https://boltzmaker.mdeller.com)**; only the GPU
`run` step still needs your own hardware (see **Web deployment** below).

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

## 📥 Installation

Three ways to run BoltzMaker. **Path 1 installs nothing at all** and is the fastest way to
see what the pipeline does; Paths 2 and 3 install it properly on your own machine, and differ
only in whether that machine has internet access. (Looking for more detail or troubleshooting
on either install path? See **One-time setup** and `docs/tier_b_offline_install.md` further
down.)

| | What it is | Best when |
|---|---|---|
| **Path 1: Web app** | Use it in the browser at [boltzmaker.mdeller.com](https://boltzmaker.mdeller.com). Nothing to install. | You want to try it, build a campaign spec, or analyse results you already have. |
| **Path 2: Normal install** | Full local install on a machine with internet access. | You are running real campaigns on your own GPU. |
| **Path 3: Offline install** | A single self-extracting installer built elsewhere and carried across. | The machine is airgapped or behind a firewall. |

### Path 1: Web app (no install)

Everything except the GPU prediction step runs at
**[boltzmaker.mdeller.com](https://boltzmaker.mdeller.com)**. Real structure prediction needs a
GPU, which the server does not have, so that one step always happens on your own hardware.
The site opens on a choice of two ways to work.

**Fully Automated Mode** is two steps and is the one to pick if you just want a campaign run
end to end:

1. **Prepare.** Describe your proteins, partners and ligands in the form, choose how hard to
   push your hardware, and download a single self-extracting bundle. It carries the campaign
   spec, BoltzMaker itself, a pinned environment covering Boltz-2 and the whole analysis
   stack, and the scripts that run them.
2. **Analysis.** Run that bundle on a machine with a GPU (double-click it on macOS, or
   `sh ./boltzmaker_<campaign>.command` from a terminal) and it installs the environment,
   runs the whole pipeline, and
   writes one `.bmz` results file. Upload that file back to the site to explore your campaign:
   a sortable table of every target, a confidence-versus-affinity triage plot, and per-target
   3D pose viewers with the protein-ligand interactions that were detected.

**Stepwise Mode** exposes the same non-GPU stages as four separate tools: the campaign
**Wizard**, **Generate**, **Preflight**, and **Analyze**. Pick this when you already have your
own setup and want one piece of it, rather than the whole pipeline.

Full detail on both, including every option and what the `.bmz` file contains, is in
**Web deployment** below.

### Path 2: This computer has internet access

**1.** Open the **Terminal** app (Applications -> Utilities -> Terminal, or search for
"Terminal" with Spotlight), then make a folder for BoltzMaker and go into it:

```sh
mkdir -p ~/Desktop/BoltzMaker
cd ~/Desktop/BoltzMaker
```

**2.** Download BoltzMaker into that folder:

```sh
git clone https://github.com/bellcheddar/BoltzMaker.git .
```

(the trailing `.` tells it to put the files directly into the folder you just made,
rather than inside another new folder). If this is the first time you've used `git`,
macOS may pop up a dialog asking to install "Command Line Tools" -- click Install and
wait for it to finish, then run the command again.

**3.** Run the installer:

```sh
./install.sh
```

Wait for it to finish. It downloads a few GB of software the first time, so it can
take a while depending on your connection.

**4.** Check it worked:

```sh
pixi run preflight examples/t4_lysozyme/boltz_input.md
```

If you see a table of green PASS results, you're ready to go -- see **Commands**
below for what to run next.

### Path 3: This computer has no internet access

Use this for a lab machine, server, or any computer that's offline or behind a
firewall. You'll need a second computer that *does* have internet access to prepare a
single installer file first.

**1.** On the computer **with** internet access, follow **Path 2** above, then build
the offline installer file:

```sh
pixi global install pixi-pack
pixi-pack --platform osx-arm64 --ignore-pypi-non-wheel --create-executable -o boltzmaker-installer.sh
```

(use `--platform linux-64` instead of `osx-arm64` if the offline computer runs Linux)

**2.** Copy `boltzmaker-installer.sh`, together with the whole `BoltzMaker` folder,
onto the offline computer (USB drive, internal network transfer, etc.).

**3.** On the offline computer, in a terminal, go to where you copied those files and
run:

```sh
./boltzmaker-installer.sh -o ./boltzmaker-env
source ./boltzmaker-env/activate.sh
export KMP_DUPLICATE_LIB_OK=TRUE
```

**4.** Check it worked:

```sh
python3 BoltzMaker.py preflight examples/t4_lysozyme/boltz_input.md
```

Full details, including a couple of one-time extra steps this path needs, are in
[`docs/tier_b_offline_install.md`](docs/tier_b_offline_install.md).

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
self-downloaded [micromamba](https://micro.mamba.pm) -- macOS `osx-arm64`/`osx-64` and
Linux `linux-64`/`linux-aarch64` are all resolved from the running platform, so this
works on a Linux server as well as a Mac, ~1-1.5GB, mostly PyMOL's own Qt/
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

Two things worth knowing about how that fallback feeds DSSP, both of which used to break
it. The chain is written to a temporary legacy-PDB file first, whose chain-ID field is a
single character -- but BoltzMaker's own chain names are the family id verbatim (up to 5
characters), so any real multi-character family id raised "chain name too long for the PDB
format". The temporary copy is now renamed to `A` before writing; it is a throwaway DSSP
input, and only residue numbers and SSE kind are read back out, so nothing you see is
affected. Separately, `gemmi` emits no `HEADER` record for a structure built purely in
memory, and `mkdssp` >= 4 then mis-sniffs the headerless file as mmCIF and refuses to parse
it, so a minimal synthetic `HEADER` line is prepended. Its content is never read.

### Alternative: `pixi` (one unified environment, macOS + Linux/CUDA)

```sh
./install.sh
```

Installs [`pixi`](https://pixi.sh) if it isn't already on your machine, then solves and
installs everything (`boltz`, `rdkit`, PLIP's OpenBabel/PyMOL stack, and the rest of
`requirements.txt`) as **one** environment from `pixi.toml`/`pixi.lock`, replacing the
need to separately run `setup` + `setup-plip` above. Reproducible (the committed
`pixi.lock` pins every package on both `osx-arm64` and `linux-64`), and the only path
here that's actually tested against Linux/CUDA rather than macOS/MPS alone. Once
installed:

```sh
pixi run preflight my_campaign.md
pixi run all my_campaign.md
```

(or `pixi shell` to activate the environment directly and run `python3 BoltzMaker.py
...` as normal). PLIP needs one extra one-time step, same spirit as `setup-plip` above:
`pixi run postinstall`.

**No internet on the target machine at all?** See
[`docs/tier_b_offline_install.md`](docs/tier_b_offline_install.md) for building a single
self-extracting installer script per platform (`pixi-pack --create-executable`) that
needs no `pixi`, no `conda`, and no network to run.

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
| `--json` | off | `preflight` only: emit the check results as a JSON array on stdout instead of the rich table, for scripting and tooling (this is what the hosted web app consumes). The banner is suppressed alongside it, exactly as it is for `format`, so stdout stays parseable |

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

## ⚙️ Progress, and how long a run will take

Two rows during `run`, laid out as a metrics rail: a state mark, a label, the bar, then every
measurable value right-aligned in a fixed-width column.

```
▶ targets    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/15  2h14m   ~3h40m
  structure  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━        18m04s  ▓▓▓░░░░░  21.4/69G
```

The top row is the campaign: targets done, elapsed, and the estimate. The second is the
**phase** Boltz is in (MSA generation / structure prediction / affinity prediction), parsed
from its log output, with its own clock and the memory gauge.

Only the bar is elastic. Everything else has a fixed width and is right-aligned in tabular
figures, so digits sit under digits and a phase name changing length no longer drags the row
sideways. The state mark replaces the second spinner: <span>▶</span> running,
<span>⏸</span> paused, <span>■</span> stopping, always in the same column.

**The memory gauge is filled against the point this machine starts to hurt, not against
installed RAM** -- the same `MEMORY_THRASH_FRACTION` the swap-thrash warning uses. A 4-chain
GPCR complex took ~65GB on a 64GB Mac and thrashed for 20 minutes with no progress; measured
against total memory that run would have looked merely "quite full" until the moment it died.
The gauge turns amber at 60% of that ceiling and red at 85%, so it changes colour before the
log starts complaining rather than after.

**Boltz exposes no diffusion- or recycling-step-level progress** anywhere in its output
(verified against the installed package's source), so that is the finest granularity
available -- and on a single-target campaign it is not fine at all: Boltz's own progress
bar counts dataloader items, one target is one item, so it renders `0/1` at the start,
`1/1` at the end, and nothing whatsoever in between. A run can therefore sit at `0/1` for
an hour while working perfectly.

Two things follow, and both are deliberate:

- The inner bar **pulses** rather than showing a static empty bar, and carries our own
  "N in this phase" clock. Boltz's `it/s` figure is shown only while it is actually being
  refreshed; once it goes stale (60s without an update) it is replaced by that clock,
  because a rate string written once at the start and displayed for an hour is a stale
  snapshot presented as live data.
- The ETA is **estimated, and says where the estimate came from**. Once a target completes,
  it is measured from this run. Before that, it comes from the median seconds-per-target of
  previous runs of the same campaign on the same accelerator, read from
  `.boltzmaker_run_history.jsonl` (median, not mean, so one swap-thrashing run does not
  set expectations for every run after it). With no history at all it says so rather than
  inventing a number.

Sizing a first run on new hardware is therefore genuinely unknown until one target lands.
`--limit 1` is the cheapest way to find out: it runs a single target, which both gives you
a real number and writes the history entry every later run estimates from.

### Controls while a run is going

On a real terminal, `run` takes two single keypresses. (Under `nohup`, a pipe or CI there is
no keyboard to read, and it says so rather than appearing to offer them.)

| Key | What it does |
|---|---|
| `p` | **Pause / resume.** A real `SIGSTOP` of Boltz and every worker it started, not a soft flag: the processes are frozen exactly where they stood and `p` again continues them mid-diffusion. Nothing is discarded and nothing is recomputed. |
| `q` | **Quit.** Stops Boltz and all its worker processes, writes the run-history entry, and exits cleanly. Identical to Ctrl-C, which takes the same path. |

Two things worth knowing about pause. A paused run **keeps everything it holds** -- RAM, and
the GPU allocations with it -- because that is what makes it resumable in place. It is the
right tool for "I need the machine for ten minutes", and the wrong one for "pause this until
tomorrow"; for that, quit and re-run, since `run` skips targets that already completed.

Paused time is also excluded from the ETA and recorded separately in the run history
(`working_seconds` alongside `duration_seconds`), so a run paused over lunch does not teach
every later run that targets take an extra hour.

Quitting tears down the **whole process tree**, not just the process BoltzMaker launched.
Boltz runs its dataloader workers as children, and terminating only the parent left them
alive holding their share of RAM and the GPU -- measured on a real two-worker tree, and now
covered by a test.

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

## 🌐 Web deployment

**Live at [boltzmaker.mdeller.com](https://boltzmaker.mdeller.com).** A Flask frontend for the
non-GPU stages of the pipeline. The GPU `run` step is deliberately never hosted: there's no
GPU on the droplet, so that stage always runs on your own hardware.

The site opens on a choice of two ways to work: **Fully Automated Mode**, which hands the
whole pipeline to you as one downloadable bundle, and **Stepwise Mode**, which exposes the
same non-GPU stages as four separate tools.

### Fully Automated Mode

#### Step 1: Prepare

Describe the campaign in the form: a **name**, whether to **predict binding affinity**, then
your **partners** (optional co-folded chains), **proteins**, **constraints** (pocket contact,
covalent bond, or distance), and **ligands** (SMILES or CCD code). These are the same fields
`BoltzMaker.py new` asks for in the terminal, and the same 5-character shared-namespace rule
applies to every short name.

Everything you type is kept in your browser as you go, so downloading a bundle, stepping over
to Analysis, or reloading does not lose it. Three buttons sit under the campaign name:

| Button | What it does |
|---|---|
| **Save page** | Writes everything currently entered to a small `<campaign>.boltzpage.json` file. Keep it as a record of a campaign, or send it to a colleague. |
| **Upload page** | Reads one of those files back in, replacing what is on the form. |
| **Clear** | Forgets the saved state and empties the form. Asks first. |

Then choose the run settings. Every one maps to a real `BoltzMaker.py` flag, and each is
written literally into the generated script so you can read exactly what will run:

**Prediction settings**

| Setting | Flag | Default | What it does |
|---|---|---|---|
| Accelerator | `--accelerator` | auto | auto picks your GPU (CUDA or Apple MPS) when there is one. cpu works but is slow enough that it is really only for checking a campaign runs at all. |
| Data-loading workers | `--workers` | 2 | Matches Boltz's own default of 2. Lower it to 0 if you hit memory pressure on a Mac. |
| Parallel diffusion samples | `--max-parallel-samples` | 1 | How many diffusion samples Boltz holds in memory at once. 1 is the safe default on unified-memory hardware; raising it multiplies peak memory. |
| MPS high-watermark ratio | `--mps-watermark` | 1.0 | Apple Silicon only (PYTORCH_MPS_HIGH_WATERMARK_RATIO). Caps how much unified memory PyTorch will claim before it errors instead of swap-thrashing. Ignored elsewhere. |
| Recycling steps | `--recycling-steps` | Boltz default | Leave blank for Boltz's own default. More steps is slower and usually only marginally better. |
| Sampling steps | `--sampling-steps` | Boltz default | Leave blank for Boltz's own default. |
| Structure samples per target | `--diffusion-samples` | Boltz default | Leave blank for one sample per target. Each extra sample costs roughly its own share of diffusion time, and analysis only ever reads the first one (model_0) -- so raise it to inspect pose variability yourself, not to improve the report. |
| Affinity diffusion samples | `--diffusion-samples-affinity` | Boltz default | Leave blank for Boltz's own default. Only matters for targets with affinity prediction switched on. |
| Affinity sampling steps | `--sampling-steps-affinity` | Boltz default | Leave blank for Boltz's own default. |
| Max MSA sequences | `--max-msa-seqs` | Boltz default | Leave blank for Boltz's own default. Lowering it is one of the few levers that meaningfully cuts memory on very large complexes. |
| Auto-retries per target | `--max-retries` | 2 | A target that fails (typically an out-of-memory kill) is retried in isolation, one target at a time. 0 disables retrying. |
| Preflight size-warning threshold | `--memory-warn-tokens` | 1000 | Preflight warns when a target's combined residue/atom count exceeds this. It is a warning, not a limit. |

**Scope and safety**

| Setting | Flag | Default | What it does |
|---|---|---|---|
| Only run the first N targets | `--limit` | Boltz default | Leave blank to run the whole campaign. Setting it to 1 or 2 is the cheapest way to prove the pipeline works before committing hours of GPU time. |
| Treat preflight warnings as failures | `--strict` | off | Stops the run before any GPU time is spent if preflight raises any warning at all. |

**Analysis**

| Setting | Flag | Default | What it does |
|---|---|---|---|
| Skip PLIP interaction analysis | `--skip-interactions` | off | Leave off. PLIP is what produces the per-target interaction fingerprints the Analysis step shows; skipping it saves minutes but empties that panel. |
| Skip apo-vs-holo compare-sse | `--skip-sse` | off | Left off, every protein gets an apo reference so the comparison can run: an experimental structure if you gave a PDB id above, otherwise an extra ligand-free prediction of that protein. Those extra targets cost GPU time -- one more target per protein. Tick this to skip the comparison and predict nothing extra. |
| Keep private | _(this site only)_ | off | Nothing about this run is kept on the server: the bundle is not archived, and the results file you upload later is recognised as private and not archived either. Leave it off and the run is listed under Runs, where you can download the bundle and results again later. |

Submitting validates the spec (`format`, then `generate`, so a broken campaign fails here
rather than an hour into a run on your machine) and downloads
`boltzmaker_<campaign>.command`, typically around 200KB. It contains:

| File | What it is |
|---|---|
| `boltz_input.md` | Your campaign spec, tidied to the house style. Editable. |
| `sse_comparison/`, `vendor/` | The compare-sse package BoltzMaker imports during `analyze`, and the Plotly and 3Dmol builds the offline dashboard embeds. `vendor/` is most of the bundle's size and is included so the run needs nothing from the network beyond the model weights. |
| `config.json` | The run settings, machine-readable. Provenance; not read at run time. |
| `run_campaign.sh` | Installs the environment, runs the campaign, packs the results. |
| `pack_results.py` | Writes the `.bmz`. |
| `BoltzMaker.py` | The pipeline itself. |
| `pixi.toml`, `pixi.lock` | The pinned environment, locked for macOS (Apple Silicon) and Linux (x86-64). |

To run it, move the downloaded file to the machine with the GPU, put it wherever you want the
campaign to live, and either double-click it in Finder or run it from a terminal in that
folder:

```sh
sh ./boltzmaker_<campaign>.command
```

`sh` is fine on any platform: the file re-execs itself under bash on its first line, so it
behaves the same whether your `/bin/sh` is bash (macOS) or dash (most Linux distributions).
`bash ./boltzmaker_<campaign>.command` and `./boltzmaker_<campaign>.command` (once executable)
work equally well.

It unpacks into a folder beside itself and starts immediately: it installs
[pixi](https://pixi.sh) if you do not have it, solves the environment, then runs `generate` ->
`preflight` -> `run` -> `analyze` and writes one `<campaign>.bmz` file in that same folder.
Bring that one file back to the site for Step 2. **Boltz-2's model weights are not in the bundle** --
they are large and versioned by Boltz itself, so they download on first use and are cached in
your home directory, meaning a second campaign skips that step.

Each long step -- solving the environment, installing PLIP, warming the Boltz CLI -- shows a
spinner with its elapsed time and reports how long it took, so a terminal that has not moved
in four minutes is never ambiguous. If a step fails, the last twenty lines of its log are
printed rather than left in a file you have to go and find.

It is safe to re-run at any point. `run` is idempotent, so an interrupted campaign resumes
rather than starting over, and the script refuses to overwrite an existing unpacked folder.
If the campaign fails part-way it still packs what completed, and records the shortfall in the
results file rather than hiding it.

The bundle runs the whole pipeline including `analyze`, not just `run`. Once a machine has
the pinned environment, analysis costs seconds more there, and doing it locally is what lets
the droplet skip a ~1.5GB PLIP environment and a 900-second request for work your machine has
already done. What comes back is small and already structured (measured on a real 15-target
campaign: 4.2MB, against a 19.4MB dashboard and 50.6MB of PyMOL sessions that deliberately
stay on your own disk), so Analysis is a reader rather than a compute step.

#### Step 2: Analysis

Upload the `.bmz` and the campaign opens as an interactive report. Nothing is recomputed, so
it is quick regardless of campaign size.

| Panel | What you get |
|---|---|
| **Header** | Campaign name, how many predictions the campaign produced, how many are flagged, how many carry a structure. An explicit warning if targets are missing from the summary because the campaign did not fully complete. |
| **Targets** | Sortable, filterable table: target, family, ligand, confidence, pIC50, interaction count and flags. Filter by free text, by family, or to flagged targets only. Click any row to open it. |
| **Target detail** | Its heading is the target picker, so the panel both names the open target and changes it. Four equal panes: a [Mol*](https://molstar.org) pose viewer coloured by chain, a second Mol* viewer framed on the ligand and its contacting residues and turning on load (both with cartoon/surface/spin/reset, and an **AlphaFold** button that overlays that protein's AlphaFold model, superposed server-side on the confident core -- pLDDT >= 70 -- and reporting the accession, how it was resolved, how many Ca it was fitted on and the RMSD), every PLIP contact grouped by type -- residue name, number and chain, the distance, and the geometry that belongs to that interaction (donor and acceptor atom types and the donor angle for a hydrogen bond, the T/P classification and ring offset for a stack, the charge sense and ligand group for a salt bridge) -- and the full metric set including pTM, ipTM, complex pLDDT, predicted affinity, pIC50 with its ensemble spread, and the Ca RMSD to the apo reference (the residue-weighted mean across the motifs compare-sse could align, with that motif count beside it), with this target's ligand depiction filling the space below it. Below them, full width, the target's sequence: a per-residue track coloured by property with the PLIP contacts marked, and above it a conservation logo aligned across every distinct protein in the campaign, drawn in bits of information. Hovering a residue names it and lists its contacts and its conservation; clicking one selects and frames it in both viewers, as does clicking a contact. Open on the first target from the start, rather than waiting for a click that on a one-target campaign there was nothing to make. |

Everything else on the page comes from BoltzMaker's own reports, and the whole sequence --
this page's panels and the reports' -- is one ordered list in `reports.PANEL_ORDER`, so
reordering the page is a line moved rather than a template edit. It opens on the campaign
summary. BoltzMaker's own **pIC50 vs confidence score** scatter is the one kept, and it is
wired up here so clicking a point opens that target.

Beneath those panels sit **BoltzMaker's own**, lifted out of the reports it generated and
rendered as siblings: the campaign summary, ligand preparation, the 2D ligand structures,
ranked pIC50 and confidence, the family-by-ligand selectivity heatmap, interaction counts,
pIC50 against binder probability, a residue interaction fingerprint per family, and the
secondary-structure tables and charts. Twenty panels on a real campaign, against the two the
explorer draws itself. Both reports can still be downloaded whole.

They are lifted rather than reimplemented, so they cannot drift from the analysis code, and
merged rather than framed, so the page does not become a scrolling document inside a card.

**Nothing from the results file executes.** It is user input rendered on this site's own
origin, so the markup is reduced to a tag allowlist by a tokeniser -- not a regex, which was
defeated by a `<` inside a quoted attribute -- and every chart is rebuilt from its data: each
`Plotly.newPlot` call has its arguments JSON-parsed on the server and handed to the page as
values, which the page's own code then plots. Parsed and re-serialised, an injected payload is
inert text.

Two things are deliberately dropped. The reports' binding-site panels, because the explorer
already gives every target a pose viewer with its interactions beside it and the PyMOL sessions
they link to are not in the archive; and the compare-sse charts the dashboard embeds, because
the compare-sse page carries the same charts under the same element ids, and rendering both
would put two divs with one id on the page -- leaving the second unreachable and silently
undrawn.

Two things worth knowing about the plot. The dashed vertical line at **0.5** is BoltzMaker's
genuine absolute low-confidence cutoff. The mismatch flags (`HIGH_CONFIDENCE_POOR_AFFINITY`,
`LOW_CONFIDENCE_STRONG_AFFINITY`) are **not** absolute: BoltzMaker assigns them by splitting
*that campaign* into terciles, so they mean "relative to the other targets you ran", and there
is deliberately no horizontal affinity threshold line, because drawing one would imply a fixed
cutoff the numbers do not support.

An open target is deep-linkable -- the URL carries it, so a link to one target can be shared
or reloaded. **Sessions do not expire on a clock**: an analysis link keeps working, and uploads
are removed only when the space set aside for them fills, least recently opened first. The
**Download summary CSV** button gives you the full summary table including every column not
shown in the browser.

A note on vocabulary: BoltzMaker calls each `Protein:` block a **family**, and its own reports
use that word throughout. A campaign with one receptor and an apo companion therefore has two
families, which reads oddly, so this page says **protein** for the same thing and counts
**predictions** rather than families.

### Stepwise Mode

The same non-GPU stages as four independent tools. Each takes an upload and hands back a
download, and none of them depends on the others, so you can use just the one you need.

| Tool | You give it | You get back |
|---|---|---|
| **Wizard** | Answers to the same plain questions as `BoltzMaker.py new` | A validated, tidied `boltz_input.md` |
| **Generate** | A `boltz_input.md` (paste or upload) | `boltz_yamls.zip`: the per-target YAMLs plus the manifest |
| **Preflight** | A `boltz_input.md` | The full check table: SMILES and ligand chemistry, chain-id lengths, duplicate targets, size heuristics. The GPU and model-weight checks report on the server, not your machine, so read those on your own hardware instead. |
| **Analyze** | A zip of a completed campaign folder (`boltz_input.md` + `boltz_yamls/` + `boltz_output/`, plus any `Apo structure:` files) | The summary CSV/XLSX, the interactive dashboard rendered in the page, and a zip of everything including the CIFs, PLIP output and compare-sse results |

Use Stepwise when you already have your own setup and want one piece of it; use Fully
Automated when you want the whole pipeline handled.

### Runs

The landing page carries the five most recent, with a link straight into each one's analysis.
The full table is at **/runs**: everything not marked private, in one place: campaign, when it was prepared, target count,
the bundle, and the results file once uploaded. Each row offers the bundle and the `.bmz`
for download, and **explore**, which re-opens the analysis from the archived results without
uploading anything again.

The archive is **capped** -- 3GB and 200 runs -- and prunes oldest-first when it fills, with
each removal recorded so a missing run is explainable rather than a mystery. The host this
runs on has ~16GB free and also serves three other apps, so an uncapped archive would be a
slow-motion disk-full outage.

### Limits, and what to do when something goes wrong

| Situation | What is happening |
|---|---|
| Upload rejected as too large | Uploads are capped at **200MB**. The packer aims below that (it stops at 180MB, dropping the largest structures first and recording each one in the manifest), so hitting this usually means an unusually large campaign. Analyse it locally with `boltz_dashboard.html` instead. |
| "This results file declares format version N" | The `.bmz` was written by a different version of the bundle than the site understands. Prepare a fresh bundle and re-pack; the file itself is not damaged. |
| "No manifest.json in the upload" | A campaign folder was uploaded instead of the `.bmz`. Either upload the `.bmz` the bundle wrote, or use Stepwise Mode's **Analyze**, which is the tool that takes a campaign folder. |
| Some targets have no pose viewer | Those structures were dropped to stay under the size limit, or the target failed. `manifest.json` inside the `.bmz` records which, and why. They are still in `boltz_cif/` on your own machine. |
| The 3D viewer says WebGL is unavailable | The browser has WebGL disabled or unsupported. Everything else on the page is unaffected. |
| Preflight fails on `sse_comparison` or `result_packer` | The bundle is incomplete -- re-download it. Both are checked before any GPU time is spent precisely because `analyze` imports them only at the end, so a missing file used to surface after the prediction had already finished. |
| Preflight warns on `vendor_assets` | Plotly or 3Dmol is missing from `vendor/`, so the dashboard will reach for a CDN and will not render offline. The run itself is unaffected. |
| Preflight warns `boltz_cli` did not answer `--help` in 120s | A cold first import, not a broken install: `boltz --help` loads the whole torch stack, and a freshly solved environment byte-compiles it too. The bundle warms it before the campaign, and it is a warning that does not stop the run. |
| The interactions panel is empty | PLIP either did not run for that target, or found nothing. If you switched **Skip PLIP interaction analysis** on when preparing, that is the cause. |
| A session link stops working | Sessions expire after two hours. Upload the file again; nothing is lost, since the `.bmz` is on your own disk. |

### How it is built and served

**Source and tested-CLI isolation.** The web app lives in `web/`. It was developed on a
separate `web` branch/worktree so that web-app work could never disturb the tested
`BoltzMaker.py`, and has since been merged into `main` -- the isolation that matters is
now the process boundary described next, not a branch boundary. `BoltzMaker.py` was never
designed to be imported (it relaunches itself into a managed
venv at module import time), so the Flask app only ever invokes it as a subprocess, with an
explicit minimal environment and a per-command timeout, through a dedicated trimmed venv
(`.venv/`, torch/boltz-free, ~500MB -- every torch/boltz reference in the script is a
function-local lazy import) kept separate from the Flask-serving venv (`web/.venv/`).

**The `.bmz` results file.** A zip carrying `manifest.json` (format version, campaign name,
timestamps, a SHA-256 of the `BoltzMaker.py` that produced it, per-file checksums, and an
explicit record of anything not packed), the summary CSVs, one structure per target, and one
labelled PLIP image per target. Its layout is written by the bundle's generated
`pack_results.py` and read by `web/boltzmaker_web/results.py`; both mirror one `BMZ_VERSION`,
and a file declaring any other version is refused rather than parsed optimistically. Uploads
are treated as hostile: extraction is bounded on entry count, declared size, actual written
size, compression ratio and resolved path, with every check run over the whole member list
before a single byte is written.

**Optional PLIP.** If the droplet's `.plip_env` (the same conda-forge PyMOL/OpenBabel
environment `setup-plip` builds locally, ~1-1.5GB) is present, `analyze` runs full
protein-ligand interaction detection and compare-sse automatically; if not, both degrade
gracefully rather than erroring, exactly as they do locally.

**Serving stack:** gunicorn (3 sync workers, 900s timeout to cover PLIP rendering and
compare-sse's GPCRdb/KLIFS/PDBe lookups) behind nginx (Let's Encrypt TLS via certbot, HTTP/2,
rate-limited upload endpoints, 200MB body cap), as a hardened systemd service (dedicated
unprivileged user, memory/CPU caps). Every request gets its own scratch directory, deleted
when the request finishes and swept by a five-minute cleanup timer as a backstop; uploaded
zips are checked for zip-slip and zip-bomb payloads (path-traversal/absolute-path rejection,
uncompressed-size and entry-count caps) before anything is extracted.

## 🧫 Testing

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/
```

286 tests. The `compare-sse` annotators are covered against real fixture data (a real apo EGFR
kinase-domain structure vs the `egfr_covalent` example's real holo prediction; a real
apo beta2-adrenergic-receptor structure vs `adrb2_gs_panel`'s real holo predictions),
with GPCRdb/KLIFS/PDBe network calls swapped for an injectable fake client seeded with
real, previously-verified API responses -- fully offline and fast (~9s). Plus grammar
and CLI-resolution tests for the parser fields above, chain-resolution tests against real
fusion-construct and kinase-domain-only apo structures, GPCRdb/KLIFS/Pfam annotator
pipelines, and the dashboard's summary-stats and SSE-table column logic.

The web app's own 53 tests cover Fully Automated Mode end to end. Rather than asserting
against a hand-written `.bmz` fixture, they render the real `pack_results.py` out of a real
bundle, run it over a synthetic campaign, and read the result back with the real reader --
the packer and the reader are two halves of one contract living in different files and
running on different machines, which is exactly the shape of thing that drifts silently.
Also covered: the generated bundle is really executed under `sh`, `bash`, `dash`, `zsh` and
`ksh` (with its final step stubbed) to prove the documented `sh ./<bundle>.command` works where
`/bin/sh` is dash as well as where it is bash, the generated scripts are checked with `bash -n`
(they only ever execute on someone else's machine), every run-setting flag is checked against `BoltzMaker.py all
--help` so a typo cannot reach a user's overnight run, and the hostile-upload guards are
exercised with real zip-slip, compression-bomb and malformed-manifest archives.

Note that four `compare-sse` tests need example structure data that is gitignored
(`examples/*/boltz_cif/`), so they fail in a fresh clone until you have run one of the
example campaigns.

## 📚 Citation

> Passaro, S., Corso, G., Wohlwend, J., Reveiz, M., Thaler, S., Somnath, V.R., Getz, N., Portnoi, T., Roy, J., Stark, H., Kwabi-Addo, D., Beaini, D., Jaakkola, T., Barzilay, R. (2025). Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction. *bioRxiv*. https://doi.org/10.1101/2025.06.14.659707

> Mirdita, M., Schütze, K., Moriwaki, Y., Heo, L., Ovchinnikov, S., Steinegger, M. (2022). ColabFold: making protein folding accessible to all. *Nature Methods*. https://doi.org/10.1038/s41592-022-01488-1

> Schake, P., Bolz, S.N. et al. (2025). PLIP 2025: introducing protein-protein interactions to the protein-ligand interaction profiler. *Nucleic Acids Research*, gkaf361. https://doi.org/10.1093/nar/gkaf361

> The PyMOL Molecular Graphics System, Version 3.1, Schrödinger, LLC.

> Rego, N., Koes, D. (2015). 3Dmol.js: molecular visualization with WebGL. *Bioinformatics*, 31(8), 1322-1324. https://doi.org/10.1093/bioinformatics/btu829

## 📄 License

[MIT](LICENSE) &copy; Marc C. Deller

## 📋 To do

- [x] Run a real GPU campaign end to end -- prepared on the site, run from the bundle, packed, uploaded and explored. Four bundle defects had reached a user before this (a preflight timeout too short for a cold torch import, `sse_comparison` and `vendor` missing from the bundle, pre-1980 zip timestamps, `sh` portability), because everything up to the campaign is verified automatically while the `pixi install` -> `boltz predict` -> `analyze` path is not. Worth repeating before each release
- [x] Show everything the dashboard computes in the hosted Analysis step, not only the two panels the explorer draws itself. BoltzMaker's own generated reports now travel inside the `.bmz` and are framed beside the interactive panels, so the hosted view cannot drift from the offline one
- [x] Give every protein an apo reference so compare-sse can actually run from the web form: a predicted ligand-free companion by default, an experimental PDB entry when one is named (mmCIF preferred, since most recent cryo-EM entries have no legacy file), or both. Previously the form emitted no `Apo structure:` at all, so the comparison never ran and its skip option had nothing to skip
- [x] Add **Keep private** and a **Runs** tab: the decision travels in the user's own files (the bundle records it, the packer copies it into the results manifest) so a private run leaves nothing on the server to list, while everything else is archived with its bundle and results under a capped, self-pruning archive
- [x] Add single-keypress run controls: `p` pauses and resumes via a real SIGSTOP of the whole Boltz process tree, so an interrupted target is neither discarded nor recomputed, and `q` stops the run and all its workers cleanly. Fixed a leak found on the way: terminating only the parent left dataloader workers alive holding RAM and the GPU
- [x] Replace the run's dead `-:--:--` with an ETA that says where it came from -- measured from this run once a target completes, otherwise the median seconds-per-target of past runs of the same campaign on the same accelerator -- and make the phase row honest about the fact that Boltz reports nothing between dataloader items
- [x] Preflight the bundle's own contents (`sse_comparison`, the vendored dashboard assets, the results packer), since all three are read only after the prediction finishes and a missing one used to cost the whole run before announcing itself
- [x] Keep everything typed into the Prepare form across a download, a visit to Analysis or a reload, and let it be saved to and loaded from a small `.json` file
- [x] Split the hosted site into two modes: a **Fully Automated** two-step flow (configure a campaign, download one self-extracting bundle carrying the software, environment and scripts; run it locally; upload the single `.bmz` results file it writes) and the original **Stepwise** four-tool flow, chosen from a two-panel landing page
- [x] Give the Analysis step real exploration rather than an embedded report: a sortable, filterable target table, a confidence-versus-affinity triage plot coloured by BoltzMaker's own flags, and a per-target 3Dmol.js pose viewer with the detected PLIP interactions beside it -- which also lands the cross-target selectivity/triage view below
- [x] Host the non-GPU stages (`new` wizard, `generate`, `preflight`, full `analyze` including PLIP and compare-sse) as a Flask app at [boltzmaker.mdeller.com](https://boltzmaker.mdeller.com), so the pipeline can be tried with no local install -- the GPU `run` step stays on your own hardware by design
- [x] Add `preflight --json` so the check results can be consumed by tooling rather than scraped from the rich table, with the banner suppressed alongside it (as `format` already did) to keep stdout parseable
- [x] Resolve the right micromamba build from the running platform in `setup-plip`, so Linux (`linux-64`/`linux-aarch64`) works rather than silently fetching a macOS binary on an x86_64 Linux host
- [x] Fix compare-sse's DSSP fallback for real campaigns: multi-character family ids no longer overflow the legacy-PDB chain-ID field, and the temporary structure now carries the `HEADER` line `mkdssp` >= 4 needs to recognise it as PDB at all
- [x] Pin exact dependency versions and add a cached/offline install mode for reproducible installs -- via `pixi.toml`/`pixi.lock` and `install.sh` (see **Alternative: pixi** above and `docs/tier_b_offline_install.md`), not by pinning `setup`/`setup-plip`'s own unpinned `requirements.txt`-driven installs, which remain as they were
- [x] Add a cross-target selectivity/triage view (confidence-vs-affinity quadrant flags for "high-confidence, high-affinity" hits) -- delivered in Fully Automated Mode's Analysis explorer rather than in the offline dashboard; it plots BoltzMaker's own `flags` and draws only the absolute 0.5 confidence cutoff, deliberately not a horizontal affinity threshold, because the mismatch flags are within-campaign terciles rather than absolute cutoffs
- [x] Bundle Plotly.js locally instead of via CDN so the dashboard renders fully offline/air-gapped
- [x] Add a ligand-preparation/validation step (canonicalization, stereocentre/protonation-state flagging, disconnected-fragment detection) so bad input chemistry is caught before hours of compute, not silently mispredicted
- [x] Add a 3Dmol.js rotating structure view to each target's binding-site panel, placed next to the existing static PyMOL image (keep the static image, add a "Download image" link for it -- doesn't exist yet -- and add the interactive 3Dmol.js view alongside rather than replacing anything)
- [ ] Share pip cache between the two environments (`PIP_CACHE_DIR`) so `setup-plip` doesn't re-download wheels the main venv already fetched
- [ ] Add `BoltzMaker.py doctor` -- a post-install check that imports boltz/rdkit/plip/openbabel/pymol in-process and reports exactly which env/feature is broken
- [ ] Add an explicit Boltz model-weights cache dir + a `preflight` check for it (ties into the existing iCloud dataless-file eviction check)
- [ ] Detect the MPS `torch.linalg.svd` CPU-fallback at `preflight` and warn with an estimated runtime multiplier for large multi-chain complexes
- [ ] Add a residue/chain-count-based runtime pre-estimator, plus a toggle to log which ops fall back to CPU on MPS
- [ ] Checkpoint `run` at the per-sample level (not just per-target) so an interrupted multi-hour complex resumes without recomputing completed diffusion samples
- [ ] Add a smoke-test suite: an end-to-end fixture run in CI plus unit tests for the `boltz_input.md` parser and JSON-metric flattening
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
