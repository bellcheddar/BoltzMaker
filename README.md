# 🧬 BoltzMaker

> **BoltzMaker: Boltz2 campaign-scale structure and affinity prediction, binding analysis, and run control, orchestrated end to end from a single spec file.**

[![live](https://img.shields.io/badge/live-boltzmaker.mdeller.com-00d084?logo=icloud&logoColor=white)](https://boltzmaker.mdeller.com) ![python](https://img.shields.io/badge/python-3.12.3-3776AB?logo=python&logoColor=white) ![flask](https://img.shields.io/badge/flask-3.1.3-000000?logo=flask&logoColor=white) ![gunicorn](https://img.shields.io/badge/gunicorn-26.0.0-499848?logo=gunicorn&logoColor=white) ![nginx](https://img.shields.io/badge/nginx-1.24.0-009639?logo=nginx&logoColor=white) ![boltz](https://img.shields.io/badge/boltz-2-00897B) ![rdkit](https://img.shields.io/badge/RDKit-2026.03-00d084) ![gemmi](https://img.shields.io/badge/gemmi-0.6.5-8a3ffc) ![biopython](https://img.shields.io/badge/Biopython-1.84-1a6b8f) ![plip](https://img.shields.io/badge/PLIP-2025-9b51e0) ![pymol](https://img.shields.io/badge/PyMOL-3.1-ff6900) ![plotly](https://img.shields.io/badge/Plotly.js-2.35.2-3F4F75?logo=plotly&logoColor=white) ![3dmoljs](https://img.shields.io/badge/3Dmol.js-3D%20viewer-fcb900) ![molstar](https://img.shields.io/badge/Mol*-4.9.0-1a6b8f) ![pytest](https://img.shields.io/badge/pytest-455%20passing-0A9EDC?logo=pytest&logoColor=white) ![data](https://img.shields.io/badge/data-GPCRdb%20%C2%B7%20KLIFS%20%C2%B7%20PDBe-467FF7) ![licence](https://img.shields.io/badge/licence-MIT-467FF7) ![author](https://img.shields.io/badge/author-Marc%20C.%20Deller%2C%20D.Phil.-1C244B)

<table>
<tr>
<td>🌐 <b>Website</b></td><td><a href="https://boltzmaker.mdeller.com" target="_blank" rel="noopener noreferrer">boltzmaker.mdeller.com</a></td>
<td>✉️ <b>Contact</b></td><td><a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a></td>
<td>🐙 <b>GitHub</b></td><td><a href="https://github.com/bellcheddar/BoltzMaker" target="_blank" rel="noopener noreferrer">bellcheddar/BoltzMaker</a></td>
</tr>
</table>

---

BoltzMaker is for campaign-scale Boltz-2 work: a matrix of receptors x ligands x conditions,
described once and run as one unit, rather than a prediction at a time. One annotated
`boltz_input.md` names the proteins, their co-folded partners, the ligands, the pocket /
covalent / distance constraints and any ligand-free controls; BoltzMaker crosses them into a
target per combination and carries all of them through generation, validation, prediction and
reporting together. The example campaigns below run up to 20 targets from one file, and a real
GPCR panel here ran 26. It is built for structural biologists and drug-discovery scientists
running structure/affinity panels -- covalent-linkage studies, multi-chain SAR and selectivity
matrices, pocket-condition sweeps.

**The way in is [boltzmaker.mdeller.com](https://boltzmaker.mdeller.com), and it installs
nothing.** Every stage but one runs there: describing the campaign (the `new` wizard's questions
as a form), `generate`, `preflight`, and the whole of `analyze` -- PLIP interaction detection and
compare-sse included. Only the GPU `run` step needs your own hardware, so the site hands you one
self-extracting bundle carrying the spec, BoltzMaker and a pinned environment. Run it where the
GPU is, bring back the single `.bmz` it writes, and the site opens the campaign as an interactive
report. Full detail under **Web deployment** below.

Why it matters: hand-running a campaign that size means writing dozens of near-identical YAML
files, remembering the right CLI flags for your hardware, and digging through prediction JSONs
afterwards. BoltzMaker does all three, enriches the result with real protein-ligand interaction
analysis via [cif2plip](https://github.com/bellcheddar/cif2plip), and runs ligand-chemistry
checks -- undefined stereocentres, ambiguous protonation states, stray salts -- so bad chemistry
is caught before hours of compute rather than silently mispredicted.

It installs locally as a single script too, consolidating five earlier single-purpose tools into
one spec-driven pipeline sharing a single campaign format:
[generate_yaml](https://github.com/bellcheddar/generate_yaml) (input YAMLs),
[simple-zsh-script-to-run-boltz2](https://github.com/bellcheddar/simple-zsh-script-to-run-boltz2)
(driving `boltz predict`),
[analyze-boltz2-results](https://github.com/bellcheddar/analyze-boltz2-results) (post-run
analysis), [cif2plip](https://github.com/bellcheddar/cif2plip) (interaction profiling) and
[smiles2grid](https://github.com/bellcheddar/smiles2grid) (a boxed grid of 2D ligand
structures). And yes, the name is a nod to
[Boltmaker](https://www.timothytaylor.co.uk/beer/boltmaker), Timothy Taylor's Champion Beer of
Britain and one of the author's favourites.

See [CHANGELOG.md](CHANGELOG.md) for what's changed recently, and
[PROJECT_PLAN.md](PROJECT_PLAN.md) for the roadmap behind the To-do list below.

## 📥 Installation

Three ways to run BoltzMaker. **Path 1 installs nothing at all** and is where to start; Paths 2
and 3 install it properly on your own machine, and differ only in whether that machine has
internet access.

### Path 1: Web app (no install)

[boltzmaker.mdeller.com](https://boltzmaker.mdeller.com) opens on two ways to work: **Fully
Automated Mode**, the two-step describe-download-run-upload flow above, and **Stepwise Mode**,
which exposes the same non-GPU stages as four independent tools (**Wizard**, **Generate**,
**Preflight**, **Analyze**) for when you already have your own setup and want one piece of it.
Both are documented under **Web deployment** below.

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

(the trailing `.` puts the files directly into the folder you just made rather than inside
another new folder). If this is the first time you've used `git`, macOS may pop up a dialog
asking to install "Command Line Tools" -- click Install, wait for it to finish, then run the
command again.

**3.** Run the installer:

```sh
./install.sh
```

It downloads a few GB of software the first time, so it can take a while.

**4.** Check it worked:

```sh
pixi run preflight examples/t4_lysozyme/boltz_input.md
```

A table of green PASS results means you're ready -- see **Commands** below.

### Path 3: This computer has no internet access

For a lab machine, server, or anything offline or behind a firewall. You'll need a second
computer that *does* have internet access to prepare a single installer file first.

**1.** On the computer **with** internet access, follow **Path 2** above, then build the
offline installer file:

```sh
pixi global install pixi-pack
pixi-pack --platform osx-arm64 --ignore-pypi-non-wheel --create-executable -o boltzmaker-installer.sh
```

(use `--platform linux-64` instead of `osx-arm64` if the offline computer runs Linux)

**2.** Copy `boltzmaker-installer.sh`, together with the whole `BoltzMaker` folder, onto the
offline computer (USB drive, internal network transfer, etc.).

**3.** On the offline computer, in a terminal, go to where you copied those files and run:

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

`boltz_input.md` is the family x partners x ligand DSL spec; the four commands that read it
produce:

| Command | Produces |
|---|---|
| `generate` | `boltz_yamls/*.yaml` + manifest |
| `preflight` | PASS/WARN/FAIL: CLI, GPU/MPS, disk, iCloud, YAML/SMILES/chain-id/chemistry, memory |
| `run` | `boltz predict` -> `boltz_output/`, live progress + memory monitor, resumable |
| `analyze` | `boltz_summary.csv`/`.xlsx`, `boltz_dashboard.html`, `boltz_cif/`, plus interaction files if `setup-plip` has run, plus `boltz_sse_comparison.csv`/`.html` for any family with an `Apo structure:` set (see **compare-sse** below) |

Each stage reads only the manifest + files the previous stage wrote, so any stage can be
re-run on its own without repeating the others: `all` simply chains all four.

## 🔧 One-time setup

```sh
python3 BoltzMaker.py setup
```

Creates a dedicated `.venv` (Python 3.12: boltz pins `numpy<2.0`, which has no prebuilt wheel
for newer Pythons) next to `BoltzMaker.py` and installs `boltz`, `rich`, `pandas`, `openpyxl`,
`pyyaml`, `rdkit`, `matplotlib`, `psutil`, `scipy`, `gemmi`, `biopython`, `plotly`, `reportlab`
and `requests`. This pulls PyTorch (~2-3 GB) and, on the first `boltz predict`, several GB of
model weights. Every other command relaunches itself under this managed environment, so you can
keep invoking the script with whatever `python3` is on your PATH. `--force` recreates the venv
from scratch; `-y/--yes` skips the download confirmation prompt.

### Optional: `setup-plip` (protein-ligand interaction analysis)

```sh
python3 BoltzMaker.py setup-plip
```

Entirely optional and separate from the venv above. Builds a `.plip_env` (~1-1.5GB, mostly
PyMOL's own Qt/Cairo/HDF5 dependencies) via a self-downloaded
[micromamba](https://micro.mamba.pm), resolving `osx-arm64`/`osx-64`/`linux-64`/`linux-aarch64`
from the running platform so it works on a Linux server as well as a Mac, and vendors a pinned
commit of [cif2plip](https://github.com/bellcheddar/cif2plip), which converts a Boltz ModelCIF
into a strict PDB and runs [PLIP](https://github.com/pharmai/plip) on it for real interaction
fingerprints (H-bonds, salt bridges, pi-stacking, halogen bonds, metal coordination, etc.).
conda-forge is used deliberately rather than pip, because PLIP needs OpenBabel and PyMOL as
in-process imports and both PyPI routes are broken -- see the first **Troubleshooting** row.

Without `.plip_env` everything degrades gracefully: `analyze` skips interaction analysis (the
dashboard looks exactly as it did before this feature) and the `new` wizard doesn't ask about
reference structures. Nothing else requires it, and `preflight`'s `plip_env` check always
reports which mode you're in.

### Optional: `mkdssp`/`dssp` (for `compare-sse`'s SSE-boundary-shift metric)

Not bundled or installed by any BoltzMaker command -- a small external binary you may already
have (`brew install dssp` on macOS, or `conda install -c salilab dssp`). Only needed for one
`compare-sse` metric (secondary-structure-element boundary shift, used when a structure has
no deposited HELIX/SHEET records -- true for every Boltz-predicted structure). Every other
metric works without it.

Two fixes make that fallback work. The temporary legacy-PDB copy is renamed to chain `A` first,
because its chain-ID field is a single character while BoltzMaker's chain names are the family id
verbatim (up to 5), which raised "chain name too long for the PDB format". And a minimal
synthetic `HEADER` line is prepended, because `gemmi` writes none for a structure built purely in
memory and `mkdssp` >= 4 then mis-sniffs the headerless file as mmCIF and refuses it. Neither is
read back -- only residue numbers and SSE kind are.

### Alternative: `pixi` (one unified environment, macOS + Linux/CUDA)

```sh
./install.sh
```

Installs [`pixi`](https://pixi.sh) if absent, then solves and installs everything (`boltz`,
`rdkit`, PLIP's OpenBabel/PyMOL stack, and the rest of `requirements.txt`) as **one**
environment from `pixi.toml`/`pixi.lock`, replacing `setup` + `setup-plip` above. Reproducible
(the committed `pixi.lock` pins every package on both `osx-arm64` and `linux-64`), and the only
path here actually tested against Linux/CUDA rather than macOS/MPS alone. Once installed:

```sh
pixi run preflight my_campaign.md
pixi run all my_campaign.md
```

(or `pixi shell` to activate the environment and run `python3 BoltzMaker.py ...` as normal).
PLIP needs one extra one-time step, same spirit as `setup-plip`: `pixi run postinstall`. For a
machine with no internet at all, see **Path 3** above.

### Patch the installed `boltz`

Two defects in `boltz` 2.x cost one campaign 14.5 hours and 20 invocations for zero
structures, so BoltzMaker ships fixes:

```bash
python3 patches/apply_boltz_patches.py          # idempotent; keeps a .orig of every file
python3 patches/apply_boltz_patches.py --check  # what preflight runs
```

BoltzMaker applies them itself before every run, so you rarely need the commands above, and
`preflight` shows a `boltz_patches` row because a `pip install -U boltz` silently reverts them.
**What we fixed in Boltz** below describes each one, including the device-correct full-precision
guard around the Kabsch alignment and the NaN diagnostic that names the offending tensor instead
of blaming matrix conditioning.

## 🧪 Examples

Four entirely public-domain campaigns ship in `examples/`; run any with
`python3 BoltzMaker.py all examples/<name>/boltz_input.md`. All four, plus two more that have
no bundled folder, are **public runs with a live interactive report** on the hosted site. The
individual URLs are unguessable, so they are also all listed under the
[**Runs** tab](https://boltzmaker.mdeller.com/runs). The four bundled campaigns were verified
end to end (`generate` -> `preflight` -> real `boltz predict` -> `analyze`, including cif2plip
interaction analysis) on an Apple M1 Max, 64GB.

| Campaign | Targets | Demonstrates | Verified run | Links |
|---|---|---|---|---|
| `t4_lysozyme` | 1 | The minimal shape: one protein (T4 lysozyme L99A, UniProt P00720), one ligand (benzene), no partners, no pocket contacts. Smallest/fastest smoke test | 3m 16s. Confidence 0.98, pIC50 8.9, 7 hydrophobic contacts matching the known L99A cavity residues | [explore](https://boltzmaker.mdeller.com/runs/K-hKV9wI5OYO-t3srj3C5g/explore) · [dashboard](https://bellcheddar.github.io/BoltzMaker/examples/t4_lysozyme/boltz_dashboard.html) · [input](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/t4_lysozyme/boltz_input.md) |
| `egfr_covalent` | 1 | Covalent-linkage modelling: EGFR kinase domain (UniProt P00533) + a generic covalent fragment, linked via `bond_constraints` at Cys797 | 5m 31s. Confidence 0.92, covalent Cys797 SG-to-fragment bond confirmed at 1.75 Angstrom | [explore](https://boltzmaker.mdeller.com/runs/5a_wDBYYltnO3xxJeh73CA/explore) · [dashboard](https://bellcheddar.github.io/BoltzMaker/examples/egfr_covalent/boltz_dashboard.html) · [input](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/egfr_covalent/boltz_input.md) |
| `adrb2_gs` (folder `adrb2_gs_panel`) | 2 | `compare-sse`, and why a co-folded partner should match each ligand's real biology rather than being crossed with everything -- see below | 1h 28m 36s (`ADRB2_ISO1`, agonist+Gs) + 25m 6s (`AR2NG_PRO1`, antagonist alone). Confidence 0.79 (`ADRB2_ISO1`) / 0.83 (`AR2NG_PRO1`) | [explore](https://boltzmaker.mdeller.com/runs/Nutmagij4prtzjYgi_v0LA/explore) · [dashboard](https://bellcheddar.github.io/BoltzMaker/examples/adrb2_gs_panel/boltz_dashboard.html) · [input](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/adrb2_gs_panel/boltz_input.md) |
| `5ht2_gq` (folder `5ht2_gq_panel`) | 15 | `Ligands: none`, a large size-heterogeneous campaign in one manifest, Apple Silicon MPS support for large multi-chain complexes, and `compare-sse` against a *predicted* apo reference -- see below | 9 small targets (apo + receptor-alone) ~4-5m each; 6 large receptor+Gq-heterotrimer complexes ~43-48m each. All 15 completed (12 ligand-bound + 3 apo); confidence 0.66-0.81, iPTM up to 0.99 for the ligand-bound complexes | [explore](https://boltzmaker.mdeller.com/runs/TaRE0NcV9BOpuguKRujt5g/explore) · [dashboard](https://bellcheddar.github.io/BoltzMaker/examples/5ht2_gq_panel/boltz_dashboard.html) · [input](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/5ht2_gq_panel/boltz_input.md) |
| `5HT2A_GQ` | 2 | Public run, no bundled example folder | -- | [explore](https://boltzmaker.mdeller.com/runs/d96nzlk1sj5JzfkNCumscw/explore) |
| `GLP1R_GIPR_pocket_matrix` | 20 | Public run, no bundled folder: two receptors x three ligands x three pocket conditions, plus two apo controls. The campaign behind **How tight should a pocket be?** and **Does the restraint just manufacture the pose?** below, so the live report is where you can see those measurements in situ | -- | [explore](https://boltzmaker.mdeller.com/runs/niSiE5MfGFyddSjGLmeYBA/explore) |

**`adrb2_gs`: a co-folded partner has to match the ligand's real biology.** Beta-2 adrenergic
receptor (UniProt P07550), agonist vs antagonist, written as two separate `Protein:` blocks
sharing one sequence rather than one family crossed with both ligands. The agonist target
co-folds a Gs alpha partner (UniProt P63092); the antagonist target does not, because in
reality Gs only forms a stable complex with the active, agonist-bound receptor. Co-folding it
with the antagonist too made Boltz predict a near-identical active-like fold for both, 0.38
Angstrom apart; splitting them out gets a real conformational difference, 1.28 Angstrom
apart, with the TM6 shift roughly doubled for the agonist.

**`5ht2_gq`: a 3x2x2 panel plus apo controls.** Three serotonin receptors (5-HT2A/2B/2C,
UniProt P28223/P41595/P28335), each with a real agonist/antagonist pair (Psilocin/Risperidone,
LSD/Balovaptan, Lorcaserin/SB-242084), each predicted both with and without the Gq
heterotrimer (GNAQ+GNB1+GNG2) co-folded, plus one native ligand-free (`Ligands: none`) apo
target per receptor. Those apo predictions are each receptor's `compare-sse` reference,
because no genuinely apo experimental structure exists for any of the three (checked
entity-by-entity across all 59 deposited structures). TM6 centroid shift comes out
consistently larger for the Gq-bound targets than their no-Gq counterparts across all three
receptors -- the expected activation signal; full statistical write-up in
[findings.md](https://github.com/bellcheddar/BoltzMaker/blob/main/examples/5ht2_gq_panel/findings.md).

**Run time scales with complex size, not target count.** `ADRB2_ISO1`'s two-chain receptor+Gs
complex took disproportionately longer than the single-chain examples, since attention-style
operations scale worse than linearly with sequence length -- confirmed by `AR2NG_PRO1` (same
receptor, no partner) finishing in a fraction of the time. On Apple Silicon, `torch.linalg.svd`
(used in the diffusion step) also has no MPS implementation and silently falls back to CPU:
worth budgeting for on large multi-chain campaigns.

`5ht2_gq_panel`'s six large 4-chain receptor+Gq targets (~1250-1280 tokens) originally crashed
on Apple Silicon: boltz's triangular attention computes the full row-wise QK^T score matrix for
the whole complex in one unchunked matmul, which exceeds MPS's single-tensor size ceiling past
roughly 1250 residues and crashes inside PyTorch's internal tiled-bmm fallback. Each row's
attention is independent, so chunking along that axis is exact, not an approximation -- `setup`
patches this into the installed `boltz` package (idempotent, and checked against boltz's exact
source so a future upgrade can't be silently mis-patched). `run` also wraps `boltz predict`
with `caffeinate` (macOS only, silently skipped if unavailable) as sleep-prevention hygiene for
long GPU jobs. All 15 targets now complete -- see [CHANGELOG.md](CHANGELOG.md) for the fix.

## 🧭 boltz_input.md format

Plain labelled text -- no markdown, no YAML, no brackets, no quoting. One rule: blocks are
`Label: value` lines with a blank line between them; comments start with `#`. Field names are
plain English (`Output folder`, `Predict affinity`, `Pocket contact`) rather than
Boltz-internal snake_case. Don't want to hand-write it? Run `python3 BoltzMaker.py new` and
answer plain questions instead.

The format has two layers: a **family x partners x ligand cross-product** (the ergonomic
layer -- write each protein/ligand once, get every combination as a separate target), and
standalone **constraint sentences** for the two/three-ended relationships (covalent bonds,
distance constraints) that don't fit inside one block. Each names the protein it belongs to
and can be written anywhere in the file.

```
Settings:
Output folder: ./boltz_yamls    # where generated per-target YAMLs are written
Predict affinity: no            # off by default -- it's a heavier prediction pass
Targets per invocation: 4       # restart Boltz every N targets so the GPU allocator
                                # starts clean -- see "what we fixed", item 2b.
                                # 0 runs the whole batch in one long-lived process

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
# Pocket source: LIG1 from 7XYZ # optional, and repeatable: records which experimental
                                # structure a `Pocket contact:` set was derived from.
                                # Reporting only -- never affects generate/run. Without
                                # it the reference panel reads "not recorded" for that
                                # pocket, and the pose panel can only find the
                                # experimental ligand if that structure happens to be
                                # sitting in `reference/`. Repeat it once per structure
                                # a protein takes a site from; one code claimed by two
                                # structures is an error. A `Pocket source:` line with
                                # NO matching `Pocket contact:` lines is a **reference
                                # molecule**: the structure ships so its bound ligand can
                                # score a matching compound's pose, and it defines no
                                # site, so it adds no targets
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
# Class: control                # optional: control / experimental -- reporting only. Marks
                                # which compounds are the known-answer yardsticks and which
                                # are the ones being asked about, so the charts can outline
                                # the latter without spending a colour on them

Ligand: LIG2
CCD: GOL                        # a Chemical Component Dictionary code (e.g. common crystallization
                                # additives/ions) instead of a SMILES

Covalent bond: RECP1 residue 44 atom SG to LIG1 residue 1 atom C3
Pocket contact: RECP1 residue 148
Distance constraint: RECP1 residue 10 to RECP1 residue 80 within 8.0 Angstrom
```

Every protein is crossed with every ligand (unless a protein sets `Ligands:` to scope itself
to a subset, or `Ligands: none` for a single ligand-free/apo target), producing one
`{protein}_{ligand}.yaml` per pair. See `example.md` for the full copy-paste template and
`examples/` for complete working campaigns.

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

`new` interviews you (proteins, partners, ligands, and the three constraint sentence types)
and writes the file, refusing to overwrite an existing one without asking. It covers the common
case only; rarer fields (modifications, cyclic, MSA override, templates, homo-oligomer copies)
are left for hand-editing. If `setup-plip` has been run it also asks whether each protein has a
reference structure with a ligand already bound (a co-crystal or homology model); if so it runs
cif2plip on it, lets you pick the relevant ligand where more than one is detected, and suggests
the contacted residues as `Pocket contact:` constraints, remapped onto your target's own
numbering via sequence alignment (BLOSUM62 + affine gaps).

`format` re-aligns trailing comments to a clean column and normalises blank-line spacing
around section/record boundaries -- purely cosmetic (it validates the file parses first, and
never changes meaning). Pass `--check` to report whether reformatting is needed without
writing anything (exit 1 if so, e.g. for a pre-commit check).

Any field BoltzMaker doesn't recognise (a typo like `Predict afinity:`) prints a `WARNING`
naming the block, its name and the line number, and is otherwise silently dropped, so a
misspelled field never just vanishes without a trace.

**Common options:**

| Option | Default | Description |
|---|---|---|
| `--output-dir` | `settings.output_dir` | Override where generated YAMLs are written |
| `--out-dir` | `./boltz_output` | Boltz's own `--out_dir`, next to the md file |
| `--accelerator` | `auto` | `auto` / `gpu` / `cpu` (cpu works but is really only for checking a campaign runs at all) |
| `--limit N` | none | Cap how many pending targets `run` submits (smoke test before a full batch) |
| `--max-retries` | `2` | Auto-retry a target that doesn't complete (e.g. an OOM), isolating to one target at a time -- see "Memory on Mac" below (`0` disables) |
| `--diffusion-samples` | Boltz default | Structure samples per target. Each extra sample costs roughly its own share of diffusion time, and analysis only ever reads the first (`model_0`) -- raise it to inspect pose variability yourself, not to improve the report |
| `--no-potentials` | off | Turn off Boltz's FK steering and physical-guidance coordinate update, which was hardcoded on. That guidance update is one of the places a diffusion trajectory can diverge to NaN |
| `--strict` | off | Promote preflight WARN to FAIL |
| `--skip-interactions` | off | Skip cif2plip interaction analysis during `analyze`, even if `setup-plip` has been run |
| `--skip-sse` | off | Skip compare-sse apo-vs-holo analysis during `analyze`, even if a family has `Apo structure:` set |
| `--json` | off | `preflight` only: emit the check results as a JSON array on stdout instead of the rich table, for scripting and tooling (this is what the hosted web app consumes). The banner is suppressed alongside it, exactly as it is for `format`, so stdout stays parseable |

**Memory-control options** (see the next section for why these matter on unified-memory
hardware):

| Option | Default | Description |
|---|---|---|
| `--workers` | `0` | Boltz's own default is 2, but each worker duplicates large in-memory structures out of the same pool the model is using |
| `--mps-watermark` | `1.0` | `PYTORCH_MPS_HIGH_WATERMARK_RATIO` cap |
| `--max-parallel-samples` | `1` | Boltz `--max_parallel_samples` |
| `--recycling-steps` | Boltz default | Passthrough |
| `--sampling-steps` | Boltz default | Passthrough |
| `--diffusion-samples-affinity` | Boltz default | Passthrough |
| `--sampling-steps-affinity` | Boltz default | Passthrough |
| `--max-msa-seqs` | `4096` | Boltz's own default is 8192; halving the co-evolution feature block is one of the few levers that measurably cuts peak memory. Pass `8192` to restore Boltz's default |
| `--memory-warn-tokens` | `1500` | Preflight size-heuristic WARN threshold |

`run` is idempotent: targets with a complete prediction (cif + confidence json, and an
affinity json if `predict_affinity` is on) are skipped on re-run, so an interrupted batch can
just be re-run as-is.

**`compare-sse` options** (see **compare-sse** below for what it does; the standalone command is
for re-running just this analysis, e.g. after adding an apo structure without re-running
`boltz predict`):

| Option | Default | Description |
|---|---|---|
| `--family` | every family with `Apo structure:` set | Restrict to one `Protein` family id |
| `--target` | every target for the selected family | Restrict to one target stem |
| `--out-dir` | alongside `boltz_input.md` | Where to write the CSV/HTML/PyMOL scripts |
| `--phi-psi-threshold` | `30` (degrees) | Per-residue phi/psi delta above this is flagged |
| `--dfg-distance-threshold` | `11.0` (Angstrom) | Separates the two DFG-Phe ring distances (ring to alphaC-Glu+4 Ca, ring to catalytic-Lys Ca) that classify DFG-in vs DFG-out |
| `--alphac-distance-threshold` | `4.0` (Angstrom) | Catalytic-Lys NZ to alphaC-Glu carboxylate below this is an intact salt bridge, i.e. alphaC-in |
| `--no-pymol` | off | Skip writing `.pml` session scripts |
| `--refresh-cache` | off | Bypass the GPCRdb/KLIFS/PDBe disk cache for this run |

## 🛠️ Memory on Mac, and what we fixed in Boltz

### Memory on Mac (unified-memory) hardware

A real 4-chain GPCR+G-protein complex (~1250 combined residues/atoms) used **~65GB RAM on a
64GB M1 Max** during testing and swap-thrashed for 20+ minutes with zero progress before
being killed. Mitigations built in:

- **`--mps-watermark`** sets `PYTORCH_MPS_HIGH_WATERMARK_RATIO`, capping how much memory MPS
  allocates relative to the device's recommended maximum. At the default `1.0` an oversized
  complex raises a clean MPS out-of-memory error instead of silently spilling into swap. **It
  is a hard allocation ceiling, not a swap-avoidance dial.** Lowering it "to be safe" is the
  wrong instinct: `0.7` on a 64GB M1 Max caps allocation at 36GB against a ~34GB requirement,
  and every batch then OOMs immediately. Lower it only above a peak you have measured.
- **`--workers` defaults to 0** and **`--max-parallel-samples` to 1**: both duplicate large
  in-memory structures out of the same pool the model is using. Raising
  `--max-parallel-samples` buys no throughput on an M1 Max either, where this stage is
  compute-bound rather than memory-bound -- it only multiplies peak memory.
- **`--max-msa-seqs` defaults to 4096** rather than Boltz's 8192, halving the co-evolution
  feature block. A quality/memory trade rather than a free win, and one of the few levers that
  measurably cuts peak memory on a large complex.
- **`preflight`'s `memory_heuristic`** WARNs when a target's total residue+ligand-atom count
  crosses `--memory-warn-tokens` (default **1500**), citing the data point above. A rough
  heuristic, not a memory model, and it only blocks a run under `--strict`. Raised from 1000
  because a GPCR + G-protein campaign runs at 1307-1333 tokens, so 1000 warned on all 26
  targets and separated nothing: a warning that fires on everything carries no signal.
- **Peak RSS is recorded** per completed target to `.boltzmaker_target_memory.jsonl`, so the
  size check can eventually come from what this machine actually did rather than a hand-set
  token threshold that separated nothing whether a target succeeded or OOM'd.
- **`run`'s progress bar shows live memory** (RSS summed across the whole `boltz predict`
  process tree), and warns if usage stays above 90% of system RAM for 60+ seconds with no new
  completed target: a sign of thrashing, not progress.
- **`run`/`all` auto-retries** (`--max-retries`, default 2) any target that doesn't complete,
  isolating every still-incomplete target to its own single-target `boltz predict` invocation
  from the first retry onward. A real 4-target cascade on `5ht2_gq_panel` (an OOM on 2 of 6
  large targets run together crashed the shared affinity phase for 2 more that had already
  succeeded) recovered cleanly this way, so a large campaign can be left unattended.
- **That isolation is enforced against Boltz's *manifest***, not just the staging directory.
  Staging one YAML is not enough: `boltz predict` filters an already-processed input out as
  "All inputs are already processed", then rebuilds the manifest from every record in
  `<out_dir>/boltz_results_*/processed/records/` and iterates that. A single-target retry
  therefore re-ran the whole campaign in one process, and one target raising took every target
  behind it down with it -- 20 invocations over 14.5 hours produced zero structures before this
  was found. Each batch now parks the other records for its duration.

If a target still fails after every automatic retry, that's a real finding (this hardware may
not be viable for a complex that size), not something to force through.

### 🩺 What we fixed in Boltz, in plain English

Boltz is excellent software, but a few of its assumptions do not hold on an Apple Silicon Mac,
and two of them waste days rather than minutes. **Every one of these was found by measuring a
real campaign, not by reading the code.**

**1. Memory that was never given back.** On running out of memory Boltz released its GPU memory
by asking the NVIDIA graphics system to let go (`torch.cuda.empty_cache()`). There is no NVIDIA
hardware in a Mac, so that did nothing and the memory stayed held, making each failure likelier
than the last: one campaign skipped eleven targets in a row. The patch adds
`torch.mps.empty_cache()` alongside it, so an out-of-memory skip actually frees memory.

**2. Memory held between targets.** Even when a target *succeeded* its working memory was kept
rather than returned, so the next target started with the tank half full. Measured on a live
run: 47GB held with only 5.5GB in use, against a 55.7GB ceiling. Returning it after each target
frees about **28GB** -- the difference between the next target fitting and failing. Bookkeeping
only; no prediction changes.

**2b. And the part that cannot be returned.** Some memory never comes back while the process
lives, however politely you ask: on a measured run the amount held floored at ~20GB after the
first target and climbed ~1.9GB per target after, while a single target in a fresh process
needed up to 47.6GB of the 55.7GB available. Left alone the two eventually meet, which is why
one run had **no** memory failures in its first four targets and **three** in its last four.
Only ending the process frees it, so BoltzMaker starts a fresh one every few targets --
`Targets per invocation`, default 4. Boltz skips work already done, so a fresh process costs one
model load (~4 minutes against ~45 minutes of prediction) and recomputes nothing. Set it to 0
for the old behaviour of one long-lived process.

**3. Half-precision where full precision was intended.** Boltz forces its most delicate
calculations to full precision because they overflow otherwise, but does so with an instruction
naming NVIDIA hardware explicitly -- so on a Mac all **19** of those protections were silently
doing nothing and the delicate steps ran at half precision anyway.

**4. One bad target killing all the others.** A numerical failure in a single target aborted the
entire run, and every target queued behind it was never attempted, with nothing in the output to
say so. A failure is now contained to the target that caused it.

**5. The affinity step tripping over a missing file.** Boltz predicts binding affinity for all
structures at once after they are built. If any target had been skipped, that step looked for a
file which was never written and crashed, taking down the results of every target that had
succeeded. It now skips the incomplete ones and carries on.

**6. Steering that could destroy a structure.** Boltz nudges atoms with simulated physical
forces to keep the geometry sensible. When two atoms end up very close the repulsive force
becomes enormous, and after twenty rounds of nudging it can overflow to infinity -- which is
then added to *every* atom's position, turning the whole structure into nonsense. One target
failed this way twenty times in a row. An unusable force is now ignored rather than applied, and
the run reports how often it had to: a handful is noise, hundreds means that structure was less
carefully steered than its siblings and deserves a second look.

Guards 4, 5 and 6 only ever act on values that are *already* broken, so any target that would
have worked before produces byte-for-byte the same structure and affinity. They can only rescue
targets that previously produced nothing.

**6b. Steering that pulled a molecule apart, quietly.** Guard 6 stops an *infinite* force being
applied; that was half the problem. Alongside those infinities sit finite but enormous values,
and those were applied. One compound came out with four of its atoms 49, 58, 737 and 2147
angstroms from the rest of the molecule -- the same four atoms, to within a few angstroms, in
three separate runs. The protein was fine and every score was excellent: 0.80 confidence, top of
the binder ranking. Nothing in the report mentioned the ligand was no longer a molecule, because
nothing in the report looked at its geometry. Two limits now apply: a push far beyond anything
else in that step is treated as a singularity and scaled back, keeping its direction; and no
single step may move an atom more than a tenth of a chemical bond. Together they take that
compound from 2154 angstroms across to 16.5 -- the same answer, to within two angstroms, as
running it with steering off entirely. The instability is still there and still reported; it
simply can no longer throw atoms across the room.

**7. Patches that were only applied one way in.** These are edits to the installed Boltz, and
used to be applied only by `run_campaign.sh` -- so starting a campaign directly with
`BoltzMaker.py all`, or rebuilding the environment (installing Boltz puts back its own untouched
files), quietly reverted everything above, with nothing but a warning line in the preflight table
that nobody is awake at 3am to read. BoltzMaker now applies them itself before every run: a no-op
when already in place, and if a repair *was* needed the preflight row says so
(`repaired 3 this run`) rather than passing silently.

**8. A run that hangs forever instead of failing.** The worst failure was the one that did not
look like a failure: Boltz goes quiet, its worker sits in a state the operating system will not
interrupt, it keeps its GPU memory, and it never exits or errors. Seen on a live campaign: 24
minutes of silence holding 39.8GB with no work being done, which would have run to morning.
BoltzMaker now watches how long since Boltz last said anything, and after an hour treats it as
wedged, stops it, and lets the retry ladder rerun the affected targets one at a time in fresh
processes. Nothing already computed is lost. This used to need a separate watchdog program
alongside; it is now part of the run, so an unattended campaign needs nothing watching it.

## ⚙️ Progress, and how long a run will take

Two rows during `run`, laid out as a metrics rail: a state mark, a label, the bar, then every
measurable value right-aligned in a fixed-width column of tabular figures, so digits sit under
digits and a phase name changing length cannot drag the row sideways.

```
▶ targets    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/15  2h14m   ~3h40m
  structure  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━        18m04s  ▓▓▓░░░░░  21.4/69G
```

The top row is the campaign: targets done, elapsed, and the estimate. The second is the
**phase** Boltz is in (MSA generation / structure prediction / affinity prediction), parsed
from its log output, with its own clock and the memory gauge. Only the bar is elastic. The state
mark replaces the second spinner: <span>▶</span> running, <span>⏸</span> paused,
<span>■</span> stopping, always in the same column.

**The memory gauge is filled against the point this machine starts to hurt, not against
installed RAM** -- the same `MEMORY_THRASH_FRACTION` the swap-thrash warning uses. Measured
against total memory, the 4-chain GPCR run above would have looked merely "quite full" until
the moment it died. The gauge turns amber at 60% of that ceiling and red at 85%, so it changes
colour before the log starts complaining rather than after.

**Boltz exposes no diffusion- or recycling-step-level progress** anywhere in its output
(verified against the installed package's source), so that is the finest granularity available
-- and on a single-target campaign it is not fine at all: Boltz's own progress bar counts
dataloader items, one target is one item, so it renders `0/1` at the start, `1/1` at the end,
and nothing in between. A run can sit at `0/1` for an hour while working perfectly. Two things
follow, both deliberate:

- The inner bar **pulses** rather than showing a static empty bar, and carries our own "N in
  this phase" clock. Boltz's `it/s` figure is shown only while it is actually being refreshed;
  once stale (60s without an update) it is replaced by that clock, because a rate string
  written once at the start and displayed for an hour is a stale snapshot presented as live
  data.
- The ETA is **estimated, and says where the estimate came from**. Once a target completes it
  is measured from this run; before that it comes from the median seconds-per-target of
  previous runs of the same campaign on the same accelerator, read from
  `.boltzmaker_run_history.jsonl` (median, not mean, so one swap-thrashing run does not set
  expectations for every run after). With no history it says so rather than inventing a number.

Sizing a first run on new hardware is therefore unknown until one target lands. `--limit 1` is
the cheapest way to find out: one target gives you a real number and writes the history entry
every later run estimates from.

### Controls while a run is going

On a real terminal, `run` takes two single keypresses. (Under `nohup`, a pipe or CI there is
no keyboard to read, and it says so rather than appearing to offer them.) **`p` pauses and
resumes**: a real `SIGSTOP` of Boltz and every worker it started, not a soft flag, so the
processes freeze exactly where they stood and `p` again continues them mid-diffusion, with
nothing discarded and nothing recomputed. **`q` quits**, stopping Boltz and all its worker
processes, writing the run-history entry and exiting cleanly -- Ctrl-C takes the same path.

A paused run **keeps everything it holds** -- RAM, and the GPU allocations with it -- because
that is what makes it resumable in place. Right for "I need the machine for ten minutes", wrong
for "pause this until tomorrow"; for that, quit and re-run, since `run` skips completed
targets. Paused time is excluded from the ETA and recorded separately in the run history
(`working_seconds` alongside `duration_seconds`), so a run paused over lunch does not teach
every later run that targets take an extra hour.

Quitting tears down the **whole process tree**, not just the process BoltzMaker launched. Boltz
runs its dataloader workers as children, and terminating only the parent left them alive holding
their share of RAM and the GPU -- measured on a real two-worker tree, and now covered by a test.

## 📊 Outputs

Written next to `boltz_input.md`. Anything marked optional appears only when the feature that
writes it has run.

| Output | What it is |
|---|---|
| `boltz_run_<timestamp>.log` | Raw `boltz predict` output for the run |
| `boltz_output/` | Boltz's own prediction output tree |
| `boltz_cif/` | Every completed target's `*_model_0.cif`, flattened into one folder |
| `boltz_summary.csv` / `boltz_summary.xlsx` | One row per target -- see below |
| `boltz_summary_view.csv` | The dashboard's "Summary table" columns: a trimmed, renamed subset of `boltz_summary.csv`, for anyone who wants the at-a-glance view in a spreadsheet rather than every raw field |
| `boltz_ligands.csv` | ID, SMILES, stereocentre/ionizable-group/fragment findings, MW, cLogP, TPSA |
| `boltz_dashboard.html` | The interactive report -- see below |
| `boltz_ligand_grid.pdf` (optional) | A print/share-friendly PDF of the dashboard's "Ligand structures" grid: same 5x5 pagination, rendered structures, severity borders and scaffold highlighting as on screen, in the style of [smiles2grid](https://github.com/bellcheddar/smiles2grid)'s own PDF output. Only written when a campaign has at least one SMILES ligand |
| `boltz_plip/` (optional) | Per-target cif2plip output: the converted PDB, PLIP's XML/TXT reports, the ray-traced binding-site PNG, and the PyMOL `.pse` session -- cached here so re-running `analyze` doesn't re-profile a target already done |
| `boltz_interactions.csv` (optional) | Long format, one row per detected contact across every target: interaction type, residue, distance -- the raw data behind the fingerprint heatmap and per-target contact tables |
| `boltz_dashboard_sessions/` (optional) | Each target's PyMOL `.pse` session, linked from the dashboard. This is the one thing that stops `boltz_dashboard.html` being a single self-contained file once interaction analysis has run; without `setup-plip` it stays exactly as self-contained as before |
| `boltz_pose_pairs/` | Two single-ligand mmCIFs per comparison (predicted, superposed into the experimental frame; and experimental) plus an `index.json` of the distances -- what the dashboard's pair viewer draws, carried in the `.bmz` |
| `boltz_sse_comparison.csv` / `.html` | One row per family/target/motif: Ca RMSD, centroid shift, helix-axis rotation/kink angles, SSE boundary shift, flagged phi/psi residues, and (kinases) DFG-in/out and alphaC-in/out states. Written automatically whenever any family has `Apo structure:` set. Family/Target columns, chart legends and the family-coverage table use the dashboard's display names; the CSV keeps the raw `family_id`/`target_stem` columns alongside for cross-referencing. The HTML is a standalone dashboard whose content is also embedded into `boltz_dashboard.html`. See **compare-sse** below for what the metrics mean |
| `boltz_sse_family_status.json` | One entry per protein family: `ok` (with a target/motif count) / `no_apo_structure` / `apo_not_found` / `annotation_failed` / `no_predicted_structures` -- the machine-readable form of the "Family coverage" table, so a family with no `Apo structure:` reads as "not configured" rather than silently missing |
| `boltz_sse_comparison_sessions/` (optional) | A plain-text PyMOL `.pml` script per target: colours/labels each motif, highlights the ones with a significant shift |
| `reference/` (optional, yours) | Experimental mmCIF structures you drop in yourself. Their presence is what turns on the dashboard's **Ligand pose vs experiment** panel (see below); the same files already serve `Pocket contact:` and `Apo structure:` |

### `boltz_summary.csv` / `.xlsx`

One row per target: every scalar field from the confidence/affinity JSONs, computed pIC50,
the input ligand SMILES, and `flags`/`notes` columns (`LOW_CONFIDENCE`,
`HIGH_CONFIDENCE_POOR_AFFINITY`, `LOW_CONFIDENCE_STRONG_AFFINITY`, `LOW_POCKET_PLDDT`,
`MISSING_OUTPUTS`). The XLSX adds a `selectivity` sheet (ligand x family pIC50 pivot) whenever
a campaign spans more than one protein family. When `setup-plip` has run there is also a
`plip_status` column (`ok` / `no_interactions` / `failed` / `ambiguous_ligand` /
`skipped_no_env`) and a `plip_<type>_count` column per interaction type detected
(hydrophobic, hydrogen_bonds, salt_bridges, etc.).

### Inside `boltz_dashboard.html`

Panels, in order:

| Panel | What it shows |
|---|---|
| **Campaign summary** | Field / Value / **Details**: a linked path to the input file, each protein/partner's id and sequence length, each ligand's id and SMILES-vs-CCD source, the full list of target stems, which ligands were flagged in ligand-chemistry review (linked to the card below), and a plain-English gloss for each of the more cryptic run parameters (accelerator, MPS watermark, recycling/sampling steps). Tracked across every `run` invocation in a small hidden sidecar file |
| **Summary table** | One row per target, in named column bands (Identity, Confidence, Affinity, Interactions, Structure) -- details below |
| **Ligand preparation** | The same stereocentre / protonation-state / disconnected-fragment checks as `preflight`'s `ligand_preparation`, shown per ligand rather than as one summary line |
| **Ligand structures** | A paginated 5x5 grid of every ligand's rendered 2D structure, findings and shared scaffolds highlighted on the structures themselves, with a captioned legend and "Download PDF" / "Download SMILES" links side by side, matching the Summary table's download-links style. See **Ligand validation & scaffold highlighting** below |
| **Charts** | An interactive [Plotly](https://plotly.com/javascript/) grid: ranked pIC50, ranked confidence, a "pIC50 vs confidence score" scatter, interaction counts by type, and a "pIC50 vs binder probability" scatter (binder probability on x, pIC50 on y). Hover/zoom/pan; plotly.js is vendored and inlined rather than CDN-loaded, so the dashboard has no runtime dependency on an external script host |
| **Selectivity heatmap** | The family x ligand pIC50 pivot, mirroring the XLSX `selectivity` sheet |
| **Interaction fingerprints** (PLIP) | A per-family residue-interaction heatmap (also interactive Plotly), shown for every family with interaction data even a single ligand -- though the similarity-based reordering that helps SAR ranking within a series only kicks in from 3+ ligands |
| **Per-target binding site** (PLIP) | Its binding-site image (residues labelled and interaction distances shown -- PLIP's own images have neither, so these are re-rendered from its PyMOL session with both added, with a "Download image" link) next to an interactive, auto-rotating [3Dmol.js](https://3dmol.org) view of the same predicted structure (built from the mmCIF, ligand highlighted), side by side with a table of that target's contacts (own "Download CSV") plus a download link for the full PyMOL session |
| **Secondary structure shifts** | The compare-sse card, embedded whole: family coverage, overall shift statistics, and the per-motif table with its Plotly charts. See **compare-sse** below |

**Display names, not internal ids.** The "Target" column shows
`{run}_{group}_{partners}_{ligand}_{pocket}` (e.g. `2_5HT2A_GNAQ+GNB1+GNG2_RISP_41Y`) rather than
the internal per-variant family id/stem (`H2ANG_RISP`, `H2AAP`), partners omitted when there are
none and `apo` in place of a ligand for a ligand-free target, which takes no pocket suffix. The
same name -- or its family-level `{group}_{partners}` form -- replaces the internal id in every
chart tick, legend and point label, every per-target/per-family card title, the campaign-summary
target list, the selectivity pivot's columns in both the dashboard heatmap and the XLSX sheet,
and compare-sse. The raw ids stay alongside it in every underlying CSV/XLSX `targets` sheet, for
cross-referencing against real output filenames.

The leading run number and trailing pocket code earn their place in a matrix campaign, where one
ligand is predicted several times and a run number alone reads as an index rather than a
condition: `2_..._ORFO_41Y` against `3_..._ORFO_V6G` says what was done differently, where
`2_..._ORFO` and `3_..._ORFO` say only that there were two of them. The suffix comes from the
same value the "Pocket" column shows (the pocket code, or `Unc` when unconstrained), so a name
and its column cannot drift apart.

**The Summary table's own details.** Short human headers replace raw JSON field names, and
redundant/granular columns (per-chain and per-chain-pair confidence breakdowns, individual
ensemble sub-model values) are hidden by regex pattern rather than a fixed list, so it scales
past two chains. Two download links sit above it: the full underlying CSV, and one matching just
this trimmed/renamed view. A "Partner" column lists each target's co-folded partner chain(s)
(hidden when there are none), and rows are grouped by `Group:`/family id with a blue top border
marking each new group.

**The "Flags" column is now "Summary", and icon-based:** a bullseye (affinity) and a shield
(confidence) per row, each tinted green/amber/red by tier, with the exact value and
interpretation on hover. The tiers reuse the existing `LOW_CONFIDENCE_THRESHOLD` and a symmetric
buffer around Boltz's documented 0.5 binder decision boundary, because Boltz's own docs define
these metrics' [0, 1] range but publish no official tri-colour bands. A `MISSING_OUTPUTS` failure
collapses the cell to a single red cross, and a legend right of the download links spells out all
six tier/icon combinations. It is always shown (previously hidden entirely when nothing was
flagged), so a clean campaign reads as a row of green icons rather than a column that silently
disappears. A ligand-free (apo) target's ligand/affinity/interface/interaction columns, the
bullseye included, show an explicit `N/A` rather than a blank cell or a misleading `0.00`.

**Chart colour and shape.** The two scatters colour each point by tier via a continuous
colourscale + colorbar legend, in the selectivity heatmap's style: confidence tier for
pIC50-vs-confidence-score, affinity tier for pIC50-vs-binder-probability, matching the shield and
bullseye icons respectively. When a `Ligand:` block sets `Role: agonist`/`Role: antagonist`,
points are also shape-coded (circle = agonist, diamond = antagonist), the legend sitting inside
the plot area's top-left corner rather than Plotly's default outside-right, where it would
collide with the colorbar. Campaigns that don't set `Role:` see a single unshaped trace.

**Embedding.** The dashboard posts its own content height to any parent window via `postMessage`
on load and resize, so a page embedding it in an iframe (e.g. `findings.md`'s "Interactive
dashboard" section) can size the iframe to the actual content -- a cross-origin iframe cannot
otherwise be measured from the embedding page's JS.

## 🔬 Ligand validation & scaffold highlighting

Two related but distinct checks run over every SMILES ligand before you commit hours of
`boltz predict` time, and both surface in the dashboard. Boltz folds whatever chemistry it is
given: an undefined stereocentre, an unintended protonation state or a stray counterion raises
no error, it silently changes the predicted pose and affinity. These are exactly the mistakes a
non-specialist (or a tired specialist) makes typing SMILES by hand, and they're invisible until
you're staring at a confusing result with no idea the input was ever wrong.

### Ligand preparation (validity checks)

At parse time every ligand SMILES is canonicalised (RDKit) so the same molecule is represented
consistently everywhere downstream -- the generated YAML, the summary table, and cif2plip's own
ligand-matching (see the InChIKey-based matching note in [CHANGELOG.md](CHANGELOG.md)). Then,
both at `preflight` (as the `ligand_preparation` check) and in the dashboard's "Ligand
preparation" card, each ligand is checked for **undefined stereocentres**
(`Chem.FindMolChiralCenters(includeUnassigned=True)`: a stereocentre exists but the SMILES
doesn't say which enantiomer/diastereomer, so Boltz will fold *some* version of it, possibly not
the one you intended), **disconnected fragments** (`Chem.GetMolFrags()` returning more than one
-- likely a salt or counterion left in the SMILES, e.g. a sodium carboxylate written as two
components), and **ionizable groups** (SMARTS matches for carboxylic acid, primary/secondary
amine, phenol and sulfonic acid, whose protonation state at physiological pH a plain SMILES
doesn't specify -- worth a deliberate choice, not a default assumption).

All advisory, not a hard failure -- these can be legitimate modelling choices -- but worth a
second look before trusting downstream numbers.

### Scaffold highlighting (the "Ligand structures" grid)

The ligand grid answers a different question: *do any of these ligands share a chemical core?*
This matters most for SAR campaigns, where a chemist is testing close analogues on purpose and
seeing the shared scaffold at a glance (with the parts that differ jumping out) beats reading
each SMILES individually. Two tiers, in order, and nothing is highlighted unless one of them
finds something real:

1. **Exact Bemis-Murcko scaffold match** -- ligands whose ring systems + connecting linkers are
   chemically identical are grouped, threshold-free. The dominant case for a real SAR series.
2. **Fallback for near-analogues** -- leftovers are grouped by Morgan/Tanimoto fingerprint
   similarity, then a maximum common substructure (MCS) is computed across the *whole* group and
   verified to match every member, so the claim is a proven substructure match rather than an
   assigned similarity score.

Shared fragments below 8 heavy atoms (e.g. "they all contain a benzene ring") are deliberately
not highlighted. Ligands in the same group also have their 2D depiction aligned to a common
orientation, so the shared core is drawn in the same position across cells and visually snaps
together.

**What's highlighted and how**, directly on each rendered structure -- the same badges shown on
each cell and spelled out in the panel's legend:

| Badge | Colour | Meaning |
|---|---|---|
| `S` | 🟪 Magenta | Undefined stereocentre (RDKit also draws its own `(?)` marker at the atom) |
| `A` | 🟧 Amber | Carboxylic acid -- protonation state not specified |
| `N` | 🟧 Amber | Primary/secondary amine -- protonation state not specified |
| `Ph` | 🟧 Amber | Phenol -- protonation state not specified |
| `SO3` | 🟧 Amber | Sulfonic acid -- protonation state not specified |
| `salt` | 🟥 Red | Disconnected fragment (salt/counterion) -- flagged on the border and badge only, not atom-highlighted (there's no single meaningful atom to point at) |
| -- | one of six colour-blind-safe palette colours | Atoms in a shared scaffold/substructure -- consistent per group, with a legend entry naming the group and how many ligands share it (e.g. "shared scaffold -- 3/5 ligands") |

The legend is captioned badge by badge, stating what was found and on how many ligands -- never
an unexplained highlight. A specific finding (stereocentre, ionizable group) takes priority over
the softer scaffold highlight where they overlap on an atom, being the more actionable signal.
If no ligand shares a real scaffold with any other, the panel says so plainly ("no shared
scaffold or substructure detected") rather than forcing a highlight onto something coincidental.
CCD-code ligands have no SMILES to render and show a plain placeholder instead of an empty cell.

## 🎯 Ligand pose vs experiment: the prediction against reality

Every other score on the dashboard is Boltz grading its own work. This one is not: it compares
the docked ligand with the same molecule in an experimentally determined structure, and it is
the only panel that can tell you the prediction is wrong. On a real GLP1R campaign, orforglipron
was predicted into the receptor's own transmembrane site with `ligand_iptm` 0.940 and a
confidence score of 0.836 -- comfortably green on both icons -- yet superposed on 7E14, the
crystal structure of that same complex, the predicted ligand sat **9.4 A** from where the
experiment puts it: correct pocket, correct conformation, rotated end for end. No metric Boltz
emits noticed, because none of them is a comparison with reality.

**How to use it.** Drop experimental mmCIF files into a `reference/` folder next to
`boltz_input.md` -- the same files you downloaded for `Pocket contact:` and `Apo structure:`,
nothing else to configure. The panel then appears in `boltz_dashboard.html` and in the hosted
Analysis view; without `reference/` it stays silent rather than showing an empty card.

**Three numbers, because they fail independently.** **Site (A)** is the distance between the two
ligand centroids after superposing the receptor: did it find the pocket at all. **Pose (A)** is
the symmetry-corrected RMSD in place, after that same superposition: did it find the binding
mode. **Conformer (A)** is the symmetry-corrected RMSD with the two ligands superposed on each
other: is the molecule's own shape right.

The orforglipron case reads 3.05 / 9.43 / 3.08, legible at a glance as "right pocket, right
shape, wrong orientation"; collapsed into one figure it would be legible as nothing. Two icons
carry the summary in the dashboard's own visual language -- a **bullseye** for the site, a **pose
mark** for the binding mode -- each tinted green under 2 A, amber to 5 A, red beyond, 2 A being
the long-standing convention for "this reproduces the crystal structure".

**Atoms are paired by molecular graph, not by proximity.** A 65-atom drug has equivalent methyls
and flippable rings; pairing each predicted atom with whichever experimental atom is nearest
quietly flatters a wrong pose by matching it to itself. RDKit assigns bond orders from the
campaign's own SMILES and enumerates the substructure matches, so a symmetry-equivalent
placement scores as correct and a genuinely different one does not.

**Which experimental ligand a target is compared against** is worked out rather than configured.
A constrained target names its pocket after the ligand it was derived from (`GLP1R_ORFO_V6G` ->
V6G), so that is the answer. An unconstrained target -- the baseline, and the comparison most
worth having -- is matched by heavy-atom element composition against every ligand in
`reference/`, so the same molecule is found wherever it sits.

**One small viewer per pair, grouped by pocket.** The table says a pose is 9.4 A wrong; it cannot
say *how*. "Rotated end for end" is obvious in one glance at two overlaid ligands and invisible
in a column of angstroms, so the hosted Analysis view draws each comparison as its own frame
holding exactly two ligands as sticks -- the prediction in red, the experimental one in grey --
superposed through their receptors and zoomed to fit, with spin and reset. Tiles are grouped
under the pocket they were run against, unconstrained last, so the comparison the matrix exists
for reads down one column. On the GLP1R campaign the V6G tiles show two molecules interleaved in
one volume pointing different ways, and the unconstrained tiles show them in different places
entirely: the two failure modes, told apart without reading a number.

Each pair is written at analyze time as two single-ligand mmCIFs (`boltz_pose_pairs/`, carried in
the `.bmz`), because the superposition needs RDKit, the reference files and the predicted
complex, none of which are on the server -- so the viewer draws exactly the coordinates the
numbers were measured from, not a second superposition that could disagree with the table above
it. **Viewers are pooled, not one per tile:** a browser allows a limited number of live WebGL
contexts and exceeding it does not raise, it silently kills the oldest, turning early frames
black while later ones look fine. Frames are created as they scroll into view and disposed
least-recently-seen-first, so thirty comparisons cost the same as four.

**A reference of a different protein is refused, not reported on.** Receptor residues are matched
on number with the residue type required to agree, and a reference must match at least 70% of the
numbering overlap to be accepted as this protein. Measured against 7E14: GLP1R matched at 0.90,
GIPR at 0.11. Without that gate the panel compares a GIPR prediction to a GLP1R crystal structure
and presents the disagreement as a finding. Each reference chain is tried separately rather than
pooled, because a complex numbers its G-protein chains from 1 as well, and pooling lets the last
chain read overwrite the receptor's own residues.

### 🔭 How tight should a pocket be? What the measurements say

Pointed at a real question, the panel found this: **`Pocket distance:` decides whether a
constrained prediction reproduces the crystal pose, and 8 A is too loose.**

Six conditions, all GLP1R + orforglipron scored against 7E14, one diffusion sample each, no
templates. "Contacts" is the number of receptor residues named in the constraint; "shell" is the
distance from the experimental ligand they were derived at. The campaign is public as
[`GLP1R_GIPR_pocket_matrix`](https://boltzmaker.mdeller.com/runs/niSiE5MfGFyddSjGLmeYBA/explore),
so every row below can be read in the live report.

| Pocket | Shell | Contacts | `Pocket distance` | Site (Å) | Pose (Å) | Conformer (Å) | Confidence | Ligand ipTM |
|---|---|---|---|---|---|---|---|---|
| P60 | 6 Å | 38 | 4 Å | 1.36 | **2.04** | 1.34 | 0.849 | 0.987 |
| P80 | 8 Å | 62 | 4 Å | 1.64 | 2.56 | 1.46 | 0.844 | 0.976 |
| P35 | 3.5 Å | 13 | 4 Å | 2.83 | 3.70 | 1.66 | 0.841 | 0.939 |
| P45 | 4.5 Å | 25 | 4 Å | 2.45 | 8.96 | 3.38 | 0.834 | 0.952 |
| V6G | 8 Å | 62 | 8 Å | 3.08 | 9.51 | 3.08 | 0.836 | 0.940 |
| unconstrained | -- | sparse sweep | 8 Å | 11.02 | 13.41 | 3.43 | 0.765 | 0.754 |

**The distance is the lever, and P80 isolates it.** P80 and V6G name the *identical 62 residues*.
Nothing differs between them but 4 Å against 8 Å, and the pose goes from 9.51 Å -- the right
pocket, the wrong way round -- to 2.56 Å, a reproduction of the experiment. That is a
single-variable result, which none of the other comparisons are.

**Do not tune the residue count.** At a fixed 4 Å it does not order the outcome: 13 contacts gives
3.70 Å, 25 gives 8.96 Å, 38 gives 2.04 Å, 62 gives 2.56 Å. Outcomes are bimodal -- a run either
lands (2.0-3.7 Å, conformer 1.3-1.7) or it does not (9-9.5 Å, conformer 3.1-3.4) -- and P45 fails
the same way V6G does, getting the ligand's own conformation wrong as well as its placement. With
one sample per condition there is no separating "25 contacts is bad" from "P45 was a bad draw",
so the honest summary is that **at 4 Å three of four pocket definitions reproduced the crystal
pose, and at 8 Å none did.**

**The confidence columns are the argument for this panel.** Across poses spanning 2.04 to 9.51 Å,
`confidence_score` moves 0.834 to 0.849 -- a spread of 0.015 that does not even put the worst pose
last. Ligand ipTM orders the three good runs correctly (0.939 < 0.976 < 0.987 for 3.70 > 2.56 >
2.04 Å) and then hands P45's 8.96 Å a 0.952, placing a failure mid-pack. Both scores do drop
sharply for the unconstrained run (0.765 / 0.754), so they can tell "on the receptor but not in
the site" from "in the site" -- they simply cannot tell a right pose from a wrong one once the
ligand is in the pocket. Only the comparison with an experiment can.

**Affinity is not in this table**, because the pose series was run with `Predict affinity: no` --
it was a geometry test. The one row that has it is the unconstrained baseline (binder p 0.496,
pIC50 8.98), and the campaign it came from already measured binder probability at r = +0.07
against pIC50 across 24 targets, moving with the pocket condition rather than the chemistry.

#### What to set

Use **`Pocket distance: 4`** for a named pocket. Leave the contact list as whatever your
reference structure gives you; deriving it at a 6-8 Å shell is fine and the difference between
those two was within the noise of this experiment.

This does **not** apply to the ligand-free "stay on your own receptor" sweep that unconstrained
targets get -- that is fixed at `CONFINE_DISTANCE_A` (8 Å) and deliberately not coupled to
`Pocket distance:`. The two constraints ask different questions: a pocket asks *which site*,
where tightening is the whole point, while the sweep asks *which protein* of residues scattered
the length of the chain, where no ligand can be near all of them and the number only scales the
pull. Coupling them meant tightening a pocket silently re-tuned the baseline arm it was about to
be compared with.

#### Does the restraint just manufacture the pose?

The series above shows a tight pocket reproducing a crystal pose. That is only worth something if
the restraint can also **fail**: point it at the wrong site and a pose panel that still reports
2 Å would be measuring the constraint, not the prediction.

A later two-receptor campaign runs that control. Every ligand is predicted three times --
restrained to one pocket, restrained to the other, and unrestrained -- so each of the two ligands
with an experimental structure gets its own site, a wrong site and no site at all, all at
`Pocket distance: 4`. Pocket `V6G` comes from 7E14, pocket `41Y` from 7RBT; each is the site its
own ligand actually occupies.

| Ligand | Restrained to | Site (Å) | Pose (Å) | Conformer (Å) |
|---|---|---|---|---|
| 41Y (vs 7RBT) | **its own site** (41Y) | 0.66 | **0.91** | 0.51 |
| orforglipron (vs 7E14) | **its own site** (V6G) | 1.85 | **2.79** | 1.63 |
| 41Y | nothing (unconstrained) | 6.00 | 6.17 | 0.81 |
| orforglipron | nothing (unconstrained) | 11.64 | 13.57 | 2.92 |
| 41Y | **the wrong site** (V6G) | 22.88 | 24.93 | 1.78 |
| orforglipron | **the wrong site** (41Y) | 28.23 | 29.40 | 3.67 |

**The ordering is the result.** Own site beats unconstrained beats wrong site, by an order of
magnitude at each step, on two different ligands against two different receptors. A restraint
that fabricated a comfortable pose wherever it was aimed would put the wrong-site rows near the
own-site rows; instead they are the worst numbers in the campaign, worse than having no
constraint at all. So the pocket is steering, not scoring -- and the panel is measuring the
prediction.

The conformer column stays low for 41Y even when it is 24.93 Å from home (0.81, 1.78): the
molecule's own shape is right and only its placement is wrong, exactly the decomposition the
three columns exist for. These numbers also come from a different campaign than the tightness
table above, which is why orforglipron's own-site pose reads 2.79 Å here against 2.56 Å there --
one diffusion sample per condition, so treat sub-Å differences between campaigns as noise and the
order-of-magnitude steps as the finding.

**A pocket code is a PDB chemical component id, so look it up.** `41Y` was carried through that
campaign as nothing but a pocket label. Its formal definition is a molecule -- `C32H41FN2O2`,
appearing in exactly one PDB entry -- and it turned out to be the same compound as one of the
campaign's own ligands, which meant that ligand had an experimental structure nobody had fetched.
Downloading 7RBT into `reference/` doubled the pose panel's coverage and supplied the second
ligand in the table above. If a pocket is named after a component id, resolve it against the
chemical component dictionary before assuming the campaign has no experiment to check itself
against.

## 🧬 compare-sse: apo vs holo secondary-structure shifts

**Why this exists:** a confidence score tells you *what* Boltz predicted, not *how the protein
moved* in response to ligand binding -- a real structural question whenever you have both a
reference apo (unbound) structure and a predicted holo one for the same protein. `compare-sse`
answers it in terms a structural biologist actually reasons in ("TM6 swung out 4.2 Angstrom",
"the DFG motif flipped from in to out"), not raw DSSP fragment coordinates.

It is a core part of `analyze`/`all`: any family with `Apo structure:` set is compared
automatically and the result embedded into `boltz_dashboard.html`. A family with no apo structure
isn't silently skipped -- the "Family coverage" table says so explicitly. Pass `--skip-sse` to opt
out, or use the standalone command to re-run just this analysis (`--family`/`--target` scope it).

Motifs are annotated by one of three pluggable sources, auto-selected per family or set
explicitly with `Family type:`:

| Family type | Motifs | Source |
|---|---|---|
| `gpcr` | TM1-7, H8, ECL1-3, ICL1-3 | [GPCRdb](https://gpcrdb.org)'s structure-based generic-numbering service (Ballesteros-Weinstein / GPCRdb schemes) |
| `kinase` | hinge, gatekeeper, catalytic loop (HRD), DFG motif, alphaC-Glu, catalytic Lys | [KLIFS](https://klifs.net)'s public REST API (its fixed 85-residue pocket alignment) |
| `auto` (default) | whichever of the above applies, else... | ...falls back to Pfam domain boundaries via [PDBe](https://www.ebi.ac.uk/pdbe)'s SIFTS residue mapping -- the universal last resort for any protein outside the two families above |

Apo is superposed onto holo using only the family's stable, non-binding-site-adjacent residues
(via gemmi's `superpose_positions`), so a ligand-induced local shift can't skew the global fit.
Each motif then gets:

| Metric | What it means |
|---|---|
| Ca RMSD / centroid shift | How far the motif moved, post-superposition |
| Helix-axis rotation angle | For helical motifs -- e.g. the classic TM6 "outward swing" on GPCR activation |
| Helix kink angle (apo/holo/delta) | Whether a helix straightened or kinked more |
| SSE boundary shift | Did the helix/strand get longer or shorter -- needs deposited HELIX/SHEET records, or an optional external `mkdssp`/`dssp` binary as a fallback (see **One-time setup** above); every other metric works without it |
| Flagged phi/psi residues | Per-residue backbone dihedral outliers above `--phi-psi-threshold` |
| DFG-in/out, alphaC-in/out (kinases only) | DFG uses Dunbrack's two-distance criterion on the DFG-Phe ring; alphaC uses the catalytic-Lys/alphaC-Glu salt bridge. Both are distance criteria on the atoms that actually move, not full dihedral models, and DFG reports `other` for a conformation that is neither. alphaC is unresolved rather than `out` when the side chains are unmodelled |

A metric that genuinely wasn't computed for a motif (axis rotation for a loop, DFG state for a
non-kinase family, boundary shift with no DSSP data) shows as an explicit `N/A` in both the CSV
and every dashboard table, not a blank cell.

Above the per-motif table, both the dashboard's embedded card and the standalone
`boltz_sse_comparison.html` show a **family coverage** row per protein family -- `OK` (with a
target/motif count), `No apo structure configured`, `Apo structure file not found`,
`No motif annotation available` or `No predicted (holo) structures yet` -- and **overall shift
statistics**: targets/motifs compared; mean/median/max Ca RMSD, with which target and motif had
the largest shift; mean centroid shift; total flagged phi/psi residues; and kinase DFG/alphaC
state-change counts.

```sh
python3 BoltzMaker.py compare-sse boltz_input.md
```

Writes, next to `boltz_input.md` (or `--out-dir`): `boltz_sse_comparison.csv`,
`boltz_sse_family_status.json`, a standalone self-contained `boltz_sse_comparison.html` (Plotly
bar chart + motif x target heatmap, vendored the same way as the main dashboard), and
`boltz_sse_comparison_sessions/<target>.pml` -- a plain-text PyMOL script per target that
colours/labels each motif and highlights significant shifts. It's just text: opens in any local
PyMOL install, no `pymol` dependency in BoltzMaker's own venv.

A campaign with no apo structures anywhere never aborts the rest of the pipeline over an
optional, additive feature. The standalone command still exits with a clear error if you
explicitly pass a `--family`/`--target` matching nothing, since that's a real mistake worth
stopping for.

## 🍺 Landlord: a summary in plain English

Named after Timothy Taylor's flagship, as BoltzMaker is named after their Boltmaker.

At the end of `analyze`, Landlord writes a summary of the campaign and of every target
in it: what the confidence means, what each ligand's contacts and predicted potency
show, whether a pose reproduced its experimental structure, and a verdict. It appears
as the last panel of the dashboard and of the hosted explorer, and as
`boltz_summary_prose.json` beside the CSVs.

On an Apple Silicon Mac running macOS 26 with Apple Intelligence switched on, the prose
is written **on-device by the Neural Engine**. No weights ship, no data leaves the
machine, no API key exists to leak. Everywhere else -- Intel Macs, Linux, an older
macOS, Apple Intelligence off -- the same summary is rendered from a template, and the
campaign neither notices nor cares.

| Setting | What it does |
|---|---|
| `--narration auto` | On-device if possible, template otherwise. The default. |
| `--narration template` | Template even where the model would work. Deterministic, so the output is reproducible. |
| `--narration off` | No summary. |
| `--narration model` | On-device only, failing loudly. For testing that path; deliberately not offered in the web form. |

### It never computes, and it is checked when it does

Every number a summary can contain is computed, rounded, given its units and turned
into a string *before* the model sees it, and every ranking and threshold judgement is
already made. The model is handed `"ipTM 0.84"` and `rank: "2 of 4"` -- it has nothing
to round and no list to sort.

That is not fastidiousness. Asked to compose the campaign-level findings, the model
wrote the caution count as the number of discards and the flagged count as the
confidence count. Both figures were in its input. So anything that is arithmetic --
the verdict, the tallies, the rankings -- is computed in Python, and the model
narrates rather than derives. Per-target verdict mismatches went from three in six to
none.

What the model does write is then gated: **every numeric token in generated prose must
appear verbatim in the fact block it came from**, or the summary is discarded and the
template used instead. On its first run against real output the gate caught the model
inventing "confidence scores above 0.8" -- true, as it happens, and never supplied.

The gate checks presence, not attribution. It cannot tell that a supplied number has
been attached to the wrong noun, which is exactly why the tallies are not narrated.

### Nothing here can fail a campaign

Missing binary, Apple Intelligence off, model still downloading, a timeout, unreadable
output, a summary rejected by the gate: every one of those ends at the template.
Narration runs after the analysis is already on disk, at low QoS, and a failure costs
the summary and nothing else.

### It does not compete with the GPU

Measured on an M1 Max: GPU power *fell* during narration, 15.0 to 8.2 mW, so nothing
contends with a folding run -- narration can happen while a campaign is still going.
The inference path uses about 6% of one core. `powermetrics` exposes no ANE rail on
this SoC, so the work is placed on the Neural Engine by attribution rather than by a
power reading: not the GPU, not the CPU, and `aned` busy throughout.

`docs/landlord_spike.md` has the feasibility findings, including a 0% refusal rate
across 26 fact blocks weighted towards the vocabulary most likely to trip a content
filter. `docs/landlord_bench.md` has the timings -- including why concurrency is 1 --
and `docs/landlord_packaging.md` why there is nothing to notarise.

## 🌐 Web deployment

**Live at [boltzmaker.mdeller.com](https://boltzmaker.mdeller.com).** A Flask frontend for the
non-GPU stages, in the two modes introduced under **Installation** above. The GPU `run` step is
deliberately never hosted: there's no GPU on the droplet, so that stage always runs on your own
hardware.

### Fully Automated Mode, Step 1: Prepare

Describe the campaign in the form: a **name**, whether to **predict binding affinity**, then your
**partners** (optional co-folded chains), **proteins**, **constraints** (pocket contact, covalent
bond, or distance), and **ligands** (SMILES or CCD code). Same fields `BoltzMaker.py new` asks
for, and the same 5-character shared-namespace rule on every short name.

Four fields replace something the form used to make you do by hand:

- **Co-folded partners** are tickboxes built from the Partner blocks' own short names, rather
  than a list you retype. The two had to agree exactly, so renaming a partner after a protein
  referenced it failed validation at download time with the campaign already entered. A
  selection whose partner is later renamed or removed stays visible, ticked and flagged, instead
  of quietly disappearing.
- **Apo or inactive structure PDB id** reads the entry back underneath the box: title, method,
  resolution, and **what is bound to it**. Four characters means every typo is another valid id,
  so the title is the only way to see the wrong structure was named -- and "apo" in a title is
  not a guarantee. Entries carrying ligands read amber rather than green: found, and worth your
  judgement.
- **Upload a structure** covers anything not in the PDB -- an unreleased entry, a colleague's
  model, a construct with the fusion cut out. It is copied into the bundle under `reference/`
  and named as the apo path, so the run never needs the network for it. Contents are checked
  against the extension, and the filename sanitised before it becomes a path inside an archive
  somebody unpacks.
- **Targets per prediction process** defaults to 4. On Apple unified memory the allocator never
  returns everything, so a long campaign starves itself and only process exit frees it. Blank
  was the wrong default for this hardware; `0` disables recycling.

The form also carries the rest of what a spec can say: per-protein **ligand scoping**
(`Ligands:`), a shared report **group**, the **motif annotator** (`Family type:`), a ligand's
**pharmacology** (`Role:`), and an apo reference as a file in the bundle with an optional
**chain** -- deriving a form from a spec is only honest if the form can hold everything the spec
says. Everything you type is kept in your browser, so downloading a bundle, stepping over to
Analysis, or reloading does not lose it.

**The bundle is the only file to keep.** It runs the campaign on your machine, and uploading it
back at **Upload bundle** brings the whole page back as it was -- add a ligand, change a pocket,
retune the run, download a new one. The form travels inside the bundle, so one file answers both
questions; **Clear** empties the form, and asks first.

A bundle with no saved page inside it -- every example campaign, and everything already in the
**Runs** archive -- is rebuilt from the `boltz_input.md` it carries, but only when that is
provably safe: the rebuilt page goes back through the form's own parser and assembler and the
resulting spec is compared with the original, refusing with the difference named if they
disagree. A form that silently drops a directive looks correct, rebuilds into a different
campaign, and says nothing -- worse than not loading at all. An unrecognised directive refuses by
name for the same reason.

Then choose the run settings. Every one maps to a real `BoltzMaker.py` flag, written literally
into the generated script so you can read exactly what will run. **Commands** above documents
what each flag does; the form's own labels, defaults and the few web-only notes are below.

| Setting | Flag | Default |
|---|---|---|
| Accelerator | `--accelerator` | auto (picks CUDA or Apple MPS when there is one) |
| Use potentials | `--no-potentials` when unticked | on |
| Data-loading workers | `--workers` | 0 |
| Parallel diffusion samples | `--max-parallel-samples` | 1 |
| MPS high-watermark ratio | `--mps-watermark` | 1.0 (Apple Silicon only; ignored elsewhere) |
| Recycling steps | `--recycling-steps` | blank = Boltz's own (more steps is slower and usually only marginally better) |
| Sampling steps | `--sampling-steps` | blank = Boltz's own |
| Structure samples per target | `--diffusion-samples` | blank = one sample per target |
| Affinity diffusion samples | `--diffusion-samples-affinity` | blank = Boltz's own; only matters where affinity prediction is on |
| Affinity sampling steps | `--sampling-steps-affinity` | blank = Boltz's own |
| Max MSA sequences | `--max-msa-seqs` | blank = BoltzMaker's 4096 (Boltz's own is 8192) |
| Auto-retries per target | `--max-retries` | 2 |
| Preflight size-warning threshold | `--memory-warn-tokens` | 1500 |
| Only run the first N targets | `--limit` | blank = the whole campaign. 1 or 2 is the cheapest way to prove the pipeline works before committing hours of GPU time |
| Treat preflight warnings as failures | `--strict` | off |
| Skip PLIP interaction analysis | `--skip-interactions` | off. Leave it off: PLIP produces the interaction fingerprints the Analysis step shows, and skipping empties that panel to save minutes |
| Skip apo-vs-holo compare-sse | `--skip-sse` | off. Left off, every protein gets an apo reference: an experimental structure if you gave a PDB id, otherwise an extra ligand-free prediction of that protein -- one more target per protein of GPU time. Tick to predict nothing extra |
| Keep private | _(this site only)_ | off. Ticked, nothing about the run is kept on the server: the bundle is not archived, and the results file you upload later is recognised as private and not archived either. Left off, the run is listed under Runs |

Submitting validates the spec (`format`, then `generate`, so a broken campaign fails here rather
than an hour into a run on your machine) and downloads `boltzmaker_<campaign>.command`, typically
around 200KB, containing:

| File | What it is |
|---|---|
| `boltz_input.md` | Your campaign spec, tidied to the house style. Editable. |
| `sse_comparison/`, `vendor/` | The compare-sse package `analyze` imports, and the Plotly and 3Dmol builds the offline dashboard embeds. `vendor/` is most of the bundle's size, included so the run needs nothing from the network beyond the model weights. |
| `config.json` | The run settings, machine-readable. Provenance; not read at run time. |
| `run_campaign.sh` | Installs the environment, runs the campaign, packs the results. |
| `pack_results.py` | Writes the `.bmz`. |
| `BoltzMaker.py` | The pipeline itself. |
| `pixi.toml`, `pixi.lock` | The pinned environment, locked for macOS (Apple Silicon) and Linux (x86-64). |

Move the downloaded file to the machine with the GPU, put it wherever you want the campaign to
live, and either double-click it in Finder or run it from a terminal in that folder:

```sh
sh ./boltzmaker_<campaign>.command
```

`sh` is fine on any platform: the file re-execs itself under bash on its first line, so it behaves
the same whether your `/bin/sh` is bash (macOS) or dash (most Linux distributions).
`bash ./boltzmaker_<campaign>.command` and `./boltzmaker_<campaign>.command` (once executable)
work too.

It unpacks into a folder beside itself and starts immediately: installs [pixi](https://pixi.sh)
if you do not have it, solves the environment, then runs `generate` -> `preflight` -> `run` ->
`analyze`, writing one `<campaign>.bmz` in that same folder. Bring that back for Step 2.
**Boltz-2's model weights are not in the bundle** -- large and versioned by Boltz itself, they
download on first use and cache in your home directory, so a second campaign skips that step.

Each long step -- solving the environment, installing PLIP, warming the Boltz CLI -- shows a
spinner with its elapsed time and reports how long it took, so a terminal that has not moved in
four minutes is never ambiguous; a failing step prints the last twenty lines of its log rather
than leaving it in a file you have to find. Re-running is safe at any point: `run` is idempotent
so an interrupted campaign resumes, and the script refuses to overwrite an existing unpacked
folder. A campaign that fails part-way still packs what completed and records the shortfall.

The bundle runs the whole pipeline including `analyze`, not just `run`. Once a machine has the
pinned environment analysis costs seconds more there, and doing it locally is what lets the
droplet skip a ~1.5GB PLIP environment and a 900-second request for work your machine has already
done. What comes back is small and already structured -- 4.2MB on a real 15-target campaign,
against a 19.4MB dashboard and 50.6MB of PyMOL sessions that deliberately stay on your own disk
-- so Analysis is a reader, not a compute step.

### Fully Automated Mode, Step 2: Analysis

Upload the `.bmz` and the campaign opens as an interactive report. Nothing is recomputed, so it is
quick regardless of campaign size, and it opens on the campaign summary with the first target
already selected -- on a one-target campaign there was never a click to make.

A **header** names the campaign and counts how many predictions it produced, how many are
flagged and how many carry a structure, warning explicitly if targets are missing from the
summary because the campaign did not fully complete. Below it, a sortable, filterable
**targets** table -- target, family, ligand, confidence, pIC50, interaction count and flags,
filtered by free text, by family, or to flagged targets only -- opens any row you click as the
**target detail**: four panes for that target, then two campaign-level panes and a sequence
track.

The Target detail heading is itself the target picker, so the panel both names the open target and
changes it, and a pulldown at the top of the page jumps to any panel. **Download HTML package**
gives the whole explorer as a directory of files -- one page, Mol*, Plotly and the campaign's own
data -- to drop into any web root; a **Keep private** campaign gets that download beside a
**Destroy all data** button, removing the session and any archived bundle and results from the
server.

**Four equal panes:**

| Pane | Content |
|---|---|
| Overall structure | A [Mol*](https://molstar.org) viewer coloured by chain, ligand in red |
| Binding site | A second Mol* viewer framed on the ligand and its contacting residues, turning on load |
| Interactions | Every PLIP contact grouped by type: residue name, number and chain, the distance, and the geometry belonging to that interaction -- donor and acceptor atom types and the donor angle for a hydrogen bond, the T/P classification and ring offset for a stack, the charge sense and ligand group for a salt bridge |
| Metrics | pTM, ipTM, complex pLDDT, predicted affinity, pIC50 with its ensemble spread, and the Ca RMSD to the apo reference (the residue-weighted mean across the motifs compare-sse could align, with that motif count beside it), with the ligand depiction filling the space below |

Both viewers carry cartoon/surface/spin/reset and an **AlphaFold** button overlaying that
protein's AlphaFold model, superposed server-side on the confident core (pLDDT >= 70) and
reporting the accession, how it was resolved, how many Ca it was fitted on, and the RMSD.

**Two campaign-level panes** sit below: **Ligand pose**, every ligand overlaid as sticks in one
frame with no protein, and **Superposed targets**, every target as a Ca trace with its RMSD to the
campaign's reference beside it. Each has a checkbox per target, and each RMSD is given over the
residues that actually agree, with that count.

**Then, full width, the target's sequence:** a per-residue track coloured by property with the
PLIP contacts marked, and above it a conservation logo aligned across every distinct protein in
the campaign, drawn in bits of information. Hovering a residue names it and lists its contacts and
conservation; clicking one selects and frames it in both viewers, as does clicking a contact.

**BoltzMaker's own panels sit beneath**, lifted out of the reports it generated and rendered as
siblings -- every panel listed under **Inside `boltz_dashboard.html`** above, twenty on a real
campaign against the two the explorer draws itself, both reports still downloadable whole. They
are lifted rather than reimplemented, so they cannot drift from the analysis code, and merged
rather than framed, so the page does not become a scrolling document inside a card. The whole
sequence is one ordered list in `reports.PANEL_ORDER`, so reordering the page is a line moved
rather than a template edit. BoltzMaker's **pIC50 vs confidence score** scatter is the one kept,
wired up so clicking a point opens that target. On it, the dashed vertical line at **0.5** is the
genuine absolute low-confidence cutoff, while the mismatch flags
(`HIGH_CONFIDENCE_POOR_AFFINITY`, `LOW_CONFIDENCE_STRONG_AFFINITY`) are **not** absolute: they
come from splitting *that campaign* into terciles, so they mean "relative to the other targets
you ran". There is deliberately no horizontal affinity threshold line, because drawing one would
imply a fixed cutoff the numbers do not support.

**Nothing from the results file executes.** It is user input rendered on this site's own origin,
so the markup is reduced to a tag allowlist by a tokeniser -- not a regex, which was defeated by a
`<` inside a quoted attribute -- and every chart is rebuilt from its data: each `Plotly.newPlot`
call has its arguments JSON-parsed on the server and handed to the page as values, which the
page's own code then plots. Parsed and re-serialised, an injected payload is inert text.

Two things are deliberately dropped: the reports' binding-site panels, because the explorer
already gives every target a pose viewer with its interactions beside it and the PyMOL sessions
they link to are not in the archive; and the compare-sse charts the dashboard embeds, because the
compare-sse page carries the same charts under the same element ids, and rendering both would put
two divs with one id on the page, leaving the second unreachable and silently undrawn.

An open target is deep-linkable -- the URL carries it, so a link to one target can be shared or
reloaded. **Sessions do not expire on a clock**: an analysis link keeps working, and uploads are
removed only when the space set aside for them fills, least recently opened first. **Download
summary CSV** gives the full summary table including every column not shown in the browser.

A note on vocabulary: BoltzMaker calls each `Protein:` block a **family**, and its own reports use
that word throughout. A campaign with one receptor and an apo companion therefore has two
families, which reads oddly, so this page says **protein** for the same thing and counts
**predictions** rather than families.

### Stepwise Mode

The same non-GPU stages as four independent tools. Each takes an upload and hands back a download,
and none depends on the others.

| Tool | You give it | You get back |
|---|---|---|
| **Wizard** | Answers to the same plain questions as `BoltzMaker.py new` | A validated, tidied `boltz_input.md` |
| **Generate** | A `boltz_input.md` (paste or upload) | `boltz_yamls.zip`: the per-target YAMLs plus the manifest |
| **Preflight** | A `boltz_input.md` | The full check table: SMILES and ligand chemistry, chain-id lengths, duplicate targets, size heuristics. The GPU and model-weight checks report on the server, not your machine, so read those on your own hardware instead. |
| **Analyze** | A zip of a completed campaign folder (`boltz_input.md` + `boltz_yamls/` + `boltz_output/`, plus any `Apo structure:` files) | The summary CSV/XLSX, the interactive dashboard rendered in the page, and a zip of everything including the CIFs, PLIP output and compare-sse results |

### Runs

The landing page carries the five most recent runs with a link straight into each one's analysis.
The full table is at [**/runs**](https://boltzmaker.mdeller.com/runs): everything not marked
private, in one place -- campaign, when it was prepared, target count, the bundle, and the results
file once uploaded. Each row offers the bundle and the `.bmz` for download, and **explore**, which
re-opens the analysis from the archived results without uploading anything again. The six public
campaigns listed under **Examples** above all live here.

The archive is **capped** -- 3GB and 200 runs -- and prunes oldest-first when it fills, each
removal recorded so a missing run is explainable rather than a mystery. The host has ~16GB free
and also serves three other apps, so an uncapped archive would be a slow-motion disk-full outage.

### How it is built and served

**Source and tested-CLI isolation.** The web app lives in `web/`, and the isolation that matters
is the process boundary. `BoltzMaker.py` was never designed to be imported (it relaunches itself
into a managed venv at module import time), so the Flask app only ever invokes it as a subprocess, with
an explicit minimal environment and a per-command timeout, through a dedicated trimmed venv
(`.venv/`, torch/boltz-free, ~500MB -- every torch/boltz reference in the script is a
function-local lazy import) kept separate from the Flask-serving venv (`web/.venv/`).

**The `.bmz` results file.** A zip carrying `manifest.json` (format version, campaign name,
timestamps, a SHA-256 of the `BoltzMaker.py` that produced it, per-file checksums, and an explicit
record of anything not packed), the summary CSVs, one structure per target, and one labelled PLIP
image per target. Its layout is written by the bundle's generated `pack_results.py` and read by
`web/boltzmaker_web/results.py`; both mirror one `BMZ_VERSION`, and a file declaring any other
version is refused rather than parsed optimistically. Every uploaded zip -- a `.bmz` or a
Stepwise campaign folder -- is treated as hostile: extraction is bounded on entry count, declared
size, actual written size, compression ratio and resolved path (so zip-slip and zip-bomb payloads
are rejected), with every check run over the whole member list before a single byte is written.

**Optional PLIP.** With the droplet's `.plip_env` present (the same conda-forge PyMOL/OpenBabel
environment `setup-plip` builds locally, ~1-1.5GB), hosted `analyze` runs full interaction
detection and compare-sse; without it, both degrade gracefully rather than erroring, as locally.

**Serving stack:** gunicorn (3 sync workers, 900s timeout to cover PLIP rendering and compare-sse's
GPCRdb/KLIFS/PDBe lookups) behind nginx (Let's Encrypt TLS via certbot, HTTP/2, rate-limited upload
endpoints, 200MB body cap), as a hardened systemd service (dedicated unprivileged user, memory/CPU
caps). Every request gets its own scratch directory, deleted when the request finishes and swept
by a five-minute cleanup timer as a backstop.

## 🩹 Troubleshooting / FAQ

Local runs first, then the hosted site.

| Problem | What is happening, and what to do |
|---|---|
| `setup-plip` fails, or `pip install plip` tries to build OpenBabel from source | Expected without conda-forge -- `plip`'s own installer forces a from-source OpenBabel rebuild unless OpenBabel is already importable *inside pip's build sandbox*, and the standalone PyPI `pymol-open-source` wheel has a hardcoded broken library path on at least some machines. `setup-plip` works around both via a self-downloaded micromamba; re-run `python3 BoltzMaker.py setup-plip --force` if a previous attempt left a half-built `.plip_env`. |
| A `preflight`/`analyze` step involving `.plip_env` errors with `ModuleNotFoundError: No module named 'chatmol'` (or similar) | A stray `~/.pymolrc.py` (e.g. from an unrelated PyMOL plugin) is being loaded by the bundled PyMOL. BoltzMaker already overrides `HOME` for these subprocess calls so this shouldn't reach you, but if it does, check `~/.pymolrc.py` for anything referencing a package not installed in `.plip_env`. |
| `run` seems to hang with no progress, or your Mac gets extremely slow | Check the memory figure in the progress bar and see **Memory on Mac** above -- very likely swap-thrashing, not a genuine stall. Re-run with a lower `--mps-watermark`, `--workers 1` and `--max-parallel-samples 1`. |
| A target's YAML/CIF exists on disk but BoltzMaker says it's missing, or `preflight` hangs | Check for iCloud "Optimize Mac Storage" dataless files -- `preflight`'s `icloud_materialize` check handles this automatically, but a very large campaign can take a while to force-download everything on first run. |
| `boltz` fails during `setup` with a `numpy` build error | You're likely on Python 3.13+. `boltz` pins `numpy<2.0`, which has no prebuilt wheel past cp312 -- `_find_boltz_python()` already looks for a `python3.12` specifically; install one (`brew install python@3.12`) if it can't find one. |
| A run dies with `torch._C._LinAlgError: linalg.svd ... failed to converge because the input matrix is ill-conditioned` | Not a conditioning problem, and not an OOM. Measured on this hardware: of every degenerate 3x3 (rank-1, zeros, repeated singular values, 1e-20, 1e20) plus 2000 random matrices, the only input that raises it is one containing **NaN** -- the diffusion coordinates have already diverged before the alignment runs. `linalg.svd` is not even an MPS op (it falls back to CPU), so forcing it to CPU changes nothing. Apply `patches/apply_boltz_patches.py` so the failure is contained to that one target, then try that target with `--no-potentials`, since the physical-guidance coordinate update is one of the places a trajectory can diverge. |
| One target's failure kills the whole `boltz predict`, and targets behind it never run | `boltz`'s `predict_step` skips a batch on out-of-memory but re-raises everything else, and `LinAlgError` subclasses `RuntimeError`. Run `python3 patches/apply_boltz_patches.py` (idempotent, keeps `.orig` backups) -- `preflight`'s `boltz_patches` row reports whether it is applied. Re-run it after any `boltz` upgrade, which silently reverts it. |
| A target fails preflight with a chain-id-length error | Boltz truncates chain IDs to 5 characters internally (a fixed-width field in its own schema) and silently corrupts longer ones rather than erroring at parse time -- shorten the protein/partner/ligand name in `boltz_input.md`. |
| The dashboard's charts (or the binding-site 3D view) don't render, or look unstyled | plotly.js and 3Dmol.js are vendored and inlined (not CDN-loaded), so a missing network connection shouldn't cause this -- Google Fonts is still CDN-loaded for styling, so the page needs internet access at least once for the fonts to look right (falls back to a generic sans-serif otherwise; charts, 3D views and data are unaffected). If they genuinely don't render, check that `vendor/plotly-2.35.2.min.js` and `vendor/3Dmol-2.5.5-min.js` exist next to `BoltzMaker.py` -- `analyze` prints a warning and falls back to the relevant CDN (known not to work in some HTML-preview contexts) if either is missing. |
| Upload rejected as too large | Uploads are capped at **200MB**. The packer aims below that (it stops at 180MB, dropping the largest structures first and recording each one in the manifest), so hitting this usually means an unusually large campaign. Analyse it locally with `boltz_dashboard.html` instead. |
| "This results file declares format version N" | The `.bmz` was written by a different version of the bundle than the site understands. Prepare a fresh bundle and re-pack; the file itself is not damaged. |
| "No manifest.json in the upload" | A campaign folder was uploaded instead of the `.bmz`. Either upload the `.bmz` the bundle wrote, or use Stepwise Mode's **Analyze**, which is the tool that takes a campaign folder. |
| Some targets have no pose viewer | Those structures were dropped to stay under the size limit, or the target failed. `manifest.json` inside the `.bmz` records which, and why. They are still in `boltz_cif/` on your own machine. |
| The 3D viewer says WebGL is unavailable | The browser has WebGL disabled or unsupported. Everything else on the page is unaffected. |
| Preflight fails on `sse_comparison` or `result_packer` | The bundle is incomplete -- re-download it. Both are checked before any GPU time is spent precisely because `analyze` imports them only at the end, so a missing file used to surface after the prediction had already finished. |
| Preflight warns on `vendor_assets` | Plotly or 3Dmol is missing from `vendor/`, so the dashboard will reach for a CDN and will not render offline. The run itself is unaffected. |
| Preflight warns `boltz_cli` did not answer `--help` in 120s | A cold first import, not a broken install: `boltz --help` loads the whole torch stack, and a freshly solved environment byte-compiles it too. The bundle warms it before the campaign, and it is a warning that does not stop the run. |
| The interactions panel is empty | PLIP either did not run for that target, or found nothing. If you switched **Skip PLIP interaction analysis** on when preparing, that is the cause. |
| A session link stops working | Sessions are not deleted for being old, but the oldest are evicted once the space set aside for them fills, least recently opened first. Upload the file again; nothing is lost, since the `.bmz` is on your own disk. |

## 🧫 Testing

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/
```

455 tests here, plus 616 for the web app. The `compare-sse` annotators are covered against real
fixture data (a real apo EGFR kinase-domain structure vs the `egfr_covalent` example's real holo
prediction; a real apo beta2-adrenergic-receptor structure vs `adrb2_gs_panel`'s real holo
predictions), with GPCRdb/KLIFS/PDBe network calls swapped for an injectable fake client seeded
with real, previously-verified API responses -- fully offline and fast (~9s). Plus grammar and
CLI-resolution tests for the parser fields above, chain-resolution tests against real
fusion-construct and kinase-domain-only apo structures, GPCRdb/KLIFS/Pfam annotator pipelines, and
the dashboard's summary-stats and SSE-table column logic.

53 of the web app's tests cover Fully Automated Mode end to end. Rather than asserting against a
hand-written `.bmz` fixture, they render the real `pack_results.py` out of a real bundle, run it
over a synthetic campaign, and read the result back with the real reader -- packer and reader are
two halves of one contract living in different files on different machines, exactly the shape of
thing that drifts silently. Also covered: the generated bundle really executed under `sh`,
`bash`, `dash`, `zsh` and `ksh` (final step stubbed), proving the documented
`sh ./<bundle>.command` works where `/bin/sh` is dash as well as bash; the generated scripts
checked with `bash -n` (they only ever execute on someone else's machine); every run-setting flag
checked against `BoltzMaker.py all --help` so a typo cannot reach a user's overnight run; and the
hostile-upload guards exercised with real zip-slip, compression-bomb and malformed-manifest
archives.

Four `compare-sse` tests need example structure data that is gitignored
(`examples/*/boltz_cif/`), so they fail in a fresh clone until you have run one of the example
campaigns.

## 📚 Citation

> Passaro, S., Corso, G., Wohlwend, J., Reveiz, M., Thaler, S., Somnath, V.R., Getz, N., Portnoi, T., Roy, J., Stark, H., Kwabi-Addo, D., Beaini, D., Jaakkola, T., Barzilay, R. (2025). Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction. *bioRxiv*. https://doi.org/10.1101/2025.06.14.659707

> Mirdita, M., Schütze, K., Moriwaki, Y., Heo, L., Ovchinnikov, S., Steinegger, M. (2022). ColabFold: making protein folding accessible to all. *Nature Methods*. https://doi.org/10.1038/s41592-022-01488-1

> Schake, P., Bolz, S.N. et al. (2025). PLIP 2025: introducing protein-protein interactions to the protein-ligand interaction profiler. *Nucleic Acids Research*, gkaf361. https://doi.org/10.1093/nar/gkaf361

> The PyMOL Molecular Graphics System, Version 3.1, Schrödinger, LLC.

> Rego, N., Koes, D. (2015). 3Dmol.js: molecular visualization with WebGL. *Bioinformatics*, 31(8), 1322-1324. https://doi.org/10.1093/bioinformatics/btu829

## 📄 License

[MIT](LICENSE) &copy; Marc C. Deller

## 📋 To do

- [x] Give the dashboard one number that is not Boltz grading its own work: a
  **Ligand pose vs experiment** panel comparing the docked ligand with the same molecule in an
  experimental structure. Measured motivation: a GLP1R/orforglipron prediction scored
  `ligand_iptm` 0.940 and confidence 0.836 while sitting 9.4 A from where 7E14 puts the
  same ligand in the same pocket, rotated end for end, and nothing on the dashboard could
  say so. Reports site, pose and conformer separately, because they fail independently
  (3.05 / 9.43 / 3.08 reads as "right pocket, right shape, wrong orientation"; one figure
  reads as nothing). Atoms are paired by molecular graph via RDKit rather than by
  proximity, which would match a wrong pose to itself; and a reference is refused unless
  it is genuinely a structure of that protein -- 7E14 matched GIPR's residue numbering at
  0.11 identity and would otherwise have been reported on. See **Ligand pose vs experiment** above.
- [x] Answer "how tight should a pocket be?" with measurements rather than intuition:
  six conditions on GLP1R + orforglipron against 7E14, reported in **How tight should a
  pocket be?** above. `Pocket distance` turned out to be the lever -- the same 62
  residues at 4 A instead of 8 A took the pose from 9.51 A to 2.04-2.56 A -- while the
  contact count did not order the outcome at all. Confidence spans 0.834-0.849 across
  that whole range and ligand ipTM ranks a 8.96 A failure mid-pack, which is the
  evidence for the pose panel existing. Decoupled the confine-to-receptor sweep from
  `Pocket distance:` in the same pass, so tightening a pocket no longer re-tunes the
  baseline arm it is compared against.
- [x] Give each comparison its own frame: **one pair viewer per predicted/experimental
  ligand pair**, exactly two ligands as sticks, superposed through their receptors and
  zoomed to fit, grouped by the pocket each target was run against. Fed by two
  single-ligand mmCIFs BoltzMaker writes at analyze time, so the picture is the same
  superposition the numbers came from and the server needs no RDKit. Frames are pooled
  and drawn on scroll, because a browser silently kills the oldest WebGL context rather
  than refusing a new one, which turns early tiles black while later ones look fine.
- [x] Let a private campaign be shown to someone without publishing it: **share links**.
  The same self-contained HTML package the Download button produces is hosted at an
  unguessable URL behind a generated password, shown once and stored only as a PBKDF2
  hash. A share is still not a listed run -- it lives under `<runs_root>/shares/`, which
  the Archive never reads, so it cannot appear on `/runs` or the landing page however many
  exist. Two independent secrets per share (the viewing password cannot revoke), a
  per-share cookie secret so revoking invalidates every session already issued, a
  10-attempt lockout that survives a worker restart, and revocation both by a one-click
  link and by the campaign's own Destroy button. Shares never expire by design, so the
  storage cap refuses a new share rather than evicting an old one -- evicting would break
  the promise that a link works until it is revoked.
- [x] Add **Use same pocket** to Prepare, with a distance box defaulting to 8 A. Co-folding puts a ligand wherever it likes: measured on a real GLP1R/GIPR campaign, 6 of 27 ligands docked onto the G-protein subunits rather than the receptor, and only 6 of 14 GIPR ligands shared a site. The pocket reference is **per ligand**, not per protein, because a pocket belongs to the ligand-receptor pair -- orforglipron's site on GLP1R (7E14) and 41Y's site on GIPR (7RBT) share 3 residues out of ~60 once projected onto each other, so one pocket per receptor would force one chemotype into the wrong site. Each ligand names a **holo** reference and picks from the ligands found in it; waters, ions, buffers, sugars and lipids are excluded outright, so 7dty's six cholesterols are never offered. Holo is enforced for the pocket and apo is enforced for the comparison: a reference with a bound ligand is refused as apo (6ln2, a modulator+Fab complex, was used as one for weeks) and a ligand-free one is refused as a pocket. Residues are mapped into the user's own numbering by alignment and reach Boltz as a `pocket` constraint with `max_distance`.
- [x] Close the archive's trust gap: "Keep private" put the guarantee in a checkbox the caller had to remember to tick, and automated form posts made against the live site published three bundles of a real private campaign on `/runs` and the front page. Archiving now needs positive evidence of a person submitting the form from this site (`Sec-Fetch-Site: same-origin`, or a same-origin `Referer`), fails closed otherwise, and honours an explicit `X-BoltzMaker-No-Archive` opt-out for test clients.
- [x] Make the bundle **the only file anyone has to keep**: it runs the campaign, and uploading it back at the top of Step 1 restores the form to edit and rebuild. It was three artefacts before -- the `.command`, the `.bmz` it produces, and a `.boltzpage.json` from a "Save page" button -- with no way to say which mattered; the second and third are gone from the page. Reading a `.command` needs a line-anchored search for the payload marker, because the extractor greps for its own marker and a plain `find` slices the shell script in as base64, failing with "Incorrect padding" and naming nothing.
- [x] Load a bundle that **has no saved page inside it** -- every example campaign and everything already in the Runs archive -- by rebuilding the form from its `boltz_input.md`, which fixes bundles already on people's disks rather than only the archived copies. Done only when provably safe: the rebuilt page goes back through the form's own parser and assembler and the resulting spec is compared with the original, refusing with the difference named if they disagree, and refusing any directive the derivation has not been taught. The check earned itself immediately, catching eight silent losses -- companion proteins invented on every reload (an unticked box posts nothing, and the field being wholly absent reads as "old page, default all on"), a covalent bond dropped because blank fields were skipped and the parallel arrays went ragged, `Class: experimental` appearing from nowhere, 5HT2's `H2AAP` renamed to `5HAP`, three companions collapsing into one because they were matched on a sequence their variants share, companions lost when a real apo exists and nothing points at them, and a spec with no `Settings:` block reading as different from its own rebuild.
- [x] Give the form the fields a spec always had and it did not: per-protein **`Ligands:` scoping**, **`Group:`**, **`Family type:`**, a ligand's **`Role:`**, an apo reference as a **file in the bundle** with an optional **chain**, and **`Targets per invocation`**. Not optional extras -- these are why no example campaign could be loaded back in, and deriving a form from a spec is only honest if the form can hold everything the spec says.
- [x] Stop the two places a partner is named from drifting apart: **co-folded partners are tickboxes** built from the Partner rows themselves. Renaming a partner after a protein referenced it used to fail validation at download time with the campaign already entered. Still posts one comma-separated `protein_partners[]` per row -- a `<select multiple>` posts one value per selection, which would make the protein rows' parallel arrays ragged and attach partners to the wrong protein.
- [x] **Read a PDB id back** under the box, the way the UniProt accession already was: title, method, resolution and the bound ligands. Every typo in a four-character id is another valid id, and "apo" in a title is not a guarantee -- this project has twice measured against a reference that was not what it claimed. Needs one GraphQL call rather than the REST entry endpoint, whose `nonpolymer_bound_components` is absent on many entries including 5VEW, which has three ligands: REST would report "no ligands" for exactly the case the check exists to catch.
- [x] **Upload an apo structure** from the machine, for anything not in the PDB, copied into the bundle under `reference/`. Two things that would fail silently: the form needs `multipart/form-data` or the browser posts the filename without the file, and the input is named per row rather than as a `[]` array because an empty file input posts nothing and an array would attach each upload to the wrong protein. Contents are sniffed rather than trusted from the extension, filenames sanitised, 20MB ceiling.
- [x] Fix the UniProt autofill **announcing nothing when it fills a field**. Assigning `.value` from script fires no event, so a partner filled from its accession did not reach the proteins' partner pickers until some later edit triggered a re-sync -- which read as "partners only appear when I add another one". Autosave missed it identically: an autofilled name and sequence were never written to browser storage until the next keystroke elsewhere, so filling a protein from its accession and reloading lost it.
- [x] Write the campaign up in plain English, on the machine that ran it: **Landlord**, narrating each target and the campaign from the Apple Neural Engine where macOS 26 and Apple Intelligence allow it, and from a template everywhere else. No weights ship and no data leaves the machine. Measured before building anything: 0 refusals across 26 fact blocks deliberately loaded with the vocabulary a content filter dislikes, and GPU power *falling* during narration (15.0 to 8.2 mW), so it does not compete with a folding run. Everything that is arithmetic is computed in Python and merely narrated -- asked to compose the campaign tallies the model named the caution count as discards, and both figures were in its input, so the numeric gate could not see it. What the model does write is gated on every number appearing verbatim in its fact block, and a rejected summary falls through to the template. Nothing in the path can fail a campaign. See **Landlord** above, and `docs/landlord_spike.md`, `docs/landlord_bench.md` and `docs/landlord_packaging.md`.
- [x] Prove the pocket restraint can **fail**, not just succeed: a wrong-pocket arm on every ligand. The tightness series showed a 4 A pocket reproducing a crystal pose, which is only evidence if the same machinery misses when aimed somewhere else. Running each ligand against its own site, the other ligand's site and no site at all put own-site at 0.91/2.79 A, unconstrained at 6.17/13.57 A and wrong-site at 24.93/29.40 A -- worse than no constraint -- on two ligands across two receptors. The conformer column stays low (0.81, 1.78) through the wrong-site failures, so the molecule's shape is right and only its placement is wrong, which is the decomposition the three columns exist for. See **Does the restraint just manufacture the pose?** above.
- [x] Resolve pocket codes against the chemical component dictionary instead of treating them as opaque labels. A pocket carried through a campaign as the string `41Y` is a PDB component id defining a real molecule, and it turned out to be the same compound as one of that campaign's own ligands -- which had an experimental structure nobody had fetched. Pulling 7RBT into `reference/` doubled the pose panel's coverage and supplied the second ligand of the wrong-pocket control above.
- [x] Record where a pocket came from, via **`Pocket source: <code> from <PDB>`**. The reference panel previously read "not recorded" for any pocket whose provenance lived only in whoever built the spec, and the pose panel could pair a prediction with its experiment only when that structure happened to already be in `reference/`. Reporting only -- it never reaches generate/run.
- [x] Take **more than one reference structure per protein**, and ship every one of them. `Pocket source:` is now repeatable, and each pocket reference downloaded for its contacts is written into `reference/` instead of being discarded -- previously a pocket's structure travelled only when the same entry happened to be the apo one too, so on any campaign where they differed the pose panel had nothing to score against and said nothing about it. One code claimed by two structures is a parse error rather than last-write-wins.
- [x] Offer **"reference molecule only"** on a pocket reference: ship the structure so its bound ligand can score a matching compound's pose, without defining a site. A site is another run for every ligand; a reference molecule costs nothing. Expressed in the spec as a `Pocket source:` line with no `Pocket contact:` lines, so no new grammar was needed, and listed in the reference panel as "reference only" rather than as a site with zero contacts. Measured on ABL1: imatinib had no experimental twin at all until 1IEP was added this way, and then reproduced its crystal pose at 0.56 A constrained against 18.39 A unconstrained.
- [x] Say which ligands were **not** compared and why. A four-target ABL1 campaign reported "2 target(s) compared" and dropped imatinib silently, which read as "it was never predicted" rather than "it had no reference".
- [x] Make the **Reference structures** panel ask only the question that applies to the protein in front of it: G-protein coupling for a GPCR, DFG and alphaC for a kinase, and nothing at all for anything else. A kinase reference was reported as "no G protein bound" -- true, and as informative as "no wings" is of a horse. Family comes from the same `applies_to()` filters that pick the annotator, so a panel cannot label a protein differently from what measured it.
- [x] Replace the **kinase state classifier**, which was wrong in one direction for every structure it ever saw. DFG-Asp Ca to catalytic-Lys Ca barely moves between states, so an 8 A threshold called dasatinib-bound 2GQG (plainly DFG-in) "DFG-out" at 11.15 A -- as it called everything. Now Dunbrack's two-distance test on the DFG-Phe ring, and the Lys-Glu salt bridge for alphaC, which read 2GQG correctly as DFG-in/alphaC-in. alphaC is unresolved rather than "out" when side chains are unmodelled, and DFG reports `other` for a conformation that is neither.
- [x] Put the **pocket code in the target name** (`2_RECP1_GNAS_LIG1_41Y`, `Unc` when unconstrained). In a matrix campaign a ligand is predicted once per pocket, so a bare run number reads as an index rather than a condition; the suffix says what was done differently. Derived from the same value the Pocket column shows, so a name and its column cannot disagree, and skipped for apo targets, which have no pocket.
- [x] Add **`Class: control` / `Class: experimental`** to a `Ligand:` block, and mark the experimental ones on the pIC50-vs-confidence, pIC50-vs-binder-probability and both ranked charts. Marked by a thin red outline rather than a colour, because colour is already carrying confidence and affinity tiers on those plots and a third meaning would collide with both. A campaign that sets no `Class:` sees no outlines, unchanged from before.
- [x] Add **Use potentials** as the first Prediction setting, on by default: Boltz's FK steering and physical-guidance coordinate update were hardcoded on, with no way to turn them off from the web form or the CLI. `--no-potentials` now threads through to `boltz predict`, which matters because that guidance update is one of the places a diffusion trajectory can diverge to NaN.
- [x] Make single-target retries actually isolated: staging one YAML did not scope the
  run, because `boltz predict` rebuilds its manifest from every processed record and
  iterates that, so a "one at a time" retry re-ran the whole campaign in one process and
  one raising target took the rest down with it. Each batch now parks the other records
  for its duration, and a retry pass that completes nothing aborts instead of repeating.
- [x] Ship `patches/apply_boltz_patches.py` for four `boltz` defects -- containment of
  numerical failures, a device-correct fp32 alignment guard, a NaN diagnostic that names
  the offending tensor, and an affinity phase that skips targets with no `pre_affinity`
  file -- verified by a `boltz_patches` preflight row so a `boltz` upgrade cannot silently
  revert them.
- [x] Add `--no-potentials` and default the run settings to the values a real 26-target
  GPCR campaign needed (`--workers 0`, `--max-msa-seqs 4096`, `--memory-warn-tokens 1500`).
- [x] Make an OOM skip reclaim memory on Apple silicon (`torch.mps.empty_cache()`), and
  record each completed target's peak RSS to `.boltzmaker_target_memory.jsonl`.
- [x] Stop one unusable Pfam mapping discarding every domain for a structure. PDBe returns `author_residue_number: null` when a domain boundary is not observed in the deposited model -- 3 of 6 mappings for `7dty`, including the receptor's own PF02793 -- and that null reached `range()`, raising `'NoneType' object cannot be interpreted as an integer` and losing the usable domains with it. A real GIPR campaign therefore had no motifs and `compare-sse produced no comparable targets`; it now writes 27 rows across both families.
- [x] Make boltz's full-precision guards work off CUDA. It wraps its numerically fragile steps -- triangular attention, pairformer, attention, the distogram and confidence heads, the encoders and the diffusion sampler -- in `torch.autocast("cuda", enabled=False)`, because they overflow in reduced precision. The device type is hardcoded, so on Apple silicon (autocast device_type `mps`) all **19 sites across 12 files** are inert and those steps run in bfloat16 regardless. Measured on torch 2.10: inside an MPS bf16 autocast a matmul under boltz's own guard still returns bfloat16; with the fix it returns float32. Nesting a second guard keeps it a no-op on CUDA.
- [x] Make an unattended run need nothing watching it. Recycle the Boltz process every
  `Targets per invocation` targets (default 4), because Apple's allocator only returns
  everything on process exit -- held memory floored at ~20GB after one target and grew
  ~1.9GB per target against a 55.7GB ceiling, which is why a run had 0 out-of-memory
  skips in its first four targets and 3 in its last four. Apply the boltz patches from
  BoltzMaker itself rather than only from `run_campaign.sh`, so a direct `all` or a
  rebuilt environment cannot run unpatched. Stop a Boltz that has said nothing for an
  hour and hand its targets to the retry ladder, instead of waiting on a wedged worker
  that will never exit. Together these retire the external watchdog.
- [x] Make a finished campaign read as an answer rather than a listing: Affinity ahead
  of Confidence, rows ranked by predicted pIC50 (apo rows sinking, ties stable),
  click-to-sort on every column of the summary and SSE tables with the indicator shown
  up front, and a Pockets panel naming each constraint and the ligands run against it.
  The analysis page lifts these panels out of each run's stored dashboard rather than
  building them, so `web/deploy/refresh_run_reports.py` re-renders the two that are a
  pure function of a bundle's `boltz_input.md` and `boltz_summary.csv` -- leaving every
  other panel byte-for-byte -- and already-uploaded runs get the change too. Clearing
  the server's `panels.json` caches is part of that: 61 of them would otherwise have
  gone on serving the old panels.
- [x] Put a viewer under the Pockets table: every receptor superposed in one grey,
  every ligand in its pocket's colour (pocket 1 green, pocket 2 blue, the
  unconstrained baseline always red), a checkbox per target, and the same spin/reset
  controls as the Superposed targets pane. Only targets that bind something are drawn
  -- an apo target has no pose to place -- so the 15-target 5-HT2 campaign shows its
  12. Which pocket a target used is recovered from its own stem, matching the whole of
  `family_ligand_code` rather than the suffix, so a ligand that happens to share a
  pocket's name is not misread as a constrained run.
- [x] Settle on one user-facing vocabulary -- **proteins, co-folded partners, ligands,
  pockets, ligand-free companions, predictions** -- and use it everywhere. The summary
  table headed its receptor column "Target" while the list below it called a prediction
  a target: one word for two things on one page. Proteins are counted by group, so the
  5-HT2 panel's nine `Protein:` blocks are its three receptors. The analysis page opens
  with those six as KPI boxes, in the order the prepare form asks for them, and the
  campaign summary reports the same six numbers.
- [x] Rank the summary table by predicted pIC50 rather than by binder probability.
  Measured across 24 ligand targets on the GLP1R/GIPR campaign, the binary head
  correlated with pIC50 at **r = +0.07** and returned nothing above 0.71 for a set of
  four real, characterised compounds. Its mean was flat across ligands (0.34-0.51)
  while tracking the *pocket condition* instead (0.30 unconstrained, 0.50-0.51
  constrained) -- it was reporting how a target was set up, not what was in the site.
  Orforglipron, a confirmed potent GLP1R binder, scored 0.59 and ranked below
  compounds it beats experimentally by orders of magnitude. pIC50 put the same four in
  their known order (orforglipron 11.2, then the other three at 9.8, 8.4 and 7.9), so
  that is what the table ranks on. A binary binder/non-binder score also has nothing to separate when
  every ligand in a campaign is a real binder.
- [ ] Classify the failure before retrying, and escalate along the axis that addresses it:
  a memory ladder (isolation, then `--max-msa-seqs 2048`) and a NaN ladder
  (`--no-potentials`, then fp32). Retrying with identical parameters is already known to be
  worthless -- 20 invocations produced nothing. Any rung past the first changes the science,
  so the rung used has to appear in the report. Do not vary `--mps-watermark` (a hard
  ceiling, not a pressure valve), `--workers` (already at its floor of 0), or the seed (the
  failing run was unseeded and still failed identically 20/20).
- [ ] Re-derive `preflight`'s size check from the recorded peaks rather than
  `--memory-warn-tokens`, so it reports "this is the size of a target that peaked at 61GB
  here" instead of a threshold someone guessed.
- [x] Recover `GLP1R_orfo`, the one target whose diffusion diverges. `--no-potentials`
  confirmed the potentials were the cause (16.8A vs 2154A), but sampling three targets
  differently from the other 21 is not a fix. Two clamps contain it instead -- a
  gradient bound anchored to the trajectory's quietest scale, and a 0.1A cap on how far
  one guidance step may move an atom -- and all three now land within 2A of that
  control with steering on, so the whole matrix is comparable.
- [ ] Work out whether the NaN divergence is bf16-specific by exposing Boltz's hardcoded
  `precision="bf16-mixed"` as an option, rather than patching it per incident.
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
