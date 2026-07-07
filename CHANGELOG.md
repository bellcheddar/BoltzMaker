# Changelog

All notable changes to BoltzMaker are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No versioned releases yet --
everything so far is tracked under `Unreleased`.

## [Unreleased]

### Added
- Core pipeline: `generate` / `preflight` / `run` / `analyze` / `all`, driven by a plain
  labelled-text `boltz_input.md` spec (proteins, partners, ligands, and standalone
  constraint sentences for pocket contacts, covalent bonds, and distance constraints).
- Self-managed pip-only `.venv` (`setup`), independent of any pre-existing Python/conda.
- Mac/MPS memory safety: `PYTORCH_MPS_HIGH_WATERMARK_RATIO` capping, Mac-safe
  `--workers`/`--max-parallel-samples` defaults, a live memory monitor with
  swap-thrashing detection, and a `preflight` size heuristic -- all informed by a real
  ~65GB-on-a-64GB-Mac thrashing incident during testing.
- Two-row live progress bar during `run` (outer: targets done/ETA/memory; inner: current
  Boltz phase), parsed from Boltz's own log output.
- `preflight` checks: Boltz CLI reachability, GPU/MPS availability, disk space, iCloud
  "Optimize Mac Storage" dataless-file detection, YAML/SMILES validity, Boltz's 5-character
  chain-ID limit, and the memory-size heuristic.
- Idempotent, resumable `run`: already-complete targets are skipped automatically.
- `analyze` output: `boltz_summary.csv`/`.xlsx` (with a selectivity pivot sheet for
  multi-family campaigns) and a branded, single-file HTML dashboard.
- Interactive wizard (`BoltzMaker.py new`) that interviews a non-specialist user in plain
  English to write a new `boltz_input.md`.
- `setup-plip` + [cif2plip](https://github.com/bellcheddar/cif2plip) integration: real
  protein-ligand interaction profiling (PLIP) via a separate, self-bootstrapped
  conda-forge environment (micromamba), independent of the main pip-only venv.
- Wizard reference-structure suggestions: point the wizard at a co-crystal/homology
  structure and it suggests `Pocket contact:` residues, remapped onto the target's own
  numbering via sequence alignment (BLOSUM62 + affine gaps).
- Dashboard interaction analysis: per-target binding-site images (residues labelled,
  interaction distances shown -- PLIP's own images have neither), a contacts table per
  target, and a per-family residue-interaction fingerprint heatmap (ligands clustered by
  similarity, for SAR ranking).
- Dashboard campaign summary table: inputs, run parameters, and total boltz predict
  runtime, tracked across every `run` invocation via a JSON-lines history sidecar.
- Four interactive [Plotly](https://plotly.com/javascript/) charts in the dashboard
  (ranked pIC50, ranked confidence, confidence-vs-affinity scatter, interaction counts by
  type), replacing static matplotlib images for those four.
- `format` command: cosmetic comment-alignment/blank-line normalization for
  `boltz_input.md`, with a `--check` mode for CI-style verification.
- Ligand-preparation validation: `boltz_input.md` ligand SMILES are canonicalized at
  parse time (RDKit), and a new `preflight` check (`ligand_preparation`) flags undefined
  stereocentres, disconnected fragments (salts/counterions), and ionizable groups whose
  protonation state may need review -- all before any compute is spent.

### Fixed
- cif2plip ligand disambiguation now matches on InChIKey first, falling back to exact
  SMILES only if that fails. PLIP's own re-derived SMILES (via OpenBabel) can differ in
  canonical form from RDKit's, so a plain string match could silently miss the correct
  ligand in a multi-ligand campaign even though it was chemically identical.

### Verified
- Three real public-domain example campaigns in `examples/` (`t4_lysozyme`,
  `egfr_covalent`, `adrb2_gs_panel`), each run end to end on real hardware (Apple M1 Max,
  64GB) with real `boltz predict` GPU runs -- see the README's Examples section for
  measured run times and results.
