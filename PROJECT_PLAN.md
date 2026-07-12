# BoltzMaker Project Plan

This is the strategic view: why the project exists, what it deliberately does *not* try
to be, and how the open backlog is organized. For the live, checkable task list see the
README's "To do" section (near the bottom of [README.md](README.md)); for a history of
what's already shipped see
[CHANGELOG.md](CHANGELOG.md). This document doesn't duplicate either -- it's the layer
above both.

## Why this exists

Running a Boltz-2 batch campaign by hand means writing dozens of near-identical YAML
files, remembering the right CLI flags for whatever hardware you're on, and manually
digging through prediction JSONs afterwards -- repetitive, error-prone work that a
structural biologist or drug-discovery scientist shouldn't have to do by hand for every
campaign. BoltzMaker turns a single plain-text spec into the full pipeline: generated
inputs, environment/input validation (including ligand-chemistry checks), a monitored
run with Mac-safe memory defaults, and a rich, self-contained report.

It grew out of five smaller single-purpose tools the author had already written
separately (`generate_yaml`, `simple-zsh-script-to-run-boltz2`, `analyze-boltz2-results`,
`cif2plip`, `smiles2grid`) -- the project's core thesis is that a *single shared campaign
format* driving every stage is worth more than the sum of those separate scripts, since it
removes the re-typing and re-matching of target names between them.

## Goals

- **One input file drives everything.** `boltz_input.md` is the single source of truth
  from YAML generation through the final dashboard -- no stage should need information
  the input file doesn't already carry.
- **Fail before compute, not after.** Preflight (environment, inputs, memory heuristics,
  ligand chemistry) exists because a multi-hour Boltz run failing on a typo or a bad
  SMILES is a worse experience than catching it in seconds up front.
- **A report that's actually read, not just generated.** The dashboard is designed for a
  scientist scanning results, not just a data dump -- grouped tables, plain-English
  parameter explanations, interactive charts, and visual chemistry review are all in
  service of that.
- **No hidden dependencies on the user's machine.** Both managed environments
  (`.venv/`, `.plip_env/`) are self-bootstrapped from nothing; the dashboard vendors its
  own JS libraries rather than depending on a CDN being reachable or trustworthy at view
  time.
- **Approachable for a non-specialist.** The `new` wizard and the plain-English
  `boltz_input.md` field names exist so someone who isn't fluent in Boltz's own YAML
  schema can still run a correct campaign.

## Non-goals

- **Not a general molecular dynamics or docking tool.** BoltzMaker is an orchestration
  layer around Boltz-2 specifically; it doesn't try to replace or wrap other structure
  prediction or docking engines.
- **Not a web service.** No server component, no multi-user auth, no hosted version --
  it's a local CLI tool that happens to produce an HTML report, deliberately kept that
  simple.
- **Not trying to outrun Boltz's own roadmap.** Features that belong upstream in Boltz
  itself (new model capabilities, new confidence metrics) are out of scope here; BoltzMaker
  consumes what Boltz produces.
- **Not chasing feature parity with commercial cheminformatics/SAR platforms.** The
  ligand-chemistry and scaffold-highlighting features exist to catch real, specific
  failure modes seen in practice, not to become a general-purpose med-chem workbench.

## Current status

The core pipeline (`generate` / `preflight` / `run` / `analyze` / `all`), the `new`
wizard, optional PLIP-based interaction analysis, and a fairly rich interactive dashboard
(Plotly charts, a scaffold-highlighted ligand structure grid, an interactive 3Dmol.js
binding-site view, PDF/CSV exports throughout) are all built and verified against four
real public-domain example campaigns, including `5ht2_gq_panel` (a 3-receptor
agonist/antagonist/G-protein-trimer panel, 15 targets), which also verified Apple
Silicon MPS support for large multi-chain complexes: boltz's triangular attention was
crashing past ~1250 residues on an unchunked matmul exceeding MPS's tensor-size ceiling,
now fixed by chunking (patched automatically into the installed `boltz` package at
`setup` time). `compare-sse` (apo-vs-holo secondary-structure
motif shifts, GPCR/kinase/Pfam-fallback annotation) is now a core, always-on part of
`analyze`/`all` -- every family with an `Apo structure:` set is compared automatically,
with a "Family coverage" status table, an "Overall shift statistics" summary, explicit
`N/A` for metrics that genuinely weren't computed, and its own pytest suite (41 tests) --
the standalone `compare-sse` command still exists for re-running the analysis on its own.
A `Protein:` block can also set `Ligands: none` for a native ligand-free (apo) target,
running through the same manifest-driven pipeline and the same staged `boltz predict`
batch as every other target -- useful when no genuinely apo experimental reference
structure exists and one has to be predicted instead. See [CHANGELOG.md](CHANGELOG.md)
for the detailed, dated history.

## Roadmap

The README's To-Do checklist is the authoritative, checkable list; grouped here by theme
so the *shape* of the remaining work is visible at a glance.

**Reliability & reproducibility** -- making a fresh install and a repeated run trustworthy:
- Pin exact dependency versions in both installers + a cached/offline install mode
- Share `PIP_CACHE_DIR` between the two environments so `setup-plip` doesn't re-fetch
  wheels the main venv already has
- `BoltzMaker.py doctor` -- a post-install check that reports exactly which env/feature
  is broken, in-process
- An explicit Boltz model-weights cache dir + a `preflight` check for it

**Performance at scale** -- the real cost centre once campaigns get larger:
- Detect the MPS `torch.linalg.svd` CPU-fallback at `preflight` and warn with an
  estimated runtime multiplier for large multi-chain complexes
- A residue/chain-count-based runtime pre-estimator, plus logging which ops fall back to
  CPU on MPS
- Per-sample (not just per-target) checkpointing in `run`, so an interrupted multi-hour
  complex doesn't recompute completed diffusion samples

**Scientific rigor & analysis depth** -- turning raw predictions into decisions:
- A retrospective `benchmark` mode: known actives/co-crystal data per target family
  (ChEMBL/BindingDB/PDB) scored against predicted-vs-measured pIC50 correlation and pose
  RMSD, so a user has a trust score before committing to a real campaign
- A cross-target selectivity/triage view in the dashboard (confidence-vs-affinity
  quadrant flags for "high-confidence, high-affinity" hits)

**Quality & testing** -- the thing every other item above depends on staying correct:
- An end-to-end fixture run in CI plus unit tests for the `boltz_input.md` parser and
  JSON-metric flattening

## Considered but deferred

Ideas that came out of brainstorming sessions but were deliberately not added to the
active backlog -- kept here rather than lost, in case a future need makes one of them
worth picking up:

- **Multi-seed ensembling with built-in negative controls** -- run N seeds per target and
  report mean +/- spread instead of a single point estimate, plus optional known-non-binder
  decoy ligands as a sanity check that real candidates separate from noise.
- **A pluggable execution backend + containerization** -- local/SLURM/cloud dispatch and a
  Docker/Apptainer image bundling both managed environments, aimed at campaigns too large
  for a single Mac to run in reasonable time. The biggest architectural shift of the ideas
  here, so not undertaken lightly.
- **A provenance manifest + campaign registry** -- one reproducibility record per campaign
  (Boltz version, weights hash, git commit, input hash, seeds, environment, hardware)
  enabling a `diff` between runs and a shared registry across a team.

## How this document is maintained

Update **Current status** and the **Roadmap** groupings whenever the README's To-Do list
gains or loses items; update **Considered but deferred** when a new brainstorm produces
ideas worth keeping but not committing to yet. This file should stay short enough to read
in one sitting -- if a section starts accumulating detail, that detail belongs in
CHANGELOG.md or the README instead.
