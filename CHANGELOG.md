# Changelog

All notable changes to BoltzMaker are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No versioned releases yet --
everything so far is tracked under `Unreleased`.

## [Unreleased]

### Added
- Styled CLI: a small "BoltzMaker" ASCII banner (marcdeller.com brand blue, same
  `pyfiglet` `small_slant` font as the ChemSage project) plus `ok`/`info`/`warn`/`err`/
  `step` icon helpers, replacing all ~89 previously-plain `print("BoltzMaker: ...")`
  call sites across `setup`/`setup-plip`/`new`/`format`/`run`/`analyze`. Built as a
  stdlib-only ANSI layer (no new dependency) so it works even before the managed venv
  exists; respects `NO_COLOR` and auto-disables on a non-tty (piped output, CI, log
  redirection). The `new` wizard's prompts get a coloured `?` marker and `y/N` hints;
  `preflight`'s summary table gets a rounded border, brand header, and coloured PASS/
  WARN/FAIL icons; the `run` progress bar gets brand-coloured spinner/bar/memory
  columns.
- `pixi.toml`/`pixi.lock`: an alternative, unified installation path (macOS + Linux/
  CUDA) via [pixi](https://pixi.sh), replacing the need to separately run `setup` +
  `setup-plip` -- pixi solves conda-forge (rdkit, gemmi, OpenBabel, PyMOL) and PyPI
  (boltz) packages together in one reproducible, committed lockfile. `install.sh`
  bootstraps it (installs pixi if missing, then `pixi install` + `pixi run
  postinstall` for plip/pdb-tools, which sit outside pixi's own solver -- see the
  file's own comments for why). `BoltzMaker.py` detects it's running inside a
  pixi-provisioned environment (via `CONDA_PREFIX`, covering both `pixi run`/`pixi
  shell` and a Tier B pack's plain `source activate.sh`) and skips its own `.venv`/
  `.plip_env` bootstrap entirely in that case; `setup`/`setup-plip` refuse to run
  there with a redirect instead. `docs/tier_b_offline_install.md` covers building and
  using a fully offline self-extracting installer (`pixi-pack --create-executable`,
  one per platform, no `pixi`/`conda`/network needed on the target machine) and its
  known caveats -- three PyPI packages boltz hard-pins to versions that are sdist-only
  (`ihm`, `modelcif`, `antlr4-python3-runtime`) silently vanish from a
  `--ignore-pypi-non-wheel` pack and crash the packed `boltz` CLI on any invocation
  unless sourced from conda-forge instead (now are); a fourth, `fairscale`, needs one
  extra `pip install` after unpacking specifically because conda-forge's own build of
  it hard-requires an incompatible conda-managed pytorch. Verified end-to-end against
  a genuinely fresh extraction (old `.venv`/`.plip_env` renamed out of the way, no
  `pixi` on PATH) for the osx-arm64 pack; the linux-64 pack cross-builds successfully
  but hasn't been run on a real CUDA machine.
- `write_html()`'s generated dashboard now posts its own real content height to any
  parent window via `postMessage` on load, resize, and via a `ResizeObserver` on
  `<body>` -- lets a page embedding the dashboard in an iframe (e.g. `findings.md`'s
  "Interactive dashboard" section) size the iframe to the actual content instead of
  guessing a fixed height, since a cross-origin iframe can't otherwise be measured or
  resized from the embedding page's own JS. A first version re-posted only at a couple
  of fixed delays after load rather than continuously observing -- confirmed
  insufficient directly (this page's own embedded PLIP images, web fonts, and the
  ligand-grid pager can all reflow content well after those fixed delays elapse,
  leaving a residual scrollbar); the `ResizeObserver` version re-posts on every actual
  layout change instead of guessing how long reflows take. `findings.md`'s dashboard
  embed moved to the end of the document (after Technical notes) and uses this
  handshake instead of a fixed 900px height that gave the embedded dashboard its own
  internal scrollbar. The embed's `src` (and its "open it directly" link) also switched
  from the absolute `bellcheddar.github.io` URL to a relative `boltz_dashboard.html`
  path, matching the two chart PNGs' own relative paths -- confirmed directly that the
  absolute-URL version was silently showing whatever dashboard was last *pushed*, not
  the current local one, since none of this session's chart changes (colorbar, the new
  pIC50-vs-binder chart, the title rename, etc.) had been pushed yet.
- New optional `Role:` field on a `Ligand:` block (`agonist` / `antagonist`) -- purely
  for reporting, never affects `generate`/`run`. When set on at least one ligand in the
  campaign, the dashboard's "pIC50 vs confidence score" scatter (renamed from "Confidence
  vs affinity") and the new "pIC50 vs binder probability" scatter (below the "Interaction
  counts by type" chart, axes: binder probability on x, pIC50 on y) shape-code points by
  pharmacology (circle = agonist, diamond = antagonist) with a legend; campaigns that
  don't set `Role:` see a single unlabelled trace, unchanged from before. Both charts
  colour points by tier -- confidence tier (green/amber/red, matching the Summary
  table's shield icon) for pIC50-vs-confidence, affinity tier (matching the bullseye
  icon) for pIC50-vs-binder -- via a continuous Plotly colourscale + colorbar legend
  (the same style as the Family x ligand selectivity heatmap's own colorbar), replacing
  the old flags-based red/green colouring and giving both charts an explicit legend for
  what the colour means, not just the shape. The shape/pharmacology legend sits inside
  the plot area's top-left corner (not Plotly's default outside-right position), since
  that default position collided visually with the colorbar. Applied `Role:` to
  `5ht2_gq_panel`'s six ligands; neither chart shows an
  agonist/antagonist cluster distinct from Gq-bound status, consistent with the
  campaign's own agonist-vs-antagonist statistical finding (see `findings.md`, which also
  shows both charts side by side at half width, and splits its SSE motif-shift table's
  "Ca centroid shift" into grouped No Gq / Gq / Δ sub-columns).
- New optional `Group:` field on a `Protein:` block: a shared display/report name for
  multiple `Protein:` blocks that represent the same underlying receptor (e.g. with vs
  without a co-folded partner, or a predicted apo variant) but must otherwise stay
  separate family ids under the hood -- `5ht2_gq_panel`'s `5HT2A`/`H2ANG`/`H2AAP` all
  set `Group: 5HT2A`, for instance (also applied to `adrb2_gs_panel`'s `ADRB2`/`AR2NG`,
  the same pattern). Defaults to the family's own id when unset, so existing campaigns
  are unaffected.
- New shared `{group}_{partners}_{ligand}` display-name convention (partners joined
  with `+`, omitted when there are none; `apo` in place of a ligand for a ligand-free
  target), e.g. `5HT2A_GNAQ+GNB1+GNG2_RISP` / `5HT2A_RISP` / `5HT2A_apo`, replacing the
  internal disambiguation stem (`H2ANG_RISP`, `H2AAP`) everywhere a single target needs
  one human-readable label -- not just the Summary table's "Target" column, but every
  chart (ranked pIC50/confidence, confidence-vs-affinity scatter, interaction counts,
  the per-family residue-interaction fingerprint heatmap, `compare-sse`'s per-motif RMSD
  bar chart and motif x target heatmap), every card title (each target's binding-site
  panel, each family's fingerprint panel), the campaign-summary target list, and the
  selectivity pivot's column headers (both the dashboard's PNG heatmap and the XLSX
  `selectivity` sheet). A family-level variant (`{group}_{partners}`, no ligand) is used
  wherever a whole family rather than one target needs a label. The raw, precise
  per-variant ids (`family_id`/`target_stem`) are always kept alongside the display name
  in every underlying CSV (`boltz_summary.csv`, `boltz_sse_comparison.csv`) and in
  `boltz_summary.xlsx`'s `targets` sheet, for anyone cross-referencing against actual
  output filenames or doing further analysis -- only the human-facing views (dashboard,
  `boltz_summary_view.csv`, the `selectivity` sheet, `compare-sse`'s own dashboard/HTML)
  switch to the display name.
- New "Partner" column in the dashboard's Summary table (Identity group, between Target
  and Ligand): lists each target's co-folded partner chain(s) (e.g. `GNAQ, GNB1, GNG2`),
  blank when a target has none. Hidden automatically when no target in the campaign has
  any partners, the same conditional-by-content rule already used for `protein_iptm`.
- The Summary table's rows are now grouped by `Group:` (or family id when unset), with a
  blue top border on the first row of each new group -- the same blue used for column
  groups, just rotated 90 degrees. Rows already come out of the manifest grouped by
  family, so this only detects the group boundary, no re-sorting.
- `run`/`all` now automatically retries a target that doesn't complete (e.g. an OOM
  crash), instead of just reporting the failure and stopping there -- a real 4-target
  cascade on `5ht2_gq_panel` showed why this matters: an OOM during structure
  prediction for 2 of 6 large targets run together (boltz's own clean-fail path, not a
  crash) left a `pre_affinity_*.npz` missing, which then crashed the shared affinity
  phase and took 2 more already-succeeded targets down with it. The first attempt runs
  exactly as before (grouped); each retry after that isolates every still-incomplete
  target into its own single-target `boltz predict` invocation with a 15s pause first
  (a crashed subprocess's MPS/Metal memory is only released once it fully exits, so
  this gives the OS a moment to reclaim it) -- the same mitigation that recovered the
  real cascade above. New `--max-retries` flag (default 2, `0` to disable and match the
  old fail-once behavior); a target still incomplete after all retries is reported
  clearly and the rest of the pipeline still proceeds.
- `compare-sse` is now a core part of `analyze`/`all`, not a standalone opt-in step --
  every `analyze`/`all` run automatically compares apo vs holo for every family that
  has an `Apo structure:` configured, and the standalone `compare-sse` command still
  exists for re-running it on its own (e.g. after adding an apo structure without
  re-running `boltz predict`). New `--skip-sse` flag to opt out, mirroring
  `--skip-interactions`. The dashboard's "Secondary structure shifts" card is written
  unconditionally now: a "Family coverage" table lists every protein family and its
  status (`OK`, `No apo structure configured`, `Apo structure file not found`, `No
  motif annotation available`, `No predicted (holo) structures yet`) so a family with
  no `Apo structure:` reads as "not configured" rather than silently vanishing from
  the dashboard, plus an "Overall shift statistics" summary (targets/motifs compared,
  mean/median/max Ca RMSD and where the largest shift landed, mean centroid shift,
  total flagged phi/psi residues, kinase DFG/alphaC state-change counts) above the
  full per-motif table. A metric that genuinely wasn't computed for a given motif
  (e.g. axis rotation for a loop, DFG state for a non-kinase family, SSE boundary
  shift with no DSSP available) now renders as an explicit `N/A` in both
  `boltz_sse_comparison.csv` and the dashboard table, rather than a blank cell. New
  `boltz_sse_family_status.json` sidecar (per-family coverage, machine-readable) next
  to `boltz_sse_comparison.csv`. `analyze`'s auto-run never aborts the pipeline over
  this (unlike the standalone command, which still exits with a clear error if you
  explicitly ask for a `--family`/`--target` that doesn't exist).
- New `compare-sse` command: compares secondary-structure-element shifts between a
  protein family's apo (unbound) reference structure and its predicted holo target(s),
  grouped by biologically annotated motif rather than raw DSSP fragments -- GPCR
  transmembrane helices (via GPCRdb's generic-numbering service), kinase pocket motifs
  (hinge, gatekeeper, catalytic loop, DFG, alphaC-Glu, catalytic Lys, via KLIFS), or
  generic Pfam domain boundaries as a universal fallback (via PDBe's SIFTS mapping),
  auto-selected per family or set explicitly with a new `Family type:` field. Driven by
  two new optional `boltz_input.md` fields on a `Protein:` block, `Apo structure:` (a
  path to a reference structure) and `Apo chain:` (optional explicit chain id).
  Superposes apo onto holo using only the family's stable, non-binding-site-adjacent
  residues (gemmi's `superpose_positions`) so ligand-induced local shifts don't skew
  the global fit, then reports per-motif Ca RMSD, centroid shift, helix-axis rotation
  and kink angle, SSE boundary shift (deposited HELIX/SHEET records, or an external
  `mkdssp`/`dssp` binary as a fallback), flagged phi/psi outliers, and (kinases only) a
  coarse DFG-in/out and alphaC-in/out state classification. Writes a campaign-level
  `boltz_sse_comparison.csv`, a standalone `boltz_sse_comparison.html` (Plotly charts,
  vendored the same way as the main dashboard), and a plain-text PyMOL `.pml` script per
  target under `boltz_sse_comparison_sessions/` (colors/labels each motif, highlighting
  those above a significance threshold -- opens in any local PyMOL, no pymol dependency
  in the main venv). New `sse_comparison/` package; new `--phi-psi-threshold`,
  `--dfg-distance-threshold`, `--alphac-distance-threshold`, `--no-pymol`,
  `--refresh-cache` flags. New `requests` dependency (GPCRdb/KLIFS/PDBe REST calls);
  `opencadd-klifs` was the originally planned KLIFS client but doesn't exist on PyPI and
  its conda-forge build (`opencadd`) currently fails to install (a stale `biopython<=1.77`
  pin that no longer resolves) -- KLIFS's own public REST API is used directly instead.
  `mkdssp`/`dssp` is an optional external prerequisite (not bundled) for the
  SSE-boundary-shift metric specifically; every other metric works without it.
- First pytest test suite in the repo (`tests/test_sse_comparison.py`, 27 tests,
  `requirements-dev.txt`): every `compare-sse` annotator is exercised against real
  fixture data (PDB 1M14 apo EGFR kinase domain vs the `egfr_covalent` example's real
  Boltz holo prediction; PDB 2RH1 apo beta2AR vs the `adrb2_gs_panel` example's real
  Boltz holo predictions) with GPCRdb/KLIFS/PDBe network calls replaced by an injectable
  fake client seeded with real, previously-verified API responses -- fully offline,
  deterministic, and fast (~2s), no HTTP-mocking library needed. Verified against known
  ground truth along the way: GPCRdb/KLIFS motif assignments landed exactly on
  textbook residues (EGFR's real gatekeeper T790, hinge Met793, catalytic Lys745,
  DFG-Asp855; beta2AR's real 7TM span), and the apo/holo comparison reproduced the
  best-known result in GPCR structural biology (TM6 shows the largest shift of any
  transmembrane helix between the inactive apo structure and an agonist/Gs-bound
  prediction).
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
- Native ligand-free (apo) target support: a `Protein:` block can now set
  `Ligands: none` to generate exactly one ligand-free target for that family, running
  through the normal `generate`/`preflight`/`run`/`analyze` pipeline alongside every
  other target in the same campaign (same manifest, same staged `boltz predict`
  batch) -- no more hand-building a YAML and a separate staging directory to fold a
  receptor alone. The generated YAML has no ligand entity, no pocket constraint, and
  no affinity property (affinity is meaningless without a binder); its target stem is
  just the family id (e.g. `5HT2A`, not `5HT2A_LIG1`). `--skip-interactions`/PLIP and
  `predict_affinity` are both automatically skipped per-target for apo targets even
  when the rest of the campaign has them on. Preflight's `memory_heuristic` and
  `yaml_validity` checks both account for ligand-free targets correctly (sequence +
  partner size only, no false "missing affinity property" failure).

### Fixed
- `adrb2_gs_panel`'s antagonist target no longer co-folds the Gs alpha partner. The
  original campaign crossed one `ADRB2` family (with `Partners: GNAS`) against both
  ligands, so the antagonist prediction got a Gs chain too -- but Gs only forms a
  stable ternary complex with an *active*, agonist-bound receptor in reality, and
  Boltz has no constraint against predicting one anyway when asked. Confirmed
  directly: the two resulting holo structures superposed at 0.38 Angstrom RMSD over
  the reference-region scaffold, i.e. essentially the same fold, silently defeating
  the point of comparing an agonist against an antagonist via `compare-sse`. Split
  into two `Protein:` blocks sharing one sequence, each scoped to one ligand via
  `Ligands:` -- `ADRB2` (agonist ISO1, +Gs) and `AR2NG` (antagonist PRO1, no partner,
  "ADRB2, No Gs" within the 5-character chain-id limit). Re-running the antagonist
  target this way gives a real conformational difference: 1.28 Angstrom holo-holo
  RMSD (up from 0.38), TM6 shift roughly doubled for the agonist relative to the
  unliganded apo reference (5.84 vs 3.06 Angstrom) -- and finishes in a fraction of
  the original run time (25m vs the two-target campaign's 1h 28m), since it no
  longer folds Gs alpha's ~394 extra residues at all.
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
- "Ligand structures" panel's "Download PDF" and "Download SMILES" links now sit side by
  side on one line, matching the Summary table's own download-links style (was two
  separate lines).
- Campaign summary table gains a third "Details" column: a linked path to the input
  file, each protein/partner's id and sequence length, each ligand's id and SMILES-vs-CCD
  source, the full list of target stems, which specific ligands were flagged in ligand
  chemistry review (pointing at the card below), and a plain-English gloss for the more
  cryptic run parameters (accelerator, MPS watermark, recycling/sampling steps, etc.).
  Value stays short and scannable; Details carries everything that would otherwise
  clutter it.
- README polish pass: intro now mentions the `new` wizard and its reference-structure
  pocket-suggestion feature; Architecture section gains a small ASCII pipeline diagram
  above the stage table, which itself was trimmed to fit each row on one line more often;
  the `boltz_input.md` format example and the Commands usage block both have their
  trailing comments realigned to a single column; and the scaffold-highlighting section's
  colour table now lists every specific badge (S/A/N/Ph/SO3/salt) with a coloured-square
  icon next to its meaning, combined with the existing cluster-colour row.

### Verified
- Three real public-domain example campaigns in `examples/` (`t4_lysozyme`,
  `egfr_covalent`, `adrb2_gs_panel`), each run end to end on real hardware (Apple M1 Max,
  64GB) with real `boltz predict` GPU runs -- see the README's Examples section for
  measured run times and results.
- `5ht2_gq_panel`: all 15 targets (12 ligand-bound + 3 native apo) completed
  successfully end to end via `BoltzMaker.py all`, including the six large 4-chain
  receptor+Gq-heterotrimer complexes (~1250-1280 tokens) that previously crashed --
  see the MPS large-complex attention fix under Fixed below.

### Fixed
- `run`'s `boltz predict` subprocess is now wrapped with `caffeinate -i -s -m -w <pid>`
  on macOS (no-op if `caffeinate` isn't on `PATH`, e.g. CI/Linux) -- real, verified
  hygiene against sleep interrupting an in-flight GPU job, confirmed via `pmset -g
  assertions` holding the assertion for the subprocess's full lifetime.
- Fixed a crash where `boltz predict`'s affinity-prediction phase iterates over every
  staged/processed input regardless of whether that input's YAML declared a
  properties/affinity block, raising `FileNotFoundError` loading a `pre_affinity_*.npz`
  that only ever gets generated for the affinity ones -- hit whenever a campaign mixes
  native `Ligands: none` apo targets with `predict_affinity: yes` targets in the same
  batch. `run_boltz()` now splits any pending batch by `Target.needs_affinity` into up to
  two separate `boltz predict` invocations, both reusing the same staging/predictions
  directory so `find_any_predictions_dir` still sees one consistent output tree.
- Root-caused and fixed the large-complex MPS crash seen on `5ht2_gq_panel`'s six
  4-chain receptor+Gq-heterotrimer targets (~1250-1280 tokens): boltz's triangular
  attention computes the full row-wise QK^T score matrix for the whole complex in one
  unchunked matmul (scales as tokens x heads x tokens x tokens), which exceeds Apple's
  MPS single-tensor size ceiling past roughly 1250 residues and crashes the process
  inside PyTorch's internal tiled-bmm fallback. Each row's attention is independent, so
  chunking along that axis is exact, not an approximation. BoltzMaker's `setup` now
  patches this directly into the installed `boltz` package (idempotent, and checks
  boltz's exact source before patching so a future boltz upgrade that changes this
  function can't be silently mis-patched). Confirmed fixed end to end: all 15
  `5ht2_gq_panel` targets, including all six large complexes, now complete successfully
  on Apple M-series GPU with zero crashes.
- Dashboard generation crashed (`AttributeError: 'NoneType' object has no attribute
  'id'`) building the campaign-summary target list whenever a campaign included a
  native apo (`Ligands: none`) target, since that code path assumed every target has a
  ligand. Now handles the ligand-free case the same way the rest of the codebase
  already does.
- `compare-sse`'s GPCRdb annotator uploads the apo structure's own chain to GPCRdb's
  generic-numbering API as a temporary legacy PDB file, whose chain-id column is 1
  character -- BoltzMaker's own chain ids (the family stem, e.g. `H2AAP`) are routinely
  longer and made every GPCR family's annotation fail with "chain name too long for the
  PDB format". Renamed to a short placeholder for that temporary upload only; GPCRdb's
  response is matched back purely by residue number, never by chain name, so this is
  safe. Also wired up `5ht2_gq_panel`'s three `Apo structure:` fields, previously
  pointing at a `reference/*_apo_predicted.cif` path that was never actually generated,
  to the real Boltz-predicted apo cifs (`boltz_cif/H2AAP_model_0.cif` etc.) -- both
  fixes together bring all 12 ligand-bound `5ht2_gq_panel` targets into `compare-sse`
  for the first time, confirming the expected biology: TM6 centroid shift is
  consistently larger for the Gq-bound targets than their no-Gq counterparts across all
  three receptors.
- Summary table completeness for ligand-free (apo) targets: `ligand_id`, `iptm`/
  `ligand_iptm`/`protein_iptm` (no inter-chain interface exists for a monomer),
  affinity columns, and PLIP interaction counts now render as an explicit `N/A` for
  apo rows instead of a blank cell or a misleading `0.00`, matching the same
  explicit-N/A convention `compare-sse` already uses.
- The "Flags" column is renamed "Summary" and is icon-based now instead of a raw
  semicolon-joined flag string: a bullseye (affinity) and a shield (confidence) icon,
  each tinted green/amber/red by tier, with the exact value and interpretation as a
  hover tooltip. Boltz's own docs (`docs/prediction.md`) define `confidence_score`/
  `affinity_probability_binary` as [0, 1] with higher = better and 0.5 as the binder/
  non-binder decision boundary, but publish no tri-colour bands -- BoltzMaker's tiers
  reuse the existing `LOW_CONFIDENCE_THRESHOLD` (0.5) as the confidence red/amber
  boundary and a symmetric +/-0.2 buffer around the documented 0.5 binder boundary for
  affinity (green >= 0.7, red < 0.3 for both). Plain emoji can't be recoloured via CSS,
  so both icons are small inline SVGs tinted through a wrapping `<span style="color:
  ...">`. A `MISSING_OUTPUTS` failure collapses the cell to a single red cross (nothing
  was computed to score); `LOW_POCKET_PLDDT` appends a small amber warning icon, since
  it's a pocket-local metric neither the bullseye nor shield otherwise represents; the
  confidence/affinity mismatch flags (`HIGH_CONFIDENCE_POOR_AFFINITY` etc.) surface as
  extra tooltip text on both icons, on top of already being visually apparent as
  contrasting tier colours. The column is always shown now (previously hidden entirely
  whenever nothing was flagged), so a clean campaign reads as a row of green icons
  rather than the column silently disappearing, and apo rows' N/A bullseye no longer
  reads as another blank cell. A new legend to the right of the summary table's
  download links spells out all six tier/icon combinations. The underlying flag values
  and CSV export are unchanged (still plain text, for further analysis).
