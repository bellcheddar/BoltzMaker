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
  protonation state may need review -- all before any compute is spent. Surfaced in the
  dashboard as a "Ligand preparation" card below the campaign summary.
- Dashboard "Ligand structures" card: a paginated 5x5 grid of every ligand's rendered 2D
  structure, building on [smiles2grid](https://github.com/bellcheddar/smiles2grid)'s
  design. Stereocentre/ionizable-group findings are highlighted directly on each
  structure; ligands sharing a Bemis-Murcko scaffold (or a verified whole-group MCS as a
  fallback) are grouped, colour-highlighted, and depiction-aligned to a common
  orientation; a captioned legend states exactly what was found and on how many ligands.

### Fixed
- cif2plip ligand disambiguation now matches on InChIKey first, falling back to exact
  SMILES only if that fails. PLIP's own re-derived SMILES (via OpenBabel) can differ in
  canonical form from RDKit's, so a plain string match could silently miss the correct
  ligand in a multi-ligand campaign even though it was chemically identical.
- Plotly.js is now vendored (`vendor/plotly-2.35.2.min.js`) and inlined into every
  generated dashboard instead of loaded from a CDN `<script src>`. The example dashboard
  linked from the README (viewed via htmlpreview.github.io) showed every chart card
  empty even though the identical local file rendered correctly -- the CDN script wasn't
  executing in htmlpreview's injected-content context. Falls back to the CDN with a
  printed warning if the vendored file is ever missing.
- The per-family residue-interaction fingerprint heatmap is now interactive Plotly
  (was matplotlib) and shown for every family with interaction data, not just families
  with 2+ ligands -- it previously required 2+ ligands per family purely because that
  gate was inherited from the similarity-reordering step's own >=3-ligand requirement,
  not because a single ligand's contact row is uninformative; `t4_lysozyme` and
  `egfr_covalent` (one ligand each) were silently missing the panel entirely.
- Full table redesigned (design assist from Fable 5): columns grouped into named bands
  (Identity, Confidence, Affinity, Interactions, Structure) via a colspan header row,
  short human column labels instead of raw field names, `pIC50` and its ensemble stdev
  merged into one "value ± SD" cell instead of two separate columns, `cif_file` rendered
  as a short link instead of the raw filename, and narrow right-aligned numeric columns
  so a typical campaign fits without horizontal scroll. Also fixes a real bug: the
  previous hidden-columns list hardcoded a 2-chain assumption and leaked `chains_ptm_2`
  and all six 3-chain `pair_chains_iptm_*` columns, uncaught and unrenamed, into any
  campaign with a partner chain -- replaced with regex-pattern hiding that scales to any
  chain count. `protein_iptm` and the `Flags` column are now dropped automatically when
  every value in that campaign is zero/empty rather than always shown or hardcoded off.
- Renamed "Full table" to "Summary table" and moved it directly below the campaign
  summary card (was below the ligand-preparation/structures panels). Added a new
  `boltz_summary_view.csv` export mirroring exactly the columns/headers shown in that
  table (pIC50 and its stdev as two separate numeric columns rather than the HTML's
  merged "± SD" cell, since a CSV is for further analysis). The existing "Download CSV"
  link is now labelled "Download full CSV" to distinguish it from the new
  "Download summary CSV" link sitting next to it.
- "Open PyMOL session" renamed to "Download PyMOL session" and given the HTML `download`
  attribute, so clicking it saves the `.pse` file instead of navigating the browser to it.
- Each target's binding-site panel gains an interactive, auto-rotating [3Dmol.js](https://3dmol.org)
  view next to the existing static PyMOL image, built directly from the predicted mmCIF
  (3Dmol.js parses mmCIF natively, so no PDB conversion is needed -- Boltz's own chain
  names are longer than PDB's 1-character chain field allows and would need remapping
  otherwise), with the ligand highlighted and the view auto-zoomed to it. The static
  image also gets a "Download image" link, which it didn't have before. 3Dmol.js is
  vendored (`vendor/3Dmol-2.5.5-min.js`) and inlined the same way Plotly is, only when a
  campaign actually has interaction-analysis data to show.
- Fixed a real layout bug in the binding-site panel: the 3Dmol viewer div and its
  "Download PyMOL session" link were separate top-level siblings, so CSS Grid auto-placed
  them into two cells instead of one column, shifting the static image and contacts table
  out of alignment. Both are now wrapped in one `.md-side-viewer` container. Column order
  is now 3Dmol view / static image / contacts table, and all three columns match at a
  consistent 260px height (the table previously used `max-height: 320px`).
- Each target's contacts table gets its own "Download CSV" link.
- New `boltz_ligand_grid.pdf`: the dashboard's "Ligand structures" grid (same cells,
  pagination, severity borders, and scaffold highlighting as the HTML version -- computed
  once and shared between both renderers) exported as a print/share-friendly PDF via
  `reportlab`, in the style of smiles2grid's own PDF output, linked as "Download PDF"
  from the panel. Only written when a campaign has at least one SMILES ligand.
- New "Download SMILES" link on the "Ligand structures" panel: a `boltz_ligands.csv`
  with ID, SMILES, undefined-stereocentre count, ionizable groups, salt/fragment flag,
  MW, cLogP, and TPSA -- one row per SMILES ligand.
- Binding-site panel: all three "Download ..." links (PyMOL session, image, contacts CSV)
  now bottom-align to the same row regardless of how tall each column's own content is
  (contacts tables with many rows no longer push their link out of line with the other
  two). 3Dmol.js auto-rotation speed halved.
- The "Ligand structures" legend now spells out every badge abbreviation it uses (S, A,
  N, Ph, SO3, salt) next to its meaning, using the same badge-chip styling as the grid
  cells themselves, combined with the existing scaffold-cluster colour key.
- README Examples table gains an "Input" column linking each example's `boltz_input.md`.

### Verified
- Three real public-domain example campaigns in `examples/` (`t4_lysozyme`,
  `egfr_covalent`, `adrb2_gs_panel`), each run end to end on real hardware (Apple M1 Max,
  64GB) with real `boltz predict` GPU runs -- see the README's Examples section for
  measured run times and results.
