#!/usr/bin/env python3
"""BoltzMaker.py -- generate, preflight, run, and analyze Boltz-2 batch campaigns.

Usage:
    python3 BoltzMaker.py setup                          # create managed venv + install boltz
    python3 BoltzMaker.py setup-plip                      # optional: separate env for cif2plip
    python3 BoltzMaker.py new       [boltz_input.md]      # interactively write a new campaign
    python3 BoltzMaker.py generate  <boltz_input.md> ...
    python3 BoltzMaker.py preflight <boltz_input.md> ...
    python3 BoltzMaker.py run       <boltz_input.md> ...
    python3 BoltzMaker.py analyze   <boltz_input.md> ...
    python3 BoltzMaker.py all       <boltz_input.md> ...   # (also the default if no subcommand given)
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
VENV_DIR = SCRIPT_DIR / ".venv"

# Separate, optional environment for cif2plip (protein-ligand interaction analysis).
# Kept apart from VENV_DIR because its dependency chain (OpenBabel, PyMOL) needs
# conda-forge builds -- confirmed empirically: plip's own installer forces a from-source
# OpenBabel-binding build unless a working OpenBabel is already importable at build time,
# and the standalone PyPI `pymol-open-source` wheel has a hardcoded broken rpath to its
# original builder's machine. conda-forge's builds have neither problem.
PLIP_VENV_DIR = SCRIPT_DIR / ".plip_env"
CIF2PLIP_COMMIT = "2c3bf8b086ec022d81599b77a91b4713697a5636"

# Vendored (not CDN-linked) so the dashboard's charts render in contexts that don't
# execute a cross-origin <script src>, e.g. htmlpreview.github.io -- confirmed empirically
# that a CDN-loaded plotly.js silently fails to run there even though the exact same file
# works when opened directly in a browser, leaving every chart card blank.
PLOTLY_JS_PATH = SCRIPT_DIR / "vendor" / "plotly-2.35.2.min.js"

# Same rationale as PLOTLY_JS_PATH -- vendored so the interactive binding-site view has
# no external script dependency at all.
THREEDMOL_JS_PATH = SCRIPT_DIR / "vendor" / "3Dmol-2.5.5-min.js"

# cif2plip's own PLIP visualization never calls cmd.label(...) at all (checked its
# source directly) -- the stock PNG/pse have sticks and dashed interaction lines but no
# residue text. This small script (BoltzMaker's own, not vendored from upstream) loads
# the .pse PLIP already produced -- same camera/view/representations -- adds labels for
# the given contacting residues, and re-renders. Runs inside .plip_env (needs `import
# pymol`), invoked as a subprocess from the main venv.
_LABEL_RESIDUES_SCRIPT = '''\
import sys
import pymol
pymol.finish_launching(["pymol", "-qc"])
from pymol import cmd

session_path, output_path = sys.argv[1], sys.argv[2]
residues = [r.split(":") for r in sys.argv[3:]]

cmd.load(session_path)

# Residue (CA) labels: offset away from the atom (screen-space, so it holds
# regardless of viewing angle) so the text doesn't sit on top of the residue
# itself or its stick representation.
cmd.set("label_size", 18)
cmd.set("label_color", "black")
cmd.set("label_outline_color", "white")
cmd.set("label_font_id", 7)  # sans-serif bold -- more legible than PyMOL's default serif
cmd.set("label_position", (2.2, 2.2, 0))

for chain, resnr, restype in residues:
    sel = f"chain {chain} and resi {resnr} and name CA"
    if cmd.count_atoms(sel) > 0:
        cmd.label(sel, f'"{restype}{resnr}"')

# Interaction-line distance labels: PLIP draws each interaction via
# cmd.distance() (which computes and can show the actual measured distance)
# but hides the label by default. Show them, styled distinctly (smaller,
# grey) from the residue labels so the two don't visually compete.
cmd.set("label_size", 14, "Interactions")
cmd.set("label_color", "gray30", "Interactions")
cmd.show("labels", "Interactions")

cmd.set("ray_opaque_background", 0)
cmd.png(output_path, width=1200, height=900, dpi=150, ray=1)
'''


def _venv_bin(name: str) -> Path:
    return VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / name


def _plip_venv_bin(name: str) -> Path:
    return PLIP_VENV_DIR / "env" / ("Scripts" if os.name == "nt" else "bin") / name


def _plip_python() -> Path:
    return _plip_venv_bin("python")


def _plip_script() -> Path:
    return PLIP_VENV_DIR / "cif2plip" / "cif2plip.py"


def _plip_label_script() -> Path:
    return PLIP_VENV_DIR / "label_residues.py"


def _plip_available() -> bool:
    return _plip_python().exists() and _plip_script().exists()


# ==========================================================================
# `setup` -- stdlib-only, must work under whatever bare python3 the user has
# ==========================================================================

def _find_boltz_python() -> Path:
    # boltz pins numpy<2.0, and numpy 1.26.x has no prebuilt wheel for Python 3.13+
    # (only cp312 and earlier) -- building it from source fails against recent Xcode
    # Clang, so the managed venv must be built on 3.12, not whatever is newest.
    candidates = ["/opt/homebrew/bin/python3.12", "/usr/local/bin/python3.12", "python3.12"]
    for c in candidates:
        path = c if os.path.isabs(c) else shutil.which(c)
        if not path or not os.path.exists(path):
            continue
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True)
            if "3.12" in (out.stdout or out.stderr):
                return Path(path)
        except Exception:
            continue
    print("ERROR: could not find a python3.12 interpreter (checked /opt/homebrew/bin, /usr/local/bin, PATH).")
    print("Install one (e.g. `brew install python@3.12`) and re-run `setup`.")
    sys.exit(1)


def cmd_setup(argv: list) -> None:
    force = "--force" in argv
    yes = "--yes" in argv or "-y" in argv

    if VENV_DIR.exists() and force:
        shutil.rmtree(VENV_DIR)
    if not VENV_DIR.exists():
        interpreter = _find_boltz_python()
        print(f"BoltzMaker: creating venv at {VENV_DIR} using {interpreter}")
        subprocess.run([str(interpreter), "-m", "venv", str(VENV_DIR)], check=True)
    else:
        print(f"BoltzMaker: reusing existing venv at {VENV_DIR} (pass --force to recreate)")

    pip = _venv_bin("pip")
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=True)

    print("BoltzMaker: about to install boltz + dependencies into the managed venv.")
    print("  This pulls PyTorch (~2-3 GB) and, on the first `boltz predict` run,")
    print("  Boltz will download several GB of model weights over the network.")
    if not yes:
        resp = input("Continue? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            sys.exit(1)

    subprocess.run(
        [str(pip), "install", "boltz", "rich", "pandas", "openpyxl", "pyyaml", "rdkit", "matplotlib", "psutil",
         "scipy", "gemmi", "biopython", "plotly", "reportlab"],
        check=True,
    )
    freeze = subprocess.run([str(pip), "freeze"], capture_output=True, text=True, check=True)
    (VENV_DIR / "requirements.lock.txt").write_text(freeze.stdout)

    boltz_check = subprocess.run([str(_venv_bin("boltz")), "--help"], capture_output=True, text=True)
    print(f"BoltzMaker: boltz CLI check exit={boltz_check.returncode}")

    py = _venv_bin("python3")
    torch_check = subprocess.run(
        [str(py), "-c", "import torch; print('mps:', torch.backends.mps.is_available()); print('cuda:', torch.cuda.is_available())"],
        capture_output=True, text=True,
    )
    print(torch_check.stdout.strip() or f"WARNING: torch import check failed: {torch_check.stderr[-500:]}")
    print("BoltzMaker: setup complete. Run `python3 BoltzMaker.py all <boltz_input.md>` next.")


# ==========================================================================
# `setup-plip` -- separate, optional environment for cif2plip. stdlib-only, same as
# `setup` above; also runs before the bootstrap-relaunch so it works on a fresh
# checkout regardless of whether `setup` has ever been run.
# ==========================================================================

def _curl_download(url: str, dest: Path) -> None:
    # Shell out to curl (system trust store) rather than urllib.request -- some Python
    # installations (e.g. python.org framework builds) ship without properly configured
    # CA certificates, which breaks urllib's HTTPS entirely; curl doesn't have this problem.
    subprocess.run(["curl", "-fLsS", "-o", str(dest), url], check=True)


def _download_micromamba(dest: Path) -> None:
    import platform
    import tarfile
    import tempfile

    arch = platform.machine()
    plat = {"arm64": "osx-arm64", "x86_64": "osx-64"}.get(arch)
    if plat is None:
        print(f"ERROR: no known micromamba build for platform {arch!r}.")
        print(f"Install micromamba yourself (https://micro.mamba.pm) and place the binary at {dest}")
        sys.exit(1)
    url = f"https://micro.mamba.pm/api/micromamba/{plat}/latest"
    print(f"BoltzMaker: downloading micromamba from {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "micromamba.tar.bz2"
        _curl_download(url, tar_path)
        with tarfile.open(tar_path, "r:bz2") as tf:
            tf.extractall(tmp)
        shutil.copy2(Path(tmp) / "bin" / "micromamba", dest)
    dest.chmod(dest.stat().st_mode | 0o111)


def cmd_setup_plip(argv: list) -> None:
    force = "--force" in argv
    yes = "--yes" in argv or "-y" in argv

    if PLIP_VENV_DIR.exists() and force:
        shutil.rmtree(PLIP_VENV_DIR)

    micromamba = PLIP_VENV_DIR / "bin" / "micromamba"
    if not micromamba.exists():
        _download_micromamba(micromamba)

    env_dir = PLIP_VENV_DIR / "env"
    if not env_dir.exists():
        print("BoltzMaker: about to build a separate environment for cif2plip (protein-ligand")
        print("  interaction analysis) via conda-forge (python + gemmi + openbabel + pymol-open-source).")
        print("  This is roughly 1-1.5GB (mostly Qt/PyMOL's own dependencies), separate from")
        print("  BoltzMaker's own pip-only venv, and entirely optional -- BoltzMaker works fully")
        print("  without it.")
        if not yes:
            resp = input("Continue? [y/N] ").strip().lower()
            if resp != "y":
                print("Aborted.")
                sys.exit(1)
        print(f"BoltzMaker: creating {env_dir} via micromamba")
        subprocess.run(
            [str(micromamba), "create", "-y", "-p", str(env_dir), "-c", "conda-forge",
             "python=3.11", "gemmi", "openbabel", "pymol-open-source"],
            check=True,
        )
    else:
        print(f"BoltzMaker: reusing existing plip env at {env_dir} (pass --force to recreate)")

    pip = env_dir / "bin" / "pip"
    subprocess.run([str(pip), "install", "pdb-tools"], check=True)
    # --no-build-isolation: plip's own installer tries to build OpenBabel's Python
    # bindings from source unless `import openbabel` already succeeds where it runs --
    # isolated build sandboxes can't see this env's already-installed openbabel, so
    # isolation must be off for that check to find it and skip the (broken) rebuild.
    subprocess.run([str(pip), "install", "--no-build-isolation", "plip"], check=True)

    cif2plip_dir = PLIP_VENV_DIR / "cif2plip"
    cif2plip_dir.mkdir(parents=True, exist_ok=True)
    script_path = cif2plip_dir / "cif2plip.py"
    url = f"https://raw.githubusercontent.com/bellcheddar/cif2plip/{CIF2PLIP_COMMIT}/cif2plip.py"
    print(f"BoltzMaker: vendoring cif2plip.py (pinned commit {CIF2PLIP_COMMIT[:10]})")
    _curl_download(url, script_path)

    # Always (re)written, even when reusing an existing env, so an env built before this
    # script existed picks up residue labeling without needing a full rebuild.
    _plip_label_script().write_text(_LABEL_RESIDUES_SCRIPT)

    print("BoltzMaker: smoke-testing the plip environment...")
    smoke = subprocess.run(
        [str(env_dir / "bin" / "python"), "-c", "import pymol, openbabel, gemmi, plip; print('SMOKE_OK')"],
        capture_output=True, text=True,
    )
    if smoke.returncode != 0 or "SMOKE_OK" not in smoke.stdout:
        print("ERROR: plip environment smoke test failed:")
        print(smoke.stderr[-2000:])
        sys.exit(1)
    print("BoltzMaker: setup-plip complete.")
    print("  `analyze` will now run interaction analysis automatically, and `new` can suggest")
    print("  pocket residues from a reference structure.")


# ==========================================================================
# Bootstrap shim -- relaunch under the managed venv's interpreter so every
# command below this point can assume rich/pandas/yaml/rdkit are importable.
# ==========================================================================

def _bootstrap_or_relaunch(argv: list) -> None:
    subcommand = argv[1] if len(argv) > 1 else None
    if subcommand == "setup":
        cmd_setup(argv[2:])
        sys.exit(0)
    if subcommand == "setup-plip":
        cmd_setup_plip(argv[2:])
        sys.exit(0)

    venv_python = _venv_bin("python3")
    if not venv_python.exists():
        print("BoltzMaker: no managed environment found.")
        print(f"Run: python3 {SCRIPT_PATH} setup")
        sys.exit(1)
    if Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(str(venv_python), [str(venv_python), str(SCRIPT_PATH)] + argv[1:])
    # else: already running under venv python -- fall through to the rest of the script.


_bootstrap_or_relaunch(sys.argv)

# --------------------------------------------------------------------------
# Everything below only ever executes inside the managed venv.
# --------------------------------------------------------------------------

import argparse
import base64
import io
import json
import re
import threading
import time
from dataclasses import dataclass, field, asdict

import yaml
import pandas as pd
import psutil
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import plotly.graph_objects as go
import plotly.io as pio


# ==========================================================================
# Data model
# ==========================================================================

@dataclass
class Settings:
    output_dir: str = "./boltz_yamls"
    predict_affinity: bool = False


@dataclass
class Partner:
    id: str
    sequence: str
    type: str = "protein"  # protein / dna / rna
    modifications: object = None
    cyclic: bool = False
    msa: object = None


@dataclass
class ProteinFamily:
    id: str
    sequence: str
    partners: list = field(default_factory=list)
    pocket_contacts: object = None
    ligands: object = None
    modifications: object = None
    cyclic: bool = False
    msa: object = None
    bond_constraints: object = None
    contact_constraints: object = None
    templates: object = None
    apo_structure: object = None   # raw path string to a reference apo structure, or None
    apo_chain: object = None        # explicit apo chain id, or None (triggers auto-detect)
    family_type: str = "auto"        # "gpcr" | "kinase" | "auto" -- selects the compare-sse MotifAnnotator


@dataclass
class Ligand:
    id: str
    smiles: object = None
    ccd: object = None


@dataclass
class Campaign:
    settings: Settings
    partners: dict
    families: list
    ligands: list
    source_path: object = None


@dataclass
class Target:
    stem: str
    family_id: str
    ligand_id: str
    pocket_contacts_used: object = None


MANIFEST_FILENAME = ".boltzmaker_manifest.json"
RUN_HISTORY_FILENAME = ".boltzmaker_run_history.jsonl"


class MDParseError(Exception):
    pass


# ==========================================================================
# MDParser -- boltz_input.md is plain labelled text: blank-line-separated
# blocks (`Settings:` / `Protein: <name>` / `Partner: <name>` / `Ligand:
# <name>`, each followed by `Field: value` lines), plus standalone
# constraint sentences ("Covalent bond: X residue N atom A to Y residue M
# atom B") recognized anywhere in the file. No markdown, no YAML, no
# brackets or quoting -- one rule (`Label: value`, blank line between
# records) so the file reads like a filled-in form, not code.
# ==========================================================================

_RECORD_START_RE = re.compile(r"^(Settings|Protein|Partner|Ligand)\s*:\s*(.*)$", re.IGNORECASE)
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$")

_RECORD_ALLOWED_FIELDS = {
    "settings": {"output folder", "predict affinity"},
    "protein": {"sequence", "partners", "ligands", "modifications", "cyclic", "msa", "templates",
                "apo structure", "apo chain", "family type"},
    "partner": {"sequence", "type", "copies", "modifications", "cyclic", "msa"},
    "ligand": {"smiles", "ccd"},
}

# A statement's owner is always its first-mentioned chain, which must be a
# Protein -- this is how a standalone constraint sentence attaches to the
# family it belongs to.
_ENDPOINT = r"(\w+)\s+residue\s+(\d+)(?:\s+atom\s+(\w+))?"
_COVALENT_RE = re.compile(
    rf"^covalent bond:\s*(\w+)\s+residue\s+(\d+)\s+atom\s+(\w+)\s+to\s+(\w+)\s+residue\s+(\d+)\s+atom\s+(\w+)\s*$",
    re.IGNORECASE)
_POCKET_RE = re.compile(rf"^pocket contact:\s*{_ENDPOINT}\s*$", re.IGNORECASE)
_DISTANCE_RE = re.compile(
    rf"^distance constraint:\s*{_ENDPOINT}\s+to\s+{_ENDPOINT}(?:\s+within\s+([\d.]+)(?:\s+\w+)?)?\s*$",
    re.IGNORECASE)


def _find_comment_start(line: str):
    # '#' starts a comment only at col 0 or after whitespace, so a SMILES
    # triple bond like 'C#N' is never mistaken for one (no quoting exists in
    # this format, so that's the only rule needed).
    for i, ch in enumerate(line):
        if ch == "#" and (i == 0 or line[i - 1].isspace()):
            return i
    return None


def _strip_comment(line: str) -> str:
    idx = _find_comment_start(line)
    return line if idx is None else line[:idx]


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_yesno(value: str, default: bool) -> bool:
    v = value.strip().lower()
    if v in ("yes", "y", "true", "1"):
        return True
    if v in ("no", "n", "false", "0"):
        return False
    return default


def _parse_csv(value: str) -> list:
    return [_strip_quotes(v.strip()) for v in value.split(",") if v.strip()]


def _parse_modification_token(s: str) -> list:
    parts = [p.strip() for p in s.split(":")]
    if len(parts) != 2:
        raise MDParseError(f"invalid modification (expected CCD:position): {s!r}")
    return [parts[0], int(parts[1])]


def _match_statement(stripped: str, lineno: int):
    m = _COVALENT_RE.match(stripped)
    if m:
        c1, r1, a1, c2, r2, a2 = m.groups()
        return {"type": "bond", "owner": c1, "atom1": [c1, int(r1), a1], "atom2": [c2, int(r2), a2], "line": lineno}
    m = _POCKET_RE.match(stripped)
    if m:
        chain, res, atom = m.groups()
        token = [chain, int(res), atom] if atom else [chain, int(res)]
        return {"type": "pocket", "owner": chain, "token": token, "line": lineno}
    m = _DISTANCE_RE.match(stripped)
    if m:
        c1, r1, a1, c2, r2, a2, dist = m.groups()
        t1 = [c1, int(r1), a1] if a1 else [c1, int(r1)]
        t2 = [c2, int(r2), a2] if a2 else [c2, int(r2)]
        entry = [t1, t2, float(dist)] if dist else [t1, t2]
        return {"type": "distance", "owner": c1, "entry": entry, "line": lineno}
    return None


def _extract_statements(raw_lines: list):
    statements, remaining = [], []
    for lineno, raw in raw_lines:
        stripped = _strip_comment(raw).strip()
        if stripped:
            stmt = _match_statement(stripped, lineno)
            if stmt is not None:
                statements.append(stmt)
                continue
        remaining.append((lineno, raw))
    return statements, remaining


def _split_records(lines: list) -> list:
    records = []
    current = None  # [record_type, name, fields, lineno]
    for lineno, raw in lines:
        if raw.strip() == "":  # a genuinely blank line ends the record
            if current is not None:
                records.append(current)
                current = None
            continue
        stripped = _strip_comment(raw).strip()
        if not stripped:
            continue  # a comment-only line -- doesn't end the record, doesn't set anything
        m = _RECORD_START_RE.match(stripped)
        if m:
            if current is not None:
                records.append(current)
            record_type, name = m.group(1).lower(), _strip_quotes(m.group(2).strip())
            if record_type == "settings" and name:
                raise MDParseError(f"'Settings:' takes no value (line {lineno}): {stripped!r}")
            if record_type != "settings" and not name:
                raise MDParseError(f"'{m.group(1)}:' needs a name (line {lineno}): {stripped!r}")
            current = [record_type, name, {}, lineno]
            continue
        if current is None:
            continue  # stray content before the first record -- ignore
        fm = _FIELD_RE.match(stripped)
        if not fm:
            continue
        field_name, field_value = fm.group(1).strip().lower(), _strip_quotes(fm.group(2).strip())
        allowed = _RECORD_ALLOWED_FIELDS.get(current[0], set())
        if field_name not in allowed:
            print(f"BoltzMaker: WARNING: unrecognized field '{fm.group(1).strip()}:' in "
                  f"{current[0].capitalize()} '{current[1]}' (line {lineno}) -- ignored, typo?")
            continue
        current[2][field_name] = field_value
    if current is not None:
        records.append(current)
    return records


def _build_partner_record(name: str, fields: dict, lineno: int) -> Partner:
    if "sequence" not in fields:
        raise MDParseError(f"partner '{name}' missing Sequence (line {lineno})")
    copies = _parse_csv(fields["copies"]) if "copies" in fields else None
    modifications = [_parse_modification_token(t) for t in _parse_csv(fields["modifications"])] if "modifications" in fields else None
    return Partner(
        id=copies if copies else name, sequence=fields["sequence"], type=fields.get("type", "protein").lower(),
        modifications=modifications, cyclic=_parse_yesno(fields.get("cyclic", ""), False), msa=fields.get("msa"),
    )


def _build_family_record(name: str, fields: dict, partners: dict, statements: list, lineno: int) -> ProteinFamily:
    if "sequence" not in fields:
        raise MDParseError(f"protein '{name}' missing Sequence (line {lineno})")
    partner_ids = _parse_csv(fields["partners"]) if "partners" in fields else []
    for pid in partner_ids:
        if pid not in partners:
            raise MDParseError(f"protein '{name}' references unknown partner '{pid}' (line {lineno})")
    modifications = [_parse_modification_token(t) for t in _parse_csv(fields["modifications"])] if "modifications" in fields else None
    pocket_contacts = [s["token"] for s in statements if s["type"] == "pocket"] or None
    bond_constraints = [(s["atom1"], s["atom2"]) for s in statements if s["type"] == "bond"] or None
    contact_constraints = [s["entry"] for s in statements if s["type"] == "distance"] or None
    family_type = fields.get("family type", "auto").lower()
    if family_type not in ("gpcr", "kinase", "auto"):
        raise MDParseError(f"protein '{name}' has invalid Family type '{family_type}' "
                            f"(expected gpcr/kinase/auto, line {lineno})")
    return ProteinFamily(
        id=name, sequence=fields["sequence"], partners=partner_ids,
        pocket_contacts=pocket_contacts, ligands=_parse_csv(fields["ligands"]) if "ligands" in fields else None,
        modifications=modifications, cyclic=_parse_yesno(fields.get("cyclic", ""), False), msa=fields.get("msa"),
        bond_constraints=bond_constraints, contact_constraints=contact_constraints,
        templates=_parse_csv(fields["templates"]) if "templates" in fields else None,
        apo_structure=fields.get("apo structure"), apo_chain=fields.get("apo chain"), family_type=family_type,
    )


def _canonicalize_smiles(smiles: str) -> str:
    # Silent normalization only -- an invalid SMILES is left as-is here and reported by
    # preflight's check_smiles (parsing shouldn't fail or change error timing over a
    # chemistry problem). A consistent canonical form flowing through the YAML, the
    # summary table, and cif2plip's own ligand-matching (see _analyze_target_interactions)
    # is the actual payoff, not just cosmetics.
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        return Chem.MolToSmiles(mol) if mol is not None else smiles
    except Exception:
        return smiles


def _smiles_to_inchikey(smiles: str):
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        return Chem.MolToInchiKey(mol) if mol is not None else None
    except Exception:
        return None


def _build_ligand_record(name: str, fields: dict, lineno: int) -> Ligand:
    has_smiles, has_ccd = "smiles" in fields, "ccd" in fields
    if has_smiles == has_ccd:  # both True (ambiguous) or both False (missing)
        raise MDParseError(f"ligand '{name}' must specify exactly one of SMILES/CCD (line {lineno})")
    smiles = _canonicalize_smiles(fields["smiles"]) if has_smiles else None
    return Ligand(id=name, smiles=smiles, ccd=fields.get("ccd"))


# ==========================================================================
# Formatter -- purely cosmetic (comment-column alignment, blank-line spacing
# around record boundaries). Never changes parsed meaning; `cmd_format`
# validates via parse_md() before writing anything back.
# ==========================================================================

def _normalize_blank_lines(text: str) -> str:
    lines = text.splitlines()
    out = []
    for raw in lines:
        stripped = _strip_comment(raw).strip()
        if stripped and _RECORD_START_RE.match(stripped) and out and out[-1].strip() != "":
            out.append("")
        out.append(raw)
    result = "\n".join(out)
    return result + "\n" if text.endswith("\n") else result


def _format_block(block: list) -> list:
    parsed = []
    for line in block:
        idx = _find_comment_start(line)
        parsed.append((line.rstrip(), None) if idx is None else (line[:idx].rstrip(), line[idx:].rstrip()))
    candidates = [len(code) for code, comment in parsed if comment is not None and code.strip() != ""]
    if not candidates:
        return list(block)  # nothing to align (e.g. a pure comment block) -- keep as-is
    target_col = max(candidates) + 2
    out = []
    for code, comment in parsed:
        if comment is None:
            out.append(code)
        elif code.strip() == "":
            out.append(" " * target_col + comment)
        else:
            out.append(code.ljust(target_col) + comment)
    return out


def format_md_text(text: str) -> str:
    text = _normalize_blank_lines(text)
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        if lines[i].strip() == "":
            out.append(lines[i])
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].strip() != "":
            i += 1
        out.extend(_format_block(lines[start:i]))
    result = "\n".join(out)
    return result + "\n" if text.endswith("\n") else result


def cmd_format(md_path: Path, check: bool = False) -> None:
    original = md_path.read_text()
    parse_md(md_path)  # validate first: surfaces MDParseError / unknown-field warnings
    formatted = format_md_text(original)
    if formatted == original:
        print(f"BoltzMaker: {md_path} already formatted.")
        return
    if check:
        print(f"BoltzMaker: {md_path} would be reformatted (comment alignment / blank-line spacing).")
        sys.exit(1)
    md_path.write_text(formatted)
    print(f"BoltzMaker: reformatted {md_path}.")


# ==========================================================================
# Wizard -- `BoltzMaker.py new` interviews a non-specialist user in plain
# language and writes a boltz_input.md in the format above. Covers the
# common case only (proteins, partners, ligands, the three constraint
# sentence-types); rarer fields (modifications, cyclic, MSA override,
# templates, homo-oligomer copies) are left for hand-editing the file
# afterward.
# ==========================================================================

def _wiz_prompt(msg: str, default: str = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        val = input(f"{msg}{suffix}: ").strip()
        if val:
            return val
        if default is not None:
            return default


def _wiz_yesno(msg: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        val = input(f"{msg} ({hint}): ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("  please answer y or n")


def _wiz_name(msg: str, taken: set) -> str:
    while True:
        val = input(f"{msg}: ").strip()
        if not val:
            print("  a name is required")
        elif len(val) > 5:
            print(f"  '{val}' is {len(val)} characters -- Boltz needs chain ids MAX 5 CHARACTERS, try again")
        elif val in taken:
            print(f"  '{val}' is already used, pick a different name")
        else:
            return val


def _align_positions(ref_seq: str, target_seq: str) -> dict:
    # Maps 0-indexed ref_seq positions -> 0-indexed target_seq positions for aligned
    # (non-gap) regions only. BLOSUM62 + affine gaps -- standard protein alignment
    # defaults, not hand-rolled, since residue-index remapping here feeds directly into
    # constraint statements a user may accept without double-checking.
    from Bio import Align
    from Bio.Align import substitution_matrices

    aligner = Align.PairwiseAligner()
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
    aligner.open_gap_score = -10
    aligner.extend_gap_score = -0.5
    aligner.mode = "global"
    alignment = aligner.align(ref_seq, target_seq)[0]
    mapping = {}
    for (r_start, r_end), (t_start, t_end) in zip(*alignment.aligned):
        for offset in range(r_end - r_start):
            mapping[r_start + offset] = t_start + offset
    return mapping


def _wiz_reference_structure_suggestions(name: str, sequence: str) -> list:
    """Optionally analyze a reference structure with a bound ligand and suggest pocket
    residues for `name`, remapped onto `sequence`'s own numbering via pairwise sequence
    alignment. Returns a list of target-numbered residue ints (possibly empty)."""
    if not _wiz_yesno(f"Do you have a reference structure with a ligand already bound for {name} "
                       f"(co-crystal or homology model)", default=False):
        return []
    ref_path = Path(_wiz_prompt("  Path to the reference structure (.cif/.pdb/.mmcif)")).expanduser()
    if not ref_path.exists():
        print(f"  {ref_path} not found -- skipping")
        return []

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        print("  running cif2plip on the reference structure...")
        try:
            proc = _run_cif2plip(ref_path, work_dir)
        except subprocess.TimeoutExpired:
            print("  cif2plip timed out on that structure -- skipping")
            return []
        inter_csv = work_dir / f"{ref_path.stem}_interactions.csv"
        summ_csv = work_dir / f"{ref_path.stem}_ligand_summary.csv"
        pdb_path = work_dir / f"{ref_path.stem}.pdb"
        if proc.returncode != 0 or not inter_csv.exists() or not summ_csv.exists():
            print("  cif2plip couldn't process that structure -- skipping")
            return []

        inter_df = pd.read_csv(inter_csv)
        summ_df = pd.read_csv(summ_csv).reset_index(drop=True)
        if summ_df.empty:
            print("  no ligands detected in that structure -- skipping")
            return []

        if len(summ_df) == 1:
            chosen = summ_df.iloc[0]["ligand"]
        else:
            print("  Multiple ligands detected in the reference structure:")
            for i, r in summ_df.iterrows():
                print(f"    [{i + 1}] {r['ligand']} (SMILES: {r.get('smiles', '?')}, "
                      f"{r.get('total_interactions', '?')} interactions)")
            choice = input(f"  Which one is the relevant bound ligand? [1-{len(summ_df)}]: ").strip()
            try:
                chosen = summ_df.iloc[int(choice) - 1]["ligand"]
            except (ValueError, IndexError):
                print("  not a valid choice -- skipping")
                return []

        sub = inter_df[inter_df["ligand"] == chosen]
        if sub.empty:
            print("  that ligand has no recorded interactions -- skipping")
            return []
        ref_chain_id = sub.iloc[0]["prot_chain"]
        contact_resnrs = sorted(int(x) for x in sub["prot_resnr"].unique())

        try:
            import gemmi
            st = gemmi.read_structure(str(pdb_path))
            st.setup_entities()
            polymer = st[0][ref_chain_id].get_polymer()
            ref_seq = polymer.make_one_letter_sequence()
            resnr_to_pos = {res.seqid.num: i for i, res in enumerate(polymer)}
        except Exception as exc:
            print(f"  couldn't extract the reference chain's sequence -- skipping ({exc})")
            return []

        mapping = _align_positions(ref_seq, sequence)
        suggested, skipped = [], 0
        for resnr in contact_resnrs:
            ref_pos = resnr_to_pos.get(resnr)
            target_pos = mapping.get(ref_pos) if ref_pos is not None else None
            if target_pos is None:
                skipped += 1
                continue
            suggested.append(target_pos + 1)  # 1-indexed residue number, matching Boltz convention

        if not suggested:
            print(f"  none of the reference structure's contact residues could be mapped onto "
                  f"{name}'s sequence -- skipping")
            return []
        if skipped:
            print(f"  ({skipped} reference residue(s) had no equivalent position in {name}'s sequence, skipped)")
        print(f"  Found {len(suggested)} candidate pocket residue(s) from the reference structure: "
              f"{', '.join(str(r) for r in suggested)}")
        if _wiz_yesno("  Add these as pocket-contact constraints", default=True):
            return suggested
        return []


def cmd_new(md_path: Path) -> None:
    if md_path.exists() and not _wiz_yesno(f"{md_path} already exists -- overwrite", default=False):
        print("BoltzMaker: aborted, nothing written.")
        return

    print("BoltzMaker: let's set up a new campaign. Press Ctrl-C any time to cancel.\n")
    try:
        predict_affinity = _wiz_yesno("Predict binding affinity too (slower, adds Kd/pIC50 estimates)", default=False)
        out = ["Settings:", "Output folder: ./boltz_yamls",
               f"Predict affinity: {'yes' if predict_affinity else 'no'}"]

        used_names, known_partners = set(), set()
        partner_blocks, protein_blocks, statement_lines = [], [], []

        print("\nNow the protein(s) -- at least one is required.")
        first = True
        while first or _wiz_yesno("Add another protein", default=False):
            first = False
            name = _wiz_name("Protein short name (max 5 letters)", used_names)
            used_names.add(name)
            sequence = _wiz_prompt(f"Paste the amino acid sequence for {name}")
            block = [f"Protein: {name}", f"Sequence: {sequence}"]

            if _plip_available():
                for r in _wiz_reference_structure_suggestions(name, sequence):
                    statement_lines.append(f"Pocket contact: {name} residue {r}")

            if _wiz_yesno(f"Does {name} co-fold with any partner chains", default=False):
                partner_ids = []
                add_more = True
                while add_more:
                    pname = _wiz_name("  Partner short name (max 5 letters)", used_names)
                    if pname not in known_partners:
                        used_names.add(pname)
                        known_partners.add(pname)
                        psequence = _wiz_prompt(f"  Paste the sequence for partner {pname}")
                        partner_blocks.append([f"Partner: {pname}", f"Sequence: {psequence}"])
                    partner_ids.append(pname)
                    add_more = _wiz_yesno("  Add another partner", default=False)
                block.append(f"Partners: {', '.join(partner_ids)}")

            while _wiz_yesno(f"Add a constraint on {name}", default=False):
                choice = input("  [1] Covalent bond  [2] Pocket contact  [3] Distance constraint: ").strip()
                if choice == "1":
                    r1 = _wiz_prompt(f"  {name} residue number")
                    a1 = _wiz_prompt(f"  {name} atom name (e.g. SG for a cysteine sulfur)")
                    other = _wiz_prompt("  Name of the ligand/protein it bonds to")
                    r2 = _wiz_prompt(f"  {other} residue number")
                    a2 = _wiz_prompt(f"  {other} atom name")
                    statement_lines.append(f"Covalent bond: {name} residue {r1} atom {a1} to {other} residue {r2} atom {a2}")
                elif choice == "2":
                    r1 = _wiz_prompt(f"  {name} residue number")
                    statement_lines.append(f"Pocket contact: {name} residue {r1}")
                elif choice == "3":
                    r1 = _wiz_prompt(f"  {name} residue number")
                    other = _wiz_prompt("  Name of the other protein")
                    r2 = _wiz_prompt(f"  {other} residue number")
                    dist = _wiz_prompt("  Maximum distance in Angstrom", default="6.0")
                    statement_lines.append(f"Distance constraint: {name} residue {r1} to {other} residue {r2} within {dist} Angstrom")
                else:
                    print("  not a recognized choice, skipping")
            protein_blocks.append(block)

        print("\nNow the ligand(s) -- at least one is required.")
        ligand_blocks = []
        first = True
        while first or _wiz_yesno("Add another ligand", default=False):
            first = False
            name = _wiz_name("Ligand short name (max 5 letters)", used_names)
            used_names.add(name)
            kind = input("  SMILES or CCD code? [1] SMILES  [2] CCD: ").strip()
            if kind == "2":
                code = _wiz_prompt(f"  CCD code for {name}")
                ligand_blocks.append([f"Ligand: {name}", f"CCD: {code}"])
            else:
                smiles = _wiz_prompt(f"  SMILES for {name}")
                try:
                    from rdkit import Chem
                    if Chem.MolFromSmiles(smiles) is None:
                        print("  WARNING: rdkit couldn't parse that SMILES -- saved anyway, double-check it")
                except Exception:
                    pass
                ligand_blocks.append([f"Ligand: {name}", f"SMILES: {smiles}"])
    except (KeyboardInterrupt, EOFError):
        print("\nBoltzMaker: cancelled, nothing written.")
        return

    for block in protein_blocks + partner_blocks + ligand_blocks:
        out.append("")
        out.extend(block)
    if statement_lines:
        out.append("")
        out.extend(statement_lines)

    md_path.write_text("\n".join(out) + "\n")
    print(f"\nBoltzMaker: wrote {md_path}")
    print(f"Next: python3 BoltzMaker.py preflight {md_path}")


def parse_md(path: Path) -> Campaign:
    text = path.read_text()
    raw_lines = list(enumerate(text.splitlines(), start=1))
    statements, remaining = _extract_statements(raw_lines)
    records = _split_records(remaining)

    settings = Settings()
    partners: dict = {}
    protein_records, ligand_records = [], []
    for record_type, name, fields, lineno in records:
        if record_type == "settings":
            settings.output_dir = fields.get("output folder", settings.output_dir)
            settings.predict_affinity = _parse_yesno(fields.get("predict affinity", ""), settings.predict_affinity)
        elif record_type == "partner":
            partners[name] = _build_partner_record(name, fields, lineno)
        elif record_type == "protein":
            protein_records.append((name, fields, lineno))
        elif record_type == "ligand":
            ligand_records.append((name, fields, lineno))

    statements_by_owner: dict = {}
    for stmt in statements:
        statements_by_owner.setdefault(stmt["owner"], []).append(stmt)

    families, seen_fam = [], set()
    for name, fields, lineno in protein_records:
        if name in seen_fam:
            raise MDParseError(f"duplicate protein '{name}' (line {lineno})")
        seen_fam.add(name)
        families.append(_build_family_record(name, fields, partners, statements_by_owner.pop(name, []), lineno))

    if statements_by_owner:
        owner, stmts = next(iter(statements_by_owner.items()))
        raise MDParseError(f"a constraint (line {stmts[0]['line']}) names '{owner}' as the owning protein, "
                            f"but no 'Protein: {owner}' block exists")

    ligands, seen_lig = [], set()
    for name, fields, lineno in ligand_records:
        if name in seen_lig:
            raise MDParseError(f"duplicate ligand '{name}' (line {lineno})")
        seen_lig.add(name)
        ligands.append(_build_ligand_record(name, fields, lineno))

    if not families:
        raise MDParseError("no 'Protein:' blocks found")
    if not ligands:
        raise MDParseError("no 'Ligand:' blocks found")
    return Campaign(settings=settings, partners=partners, families=families, ligands=ligands, source_path=path)


# ==========================================================================
# YamlGenerator
# ==========================================================================

def _expand_targets(campaign: Campaign):
    ligand_by_id = {l.id: l for l in campaign.ligands}
    targets = []
    for fam in campaign.families:
        ligand_ids = fam.ligands if fam.ligands else [l.id for l in campaign.ligands]
        for lig_id in ligand_ids:
            if lig_id not in ligand_by_id:
                raise MDParseError(f"protein '{fam.id}' references unknown ligand '{lig_id}'")
            targets.append((fam, ligand_by_id[lig_id]))
    return targets


# Homo-oligomer copies: `id: [A, B]` on a *partner* shares one sequence across
# multiple chain ids -- real YAML already parses this straight into a Python
# list, so `Partner.id` is just used as-is (str or list). Only partners support
# this: the primary family id also names the output file
# (`{family_id}_{ligand_id}.yaml`), so it must stay a plain single token.


def _chain_entry(chain_id, sequence: str, entity_type: str = "protein",
                  modifications=None, cyclic: bool = False, msa=None) -> dict:
    entry = {"id": chain_id, "sequence": sequence}
    if modifications:
        entry["modifications"] = [{"ccd": m[0], "position": m[1]} for m in modifications]
    if cyclic:
        entry["cyclic"] = True
    if msa:
        entry["msa"] = msa
    return {entity_type: entry}


def _ligand_entry(lig: Ligand) -> dict:
    key, value = ("smiles", lig.smiles) if lig.smiles is not None else ("ccd", lig.ccd)
    return {"ligand": {key: value, "id": lig.id}}


def _build_yaml_doc(fam: ProteinFamily, lig: Ligand, campaign: Campaign) -> dict:
    sequences = [_chain_entry(fam.id, fam.sequence, "protein", fam.modifications, fam.cyclic, fam.msa)]
    for pid in fam.partners:
        p = campaign.partners[pid]
        sequences.append(_chain_entry(p.id, p.sequence, p.type, p.modifications, p.cyclic, p.msa))
    sequences.append(_ligand_entry(lig))
    doc = {"sequences": sequences}

    constraints = []
    if fam.pocket_contacts:
        # Boltz's pocket constraint requires every contact entry to be an explicit
        # [chain, residue_or_atom] pair (verified against the installed boltz 2.2.1
        # schema parser) -- there is no whole-chain-only shorthand, so a family with
        # no pocket_contacts gets no pocket constraint at all (unconstrained folding).
        constraints.append({"pocket": {"binder": lig.id, "contacts": fam.pocket_contacts}})
    for atom1, atom2 in (fam.bond_constraints or []):
        constraints.append({"bond": {"atom1": atom1, "atom2": atom2}})
    for entry in (fam.contact_constraints or []):
        token1, token2 = entry[0], entry[1]
        contact = {"token1": token1, "token2": token2}
        if len(entry) > 2:
            contact["max_distance"] = entry[2]
        constraints.append({"contact": contact})
    if constraints:
        doc["constraints"] = constraints

    if fam.templates:
        doc["templates"] = [
            {("pdb" if str(path).lower().endswith(".pdb") else "cif"): path} for path in fam.templates
        ]

    if campaign.settings.predict_affinity:
        doc["properties"] = [{"affinity": {"binder": lig.id}}]
    return doc


def generate_yamls(campaign: Campaign, output_dir: Path) -> list:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest, seen = [], set()
    for fam, lig in _expand_targets(campaign):
        stem = f"{fam.id}_{lig.id}"
        if stem in seen:
            raise MDParseError(f"duplicate target filename '{stem}.yaml' -- check for duplicate family/ligand ids")
        seen.add(stem)
        doc = _build_yaml_doc(fam, lig, campaign)
        with (output_dir / f"{stem}.yaml").open("w") as f:
            yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False)
        manifest.append(Target(stem=stem, family_id=fam.id, ligand_id=lig.id, pocket_contacts_used=fam.pocket_contacts))
    with (output_dir / MANIFEST_FILENAME).open("w") as f:
        json.dump([asdict(t) for t in manifest], f, indent=2)
    return manifest


def load_manifest(output_dir: Path) -> list:
    manifest_path = output_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        print(f"BoltzMaker: no manifest at {manifest_path} -- run `generate` first.")
        sys.exit(1)
    with manifest_path.open() as f:
        return [Target(**d) for d in json.load(f)]


# ==========================================================================
# Preflight
# ==========================================================================

@dataclass
class CheckResult:
    name: str
    status: str  # PASS / WARN / FAIL
    message: str


def check_boltz_cli() -> CheckResult:
    boltz_path = _venv_bin("boltz")
    if not boltz_path.exists():
        return CheckResult("boltz_cli", "FAIL", f"{boltz_path} not found -- run `setup`")
    try:
        out = subprocess.run([str(boltz_path), "--help"], capture_output=True, text=True, timeout=20)
        ok = out.returncode == 0
        return CheckResult("boltz_cli", "PASS" if ok else "WARN",
                            f"{boltz_path} {'reachable' if ok else f'exited {out.returncode} on --help'}")
    except Exception as e:
        return CheckResult("boltz_cli", "FAIL", f"error invoking {boltz_path}: {e}")


def check_gpu() -> CheckResult:
    try:
        import torch
        if torch.backends.mps.is_available():
            return CheckResult("gpu", "PASS", "Apple MPS backend available")
        if torch.cuda.is_available():
            return CheckResult("gpu", "PASS", "CUDA backend available")
        return CheckResult("gpu", "WARN", "no GPU/MPS backend detected -- boltz will run on CPU (slow)")
    except ImportError:
        return CheckResult("gpu", "FAIL", "torch not importable -- run `setup`")


def check_disk_space(out_dir: Path, n_targets: int) -> CheckResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(out_dir)
    threshold = max(10 * 1024**3, n_targets * 200 * 1024**2)
    free_gb, need_gb = usage.free / 1e9, threshold / 1e9
    if usage.free < threshold:
        return CheckResult("disk_space", "FAIL", f"only {free_gb:.1f} GB free at {out_dir}, need ~{need_gb:.1f} GB")
    return CheckResult("disk_space", "PASS", f"{free_gb:.1f} GB free at {out_dir}")


def _is_dataless(path: Path) -> bool:
    st = path.stat()
    blocks = getattr(st, "st_blocks", None)
    return blocks is not None and st.st_size > 0 and blocks == 0


def ensure_materialized(path: Path, timeout: float = 30.0) -> CheckResult:
    # macOS "Optimize Mac Storage" can evict iCloud-synced files to dataless
    # placeholders (non-zero logical size, zero blocks on disk).
    if not path.exists():
        return CheckResult(f"materialize:{path.name}", "FAIL", f"{path} does not exist")
    if not _is_dataless(path):
        return CheckResult(f"materialize:{path.name}", "PASS", f"{path.name} is local")
    subprocess.run(["brctl", "download", str(path)], capture_output=True)
    start = time.time()
    while time.time() - start < timeout:
        if not _is_dataless(path):
            return CheckResult(f"materialize:{path.name}", "PASS", f"{path.name} materialized via brctl")
        time.sleep(1)
    return CheckResult(f"materialize:{path.name}", "FAIL",
                        f"{path.name} still dataless/evicted after {timeout:.0f}s (iCloud eviction?)")


def check_all_materialized(paths: list) -> CheckResult:
    failed, recovered = [], 0
    for p in paths:
        r = ensure_materialized(p)
        if r.status == "FAIL":
            failed.append(p.name)
        elif "materialized via brctl" in r.message:
            recovered += 1
    if failed:
        shown = failed[:5]
        return CheckResult("icloud_materialize", "FAIL",
                            f"{len(failed)} file(s) still dataless/evicted: {shown}{'...' if len(failed) > 5 else ''}")
    msg = f"{len(paths)} file(s) local"
    if recovered:
        msg += f" ({recovered} recovered from iCloud eviction via brctl)"
    return CheckResult("icloud_materialize", "PASS", msg)


def check_yaml_validity(manifest: list, output_dir: Path, campaign: Campaign) -> CheckResult:
    bad = []
    for t in manifest:
        path = output_dir / f"{t.stem}.yaml"
        try:
            with path.open() as f:
                doc = yaml.safe_load(f)
        except Exception as e:
            bad.append(f"{path.name}: parse error ({e})")
            continue
        if not doc.get("sequences"):
            bad.append(f"{path.name}: missing/empty 'sequences'")
            continue
        binder_ids = {e["ligand"]["id"] for e in doc["sequences"] if "ligand" in e}
        for c in doc.get("constraints", []):
            if "pocket" not in c:
                continue  # bond/contact constraints reference chains/atoms directly, not a ligand "binder"
            binder = c["pocket"].get("binder")
            if binder not in binder_ids:
                bad.append(f"{path.name}: pocket constraint binder '{binder}' not among ligand ids")
        if campaign.settings.predict_affinity:
            aff_binders = {p["affinity"]["binder"] for p in doc.get("properties", []) if "affinity" in p}
            if not aff_binders & binder_ids:
                bad.append(f"{path.name}: predict_affinity is on but no matching affinity property found")
    if bad:
        return CheckResult("yaml_validity", "FAIL", f"{len(bad)} problem(s): {bad[:5]}")
    return CheckResult("yaml_validity", "PASS", f"{len(manifest)} yaml file(s) valid")


def check_smiles(campaign: Campaign) -> CheckResult:
    # ccd-code ligands aren't SMILES and are validated by Boltz itself at runtime.
    from rdkit import Chem
    smiles_ligands = [lig for lig in campaign.ligands if lig.smiles is not None]
    bad, oversized, warn = [], [], []
    for lig in smiles_ligands:
        mol = Chem.MolFromSmiles(lig.smiles)
        if mol is None:
            bad.append(lig.id)
            continue
        if campaign.settings.predict_affinity:
            n_atoms = mol.GetNumAtoms()
            if n_atoms > 128:
                oversized.append(f"{lig.id} ({n_atoms} atoms)")
            elif n_atoms > 56:
                warn.append(f"{lig.id} ({n_atoms} atoms)")
    if bad:
        return CheckResult("smiles_validity", "FAIL", f"invalid SMILES for: {bad}")
    if oversized:
        return CheckResult("smiles_validity", "FAIL",
                            f"exceeds Boltz's 128-heavy-atom affinity limit: {oversized}")
    if warn:
        return CheckResult("smiles_validity", "WARN",
                            f"{len(smiles_ligands)} SMILES parse OK; {warn} exceed Boltz's 56-atom "
                            "affinity 'trained size' threshold (still runs, may be less accurate)")
    return CheckResult("smiles_validity", "PASS", f"{len(smiles_ligands)} SMILES parse OK")


_IONIZABLE_SMARTS = {
    "carboxylic acid": "[CX3](=O)[OX2H1]",
    "primary/secondary amine": "[NX3;H2,H1;!$(NC=O);!$(N=*)]",
    "phenol": "[OX2H][cX3]",
    "sulfonic acid": "[SX4](=O)(=O)[OX2H1]",
}


def _ligand_chemistry_notes(campaign: Campaign) -> dict:
    # Bad input chemistry (an undefined stereocentre, a salt/counterion left attached, an
    # ionizable group whose intended protonation state is ambiguous) doesn't error --
    # Boltz folds whatever it's given and the pose/affinity is silently wrong. Shared by
    # preflight's check_ligand_preparation, the dashboard's "Ligand preparation" card, and
    # the ligand-grid panel's per-atom highlighting, so none of the three can drift out of
    # sync. This only advises; it never blocks -- these are legitimate modelling choices
    # the user may have already made deliberately.
    #
    # Returns {ligand_id: {"notes": [str, ...], "stereo_atoms": [int, ...],
    #                      "ionizable_atoms": {group_name: [int, ...]}, "has_fragments": bool}}
    # -- only for ligands with at least one finding.
    from rdkit import Chem

    patterns = {name: Chem.MolFromSmarts(smarts) for name, smarts in _IONIZABLE_SMARTS.items()}

    notes_by_ligand = {}
    for lig in campaign.ligands:
        if lig.smiles is None:
            continue  # CCD ligands are pre-defined dictionary entries, not raw SMILES
        mol = Chem.MolFromSmiles(lig.smiles)
        if mol is None:
            continue  # already reported as a FAIL by check_smiles

        notes = []
        has_fragments = len(Chem.GetMolFrags(mol)) > 1
        if has_fragments:
            notes.append("multiple disconnected fragments (salt/counterion?)")

        centres = Chem.FindMolChiralCenters(mol, includeUnassigned=True, useLegacyImplementation=False)
        stereo_atoms = [idx for idx, chirality in centres if chirality == "?"]
        if stereo_atoms:
            notes.append(f"undefined stereocentre(s) at atom index {', '.join(str(i) for i in stereo_atoms)}")

        ionizable_atoms = {}
        for name, patt in patterns.items():
            if patt is None:
                continue
            matches = mol.GetSubstructMatches(patt)
            if matches:
                ionizable_atoms[name] = sorted({idx for match in matches for idx in match})
        if ionizable_atoms:
            notes.append(f"ionizable group(s) present ({', '.join(ionizable_atoms)}) -- verify the SMILES "
                          "reflects your intended protonation state")

        if notes:
            notes_by_ligand[lig.id] = {"notes": notes, "stereo_atoms": stereo_atoms,
                                        "ionizable_atoms": ionizable_atoms, "has_fragments": has_fragments}
    return notes_by_ligand


def check_ligand_preparation(campaign: Campaign) -> CheckResult:
    notes_by_ligand = _ligand_chemistry_notes(campaign)
    if notes_by_ligand:
        issues = [f"{lig_id}: {'; '.join(info['notes'])}" for lig_id, info in notes_by_ligand.items()]
        shown = issues[:5]
        more = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        return CheckResult("ligand_preparation", "WARN",
                            f"{len(issues)} ligand(s) may need chemistry review: {shown}{more}")
    return CheckResult("ligand_preparation", "PASS", "no stereo/protonation/fragment concerns detected")


def check_hidden_files(input_dir: Path, dry_run: bool = False) -> CheckResult:
    # exclude BoltzMaker's own manifest -- it's bookkeeping, not Finder/OS cruft.
    hidden = [p for p in input_dir.glob(".*") if p.is_file() and p.name != MANIFEST_FILENAME]
    if not hidden:
        return CheckResult("hidden_files", "PASS", "no hidden files in input dir")
    if dry_run:
        return CheckResult("hidden_files", "WARN", f"{len(hidden)} hidden file(s) would be removed: {[p.name for p in hidden]}")
    for p in hidden:
        p.unlink()
    return CheckResult("hidden_files", "PASS", f"removed {len(hidden)} hidden file(s)")


def check_chain_id_length(campaign: Campaign) -> CheckResult:
    # Boltz stores chain names in a fixed 5-character numpy field (`Chain` dtype in its
    # own source, data/types.py) -- longer ids are silently truncated on write, then
    # crash later with a confusing KeyError deep inside Boltz's schema parser (this was
    # discovered via an actual failed run, not from reading docs).
    offenders = set()
    for fam in campaign.families:
        if len(fam.id) > 5:
            offenders.add(f"protein '{fam.id}' ({len(fam.id)} chars)")
        for pid in fam.partners:
            raw_id = campaign.partners[pid].id
            for cid in (raw_id if isinstance(raw_id, list) else [raw_id]):
                if len(str(cid)) > 5:
                    offenders.add(f"partner '{pid}' chain id '{cid}' ({len(str(cid))} chars)")
    for lig in campaign.ligands:
        if len(lig.id) > 5:
            offenders.add(f"ligand '{lig.id}' ({len(lig.id)} chars)")
    if offenders:
        return CheckResult("chain_id_length", "FAIL",
                            f"chain id(s) exceed Boltz's 5-character limit: {sorted(offenders)}")
    return CheckResult("chain_id_length", "PASS", "all chain ids <= 5 characters")


def check_duplicate_targets(manifest: list) -> CheckResult:
    stems = [t.stem for t in manifest]
    dupes = {s for s in stems if stems.count(s) > 1}
    if dupes:
        return CheckResult("duplicate_targets", "FAIL", f"duplicate target stem(s): {dupes}")
    return CheckResult("duplicate_targets", "PASS", f"{len(stems)} unique target(s)")


def check_memory_heuristic(campaign: Campaign, manifest: list, threshold: int) -> CheckResult:
    # Rough empirical heuristic, not a precise memory model: a ~1250-token 4-chain
    # complex (GPCR + 3 G-protein subunits) used ~65GB RAM on a 64GB M1 Max in testing
    # and swap-thrashed for 20+ minutes with zero progress before being killed.
    from rdkit import Chem
    fam_by_id = {f.id: f for f in campaign.families}
    lig_by_id = {l.id: l for l in campaign.ligands}
    atom_cache = {}

    def ligand_atoms(lig: Ligand) -> int:
        if lig.id not in atom_cache:
            mol = Chem.MolFromSmiles(lig.smiles) if lig.smiles is not None else None
            atom_cache[lig.id] = mol.GetNumAtoms() if mol else 0
        return atom_cache[lig.id]

    offenders = []
    for t in manifest:
        fam, lig = fam_by_id.get(t.family_id), lig_by_id.get(t.ligand_id)
        if fam is None or lig is None:
            continue
        total = len(fam.sequence) + sum(len(campaign.partners[pid].sequence) for pid in fam.partners)
        total += ligand_atoms(lig)
        if total > threshold:
            offenders.append(f"{t.stem} (~{total} tokens)")
    if offenders:
        shown = offenders[:5]
        return CheckResult(
            "memory_heuristic", "WARN",
            f"{len(offenders)} target(s) exceed ~{threshold} tokens: {shown}{'...' if len(offenders) > 5 else ''} "
            "-- consider --workers 1 --max-parallel-samples 1 and/or a lower --mps-watermark",
        )
    return CheckResult("memory_heuristic", "PASS", f"all targets under ~{threshold} tokens (empirical heuristic)")


def check_plip_env() -> CheckResult:
    # Purely informational -- cif2plip interaction analysis is optional and additive,
    # so this must never WARN/FAIL (which --strict would otherwise promote to blocking
    # an ordinary run over a feature that isn't required).
    if _plip_available():
        return CheckResult("plip_env", "PASS", "cif2plip environment found -- interaction analysis will run")
    return CheckResult("plip_env", "PASS", "cif2plip environment not found -- interaction analysis will be "
                        "skipped (optional; run `setup-plip` to enable)")


def run_preflight(manifest: list, output_dir: Path, campaign: Campaign, md_path: Path, strict: bool = False,
                   memory_warn_tokens: int = 1000) -> bool:
    results = [
        check_boltz_cli(),
        check_gpu(),
        check_disk_space(output_dir, len(manifest)),
        check_all_materialized([md_path] + [output_dir / f"{t.stem}.yaml" for t in manifest]),
        check_yaml_validity(manifest, output_dir, campaign),
        check_smiles(campaign),
        check_ligand_preparation(campaign),
        check_chain_id_length(campaign),
        check_memory_heuristic(campaign, manifest, memory_warn_tokens),
        check_hidden_files(output_dir),
        check_duplicate_targets(manifest),
        check_plip_env(),
    ]
    table = Table(title="BoltzMaker preflight")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    style = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    worst = "PASS"
    for r in results:
        table.add_row(r.name, f"[{style[r.status]}]{r.status}[/{style[r.status]}]", r.message)
        if r.status == "FAIL" or (strict and r.status == "WARN"):
            worst = "FAIL"
        elif r.status == "WARN" and worst != "FAIL":
            worst = "WARN"
    Console().print(table)
    return worst != "FAIL"


# ==========================================================================
# Runner -- resume via staged symlinks, progress via filesystem polling
# ==========================================================================

def _predictions_dir_for(out_dir: Path, staging_name: str) -> Path:
    return out_dir / f"boltz_results_{staging_name}" / "predictions"


def _target_complete(pred_dir: Path, stem: str, need_affinity: bool) -> bool:
    d = pred_dir / stem
    if not d.is_dir():
        return False
    if not any(d.glob(f"{stem}_model_0.cif")):
        return False
    if not any(d.glob(f"confidence_{stem}_model_0.json")):
        return False
    if need_affinity and not any(d.glob(f"affinity_{stem}.json")):
        return False
    return True


def _partition_targets(manifest: list, pred_dir: Path, need_affinity: bool):
    complete, pending = [], []
    for t in manifest:
        (complete if pred_dir and _target_complete(pred_dir, t.stem, need_affinity) else pending).append(t)
    return complete, pending


def _stage_targets(yaml_dir: Path, targets: list, stage_dir: Path) -> None:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    for t in targets:
        src = (yaml_dir / f"{t.stem}.yaml").resolve()
        (stage_dir / f"{t.stem}.yaml").symlink_to(src)


def resolve_accelerator(choice: str) -> str:
    if choice != "auto":
        return choice
    try:
        import torch
        if torch.backends.mps.is_available() or torch.cuda.is_available():
            return "gpu"
    except ImportError:
        pass
    return "cpu"


# Phase-transition markers Boltz actually prints (verified against installed boltz 2.2.1
# source -- there is no diffusion/recycling step-level signal anywhere in its output, so
# this is the finest *honest* granularity available: which phase, and that phase's own
# per-target count/rate from Lightning's own reporting).
_PHASE_PATTERNS = [
    (re.compile(r"Calling MSA server for target (\S+)"), "MSA"),
    (re.compile(r"Running structure prediction for (\d+) input"), "structure prediction"),
    (re.compile(r"Running affinity prediction for (\d+) input"), "affinity prediction"),
]
_DATALOADER_RE = re.compile(r"Predicting DataLoader 0:\s*\d+%\|.*?\|\s*(\d+)/(\d+)\s*\[([^\]]*)\]")

MEMORY_THRASH_FRACTION = 0.90  # fraction of total system RAM considered "at risk of thrashing"
MEMORY_THRASH_SECONDS = 60  # how long sustained high memory must persist before warning


def run_boltz(yaml_dir: Path, out_dir: Path, manifest: list, workers: int, accelerator: str,
              need_affinity: bool, campaign_dir: Path, limit: int = None,
              mps_watermark: float = 1.0, max_parallel_samples: int = 1,
              recycling_steps: int = None, sampling_steps: int = None,
              diffusion_samples_affinity: int = None, sampling_steps_affinity: int = None,
              max_msa_seqs: int = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = yaml_dir / "_stage_run"
    pred_dir = _predictions_dir_for(out_dir, stage_dir.name)

    complete, pending = _partition_targets(manifest, pred_dir, need_affinity)
    if limit is not None:
        pending = pending[:limit]
    if not pending:
        print(f"BoltzMaker: {len(complete)}/{len(manifest)} target(s) already complete, nothing to run.")
        return

    _stage_targets(yaml_dir, pending, stage_dir)
    check_hidden_files(stage_dir)

    boltz_bin = _venv_bin("boltz")
    cmd = [
        str(boltz_bin), "predict", str(stage_dir),
        "--use_potentials", "--diffusion_samples", "1", "--use_msa_server",
        "--num_workers", str(workers), "--accelerator", accelerator,
        "--out_dir", str(out_dir),
    ]
    optional_flags = {
        "--max_parallel_samples": max_parallel_samples,
        "--recycling_steps": recycling_steps,
        "--sampling_steps": sampling_steps,
        "--diffusion_samples_affinity": diffusion_samples_affinity,
        "--sampling_steps_affinity": sampling_steps_affinity,
        "--max_msa_seqs": max_msa_seqs,
    }
    for flag, val in optional_flags.items():
        if val is not None:
            cmd += [flag, str(val)]

    env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="1")
    if mps_watermark is not None:
        # Caps MPS allocation at `mps_watermark` x the device's recommended max working
        # set -- an oversized complex then raises a clean MPS OOM error instead of
        # silently spilling into swap (this is what actually happened in testing: a
        # ~1250-token complex used ~65GB RAM on a 64GB Mac and thrashed for 20+ minutes).
        # torch's MPS allocator requires low_watermark <= high_watermark and otherwise
        # raises immediately (its own unset default low watermark is ~1.4, which is
        # *above* our default high of 1.0 -- discovered by an actual failed run, not
        # anticipated from docs alone) -- so the low watermark must always be pinned
        # to something <= mps_watermark whenever we override the high one.
        env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = str(mps_watermark)
        env["PYTORCH_MPS_LOW_WATERMARK_RATIO"] = "0.0"

    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = campaign_dir / f"boltz_run_{ts}.log"
    log_f = log_path.open("w")
    log_f.write(f"=== Started at {time.strftime('%a %b %d %H:%M:%S %Y')} ===\n")
    log_f.write(f"=== Command: {' '.join(cmd)} ===\n")
    log_f.write(f"=== PYTORCH_MPS_HIGH_WATERMARK_RATIO={env.get('PYTORCH_MPS_HIGH_WATERMARK_RATIO', 'unset')} "
                f"PYTORCH_MPS_LOW_WATERMARK_RATIO={env.get('PYTORCH_MPS_LOW_WATERMARK_RATIO', 'unset')} ===\n")
    log_f.flush()

    print(f"BoltzMaker: {len(complete)}/{len(manifest)} already complete; running {len(pending)} target(s).")
    print(f"BoltzMaker: log -> {log_path}")

    run_start = time.time()
    proc = subprocess.Popen(cmd, cwd=str(yaml_dir), env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
    latest_line = {"text": ""}
    phase = {"name": "starting", "done": 0, "total": 0, "rate": ""}

    def _reader():
        for line in proc.stdout:
            log_f.write(line)
            log_f.flush()
            latest_line["text"] = line.rstrip()
            for pattern, name in _PHASE_PATTERNS:
                if pattern.search(line):
                    phase.update(name=name, done=0, total=0, rate="")
            m = _DATALOADER_RE.search(line)
            if m:
                phase["done"], phase["total"], phase["rate"] = int(m.group(1)), int(m.group(2)), m.group(3)

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    # Live memory monitor: sums RSS across the whole boltz process tree (--num_workers
    # forks matter here) so the progress bar can show real usage, and so a repeat of the
    # thrashing incident gets a loud warning instead of Marc staring at a silent hang.
    total_ram_gb = psutil.virtual_memory().total / 1e9
    mem_state = {"rss_gb": 0.0, "high_since": None}
    stop_monitor = threading.Event()

    def _memory_monitor():
        while not stop_monitor.is_set():
            try:
                p = psutil.Process(proc.pid)
                rss = p.memory_info().rss
                for child in p.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                mem_state["rss_gb"] = rss / 1e9
                if rss > MEMORY_THRASH_FRACTION * psutil.virtual_memory().total:
                    if mem_state["high_since"] is None:
                        mem_state["high_since"] = time.time()
                    elif time.time() - mem_state["high_since"] > MEMORY_THRASH_SECONDS:
                        log_f.write(
                            "=== WARNING: memory usage has been above "
                            f"{MEMORY_THRASH_FRACTION:.0%} of system RAM for "
                            f"{MEMORY_THRASH_SECONDS}+s -- likely swap-thrashing, not "
                            "genuine progress. Consider Ctrl-C and re-running with a "
                            "lower --max-parallel-samples/--workers or --mps-watermark. ===\n"
                        )
                        log_f.flush()
                        mem_state["high_since"] = time.time()  # re-arm, don't spam every tick
                else:
                    mem_state["high_since"] = None
            except psutil.NoSuchProcess:
                pass
            stop_monitor.wait(2)

    mem_thread = threading.Thread(target=_memory_monitor, daemon=True)
    mem_thread.start()

    total = len(pending)
    try:
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(),
            TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), TimeRemainingColumn(),
            TextColumn("mem: {task.fields[mem]}"),
        ) as progress:
            outer = progress.add_task("targets", total=total, mem="")
            inner = progress.add_task("phase: starting", total=1, mem="")
            while proc.poll() is None:
                done = sum(1 for t in pending if _target_complete(pred_dir, t.stem, need_affinity))
                mem_str = f"{mem_state['rss_gb']:.1f}/{total_ram_gb:.0f}GB"
                progress.update(outer, completed=done, mem=mem_str)
                rate_suffix = f" [{phase['rate']}]" if phase["rate"] else ""
                progress.update(
                    inner, completed=phase["done"], total=max(phase["total"], 1),
                    description=f"phase: {phase['name']}{rate_suffix}", mem="",
                )
                time.sleep(1)
            reader_thread.join(timeout=5)
            done = sum(1 for t in pending if _target_complete(pred_dir, t.stem, need_affinity))
            progress.update(outer, completed=done, mem=f"{mem_state['rss_gb']:.1f}/{total_ram_gb:.0f}GB")
    except KeyboardInterrupt:
        print("\nBoltzMaker: interrupted -- terminating boltz predict...")
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            print("BoltzMaker: boltz predict did not exit within 15s -- sending SIGKILL.")
            proc.kill()
            proc.wait(timeout=30)
        raise
    finally:
        stop_monitor.set()
        run_end = time.time()
        elapsed = time.strftime('%a %b %d %H:%M:%S %Y')
        log_f.write(f"=== Finished at {elapsed} ===\n")
        log_f.close()

        # Recorded even on interrupt (partial progress is still worth knowing) -- read
        # back by write_html() to show run parameters/runtime in the summary table.
        completed_count = sum(1 for t in pending if _target_complete(pred_dir, t.stem, need_affinity))
        record = {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(run_start)),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(run_end)),
            "duration_seconds": round(run_end - run_start, 1),
            "workers": workers, "accelerator": accelerator, "mps_watermark": mps_watermark,
            "max_parallel_samples": max_parallel_samples, "recycling_steps": recycling_steps,
            "sampling_steps": sampling_steps, "diffusion_samples_affinity": diffusion_samples_affinity,
            "sampling_steps_affinity": sampling_steps_affinity, "max_msa_seqs": max_msa_seqs,
            "targets_submitted": len(pending), "targets_completed": completed_count,
            "exit_code": proc.returncode,
        }
        with (campaign_dir / RUN_HISTORY_FILENAME).open("a") as hf:
            hf.write(json.dumps(record) + "\n")

    still_missing = [t.stem for t in pending if not _target_complete(pred_dir, t.stem, need_affinity)]
    print(f"BoltzMaker: boltz predict exited with code {proc.returncode}")
    if still_missing:
        print(f"WARNING: {len(still_missing)} target(s) did not complete: {still_missing}")
    else:
        print(f"BoltzMaker: all {total} submitted target(s) completed successfully.")


# ==========================================================================
# Analyzer -- generic JSON flattening so the schema can evolve between
# Boltz versions without breaking the tool.
# ==========================================================================

def _flatten_json(prefix: str, obj, out: dict) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_json(f"{prefix}_{k}" if prefix else k, v, out)
    elif isinstance(obj, list):
        if not obj:
            return
        if all(isinstance(x, (int, float)) for x in obj):
            out[f"{prefix}_mean"] = sum(obj) / len(obj)
            out[f"{prefix}_min"] = min(obj)
            out[f"{prefix}_max"] = max(obj)
        elif all(isinstance(x, list) for x in obj):
            out[f"{prefix}_skipped"] = f"<{len(obj)}x{len(obj[0]) if obj[0] else 0} matrix omitted>"
        else:
            out[prefix] = json.dumps(obj)
    else:
        out[prefix] = obj


def _load_json_flat(path: Path) -> dict:
    with path.open() as f:
        data = json.load(f)
    out = {}
    _flatten_json("", data, out)
    return out


_AFFINITY_KEY_RE = re.compile(r"^affinity_pred_value(\d*)$")


def _compute_pic50_columns(flat: dict) -> dict:
    out = {}
    for k, v in list(flat.items()):
        m = _AFFINITY_KEY_RE.match(k)
        if m and isinstance(v, (int, float)):
            suffix = m.group(1)
            out[f"pIC50{'_' + suffix if suffix else ''}"] = (6 - float(v)) * 1.364
    members = [v for k, v in out.items() if re.match(r"^pIC50_\d+$", k)]
    if len(members) >= 2:
        mean = sum(members) / len(members)
        out["pIC50_ensemble_mean"] = mean
        out["pIC50_ensemble_std"] = (sum((x - mean) ** 2 for x in members) / len(members)) ** 0.5
    return out


def find_any_predictions_dir(out_dir: Path):
    if not out_dir.exists():
        return None
    for root, dirs, _files in os.walk(out_dir):
        if "predictions" in dirs:
            return Path(root) / "predictions"
    return None


_FLAG_TEMPLATES = {
    "MISSING_OUTPUTS": "prediction did not complete -- re-run this target.",
    "LOW_CONFIDENCE": "low structural confidence.",
    "HIGH_CONFIDENCE_POOR_AFFINITY": "high structural confidence but weak predicted affinity -- verify pocket/binding mode.",
    "LOW_CONFIDENCE_STRONG_AFFINITY": "strong predicted affinity but low structural confidence -- verify pose before trusting.",
    "LOW_POCKET_PLDDT": "low pLDDT near the specified pocket (approximate, complex-level proxy).",
}

LOW_CONFIDENCE_THRESHOLD = 0.5
POCKET_PLDDT_THRESHOLD = 0.7


def _flags_to_note(flags_str: str) -> str:
    if not flags_str:
        return ""
    return " ".join(_FLAG_TEMPLATES.get(p, p) for p in flags_str.split(";") if p)


def _set_flag(df: pd.DataFrame, pos: int, flag: str) -> None:
    col = df.columns.get_loc("flags")
    existing = df.iat[pos, col]
    flags = set(existing.split(";")) if existing else set()
    flags.add(flag)
    df.iat[pos, col] = ";".join(sorted(f for f in flags if f))


def apply_confidence_flags(df: pd.DataFrame) -> pd.DataFrame:
    conf_col = "confidence_score" if "confidence_score" in df.columns else ("ptm" if "ptm" in df.columns else None)
    pic50_col = "pIC50" if "pIC50" in df.columns else None

    if conf_col:
        for pos in df.index[df[conf_col] < LOW_CONFIDENCE_THRESHOLD]:
            _set_flag(df, df.index.get_loc(pos), "LOW_CONFIDENCE")

    if conf_col and pic50_col:
        valid = df[[conf_col, pic50_col]].dropna()
        if len(valid) >= 3:
            try:
                conf_tercile = pd.qcut(df[conf_col].rank(method="first"), 3, labels=["low", "mid", "high"])
                pic50_tercile = pd.qcut(df[pic50_col].rank(method="first"), 3, labels=["low", "mid", "high"])
                for pos in range(len(df)):
                    c, p = conf_tercile.iloc[pos], pic50_tercile.iloc[pos]
                    if pd.isna(c) or pd.isna(p):
                        continue
                    if c == "high" and p == "low":
                        _set_flag(df, pos, "HIGH_CONFIDENCE_POOR_AFFINITY")
                    elif c == "low" and p == "high":
                        _set_flag(df, pos, "LOW_CONFIDENCE_STRONG_AFFINITY")
            except ValueError:
                pass  # too few distinct values to tercile-split -- skip the mismatch flags

    df["notes"] = df["flags"].apply(_flags_to_note)
    return df


def apply_pocket_plddt_flag(df: pd.DataFrame, manifest: list) -> pd.DataFrame:
    pocket_targets = {t.stem for t in manifest if t.pocket_contacts_used}
    if not pocket_targets:
        return df
    proxy_col = next((c for c in ("complex_iplddt", "complex_plddt") if c in df.columns), None)
    if proxy_col is None:
        return df
    for pos in range(len(df)):
        row = df.iloc[pos]
        if row["target_id"] in pocket_targets and pd.notna(row.get(proxy_col)) and row[proxy_col] < POCKET_PLDDT_THRESHOLD:
            _set_flag(df, pos, "LOW_POCKET_PLDDT")
    df["notes"] = df["flags"].apply(_flags_to_note)
    return df


_PLIP_STATUS_FILE = "_plip_status.json"


def _plip_dir(campaign_dir: Path) -> Path:
    return campaign_dir / "boltz_plip"


def _run_cif2plip(cif_path: Path, work_dir: Path) -> subprocess.CompletedProcess:
    # cif2plip.py shells out to the bare `pdb_tidy` command by name -- it must resolve
    # via PATH, so the plip env's own bin/ has to be on PATH, not just used by absolute
    # path for the interpreter itself.
    env = os.environ.copy()
    env["PATH"] = str(_plip_python().parent) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [str(_plip_python()), str(_plip_script()), str(cif_path), "-o", str(work_dir)],
        capture_output=True, text=True, env=env, timeout=600,
    )


def _label_plip_image(pse_path: Path, out_png: Path, residues: pd.DataFrame) -> bool:
    if not _plip_label_script().exists():
        return False
    args = [f"{r.prot_chain}:{int(r.prot_resnr)}:{r.prot_restype}"
            for r in residues.drop_duplicates().itertuples()]
    if not args:
        return False
    env = os.environ.copy()
    # A user's own ~/.pymolrc.py (e.g. a plugin unrelated to BoltzMaker) can reference
    # modules that don't exist in .plip_env and error out during startup -- override HOME
    # so PyMOL can't find one, regardless of what's on any given machine.
    env["HOME"] = str(PLIP_VENV_DIR)
    proc = subprocess.run(
        [str(_plip_python()), str(_plip_label_script()), str(pse_path), str(out_png)] + args,
        capture_output=True, text=True, env=env, timeout=120,
    )
    return proc.returncode == 0 and out_png.exists()


def _analyze_target_interactions(t: Target, cif_path: Path, campaign: Campaign, campaign_dir: Path, i: int, n: int) -> dict:
    """Runs (or reuses a cached run of) cif2plip for one target. Returns a dict with
    plip_status, per-interaction-type counts, ligand InChIKey, long-format contact rows
    (target_id already attached), and relative paths to the PNG/pse if produced."""
    empty = {"plip_status": "failed", "counts": {}, "inchikey": None, "contacts": [], "png": None, "pse": None}
    final_dir = _plip_dir(campaign_dir) / t.stem
    status_file = final_dir / _PLIP_STATUS_FILE

    if final_dir.exists() and status_file.exists():
        status = json.loads(status_file.read_text())
        contacts = []
        inter_csv = final_dir / f"{cif_path.stem}_interactions.csv"
        chosen = status.get("chosen_ligand_key")
        if inter_csv.exists() and chosen:
            idf = pd.read_csv(inter_csv)
            contacts = idf[idf["ligand"] == chosen].to_dict("records")
            for c in contacts:
                c["target_id"] = t.stem
        return {"plip_status": status["plip_status"], "counts": status.get("counts", {}),
                "inchikey": status.get("inchikey"), "contacts": contacts,
                "png": status.get("png"), "pse": status.get("pse")}

    print(f"BoltzMaker: interaction profiling {i}/{n} ({t.stem})...")
    stage_dir = campaign_dir / f".boltz_plip_staging_{t.stem}"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    try:
        proc = _run_cif2plip(cif_path, stage_dir)
    except subprocess.TimeoutExpired:
        shutil.rmtree(stage_dir, ignore_errors=True)
        return empty

    inter_csv = stage_dir / f"{cif_path.stem}_interactions.csv"
    summ_csv = stage_dir / f"{cif_path.stem}_ligand_summary.csv"
    if proc.returncode != 0 or not inter_csv.exists() or not summ_csv.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
        return empty

    inter_df = pd.read_csv(inter_csv)
    summ_df = pd.read_csv(summ_csv)

    lig = next((l for l in campaign.ligands if l.id == t.ligand_id), None)
    chosen = None
    if lig is not None and lig.smiles:
        # InChIKey first: cif2plip's own SMILES is re-derived from the 3D structure via
        # PLIP/OpenBabel, whose canonicalization scheme differs from RDKit's, so an exact
        # string match against our (RDKit-canonical) SMILES can miss even the correct
        # ligand. InChIKey is algorithm-independent -- both tools implement the same IUPAC
        # standard -- so it survives that mismatch; the SMILES check below is just a
        # fallback in case InChIKey generation fails on either side.
        lig_inchikey = _smiles_to_inchikey(lig.smiles)
        if lig_inchikey and "inchikey" in summ_df.columns:
            matches = summ_df[summ_df["inchikey"] == lig_inchikey]
            if len(matches) == 1:
                chosen = matches.iloc[0]["ligand"]
        if chosen is None and "smiles" in summ_df.columns:
            matches = summ_df[summ_df["smiles"] == lig.smiles]
            if len(matches) == 1:
                chosen = matches.iloc[0]["ligand"]
    if chosen is None and len(summ_df) == 1:
        chosen = summ_df.iloc[0]["ligand"]

    if chosen is None:
        status_str, counts, inchikey, contacts = "ambiguous_ligand", {}, None, []
        print(f"BoltzMaker: WARNING: {t.stem} -- couldn't unambiguously match the campaign "
              f"ligand against cif2plip's detected ligands, skipping interaction analysis")
    else:
        sub = inter_df[inter_df["ligand"] == chosen]
        contacts = sub.to_dict("records")
        for c in contacts:
            c["target_id"] = t.stem
        counts = sub["interaction_type"].value_counts().to_dict()
        srow = summ_df[summ_df["ligand"] == chosen]
        inchikey = srow.iloc[0]["inchikey"] if not srow.empty and "inchikey" in srow.columns else None
        status_str = "ok" if len(sub) > 0 else "no_interactions"

    plip_subdir = stage_dir / f"{cif_path.stem}_plip"
    pngs = sorted(plip_subdir.glob("*.png")) if plip_subdir.is_dir() else []
    pses = sorted(plip_subdir.glob("*.pse")) if plip_subdir.is_dir() else []

    labeled_name = None
    if pses and status_str == "ok":
        labeled_path = plip_subdir / f"{pses[0].stem}_labeled.png"
        if _label_plip_image(pses[0], labeled_path, sub[["prot_chain", "prot_resnr", "prot_restype"]]):
            labeled_name = labeled_path.name

    png_rel = f"boltz_plip/{t.stem}/{cif_path.stem}_plip/{labeled_name or (pngs[0].name if pngs else '')}" \
        if (labeled_name or pngs) else None
    pse_rel = f"boltz_plip/{t.stem}/{cif_path.stem}_plip/{pses[0].name}" if pses else None

    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if final_dir.exists():
        shutil.rmtree(final_dir)
    shutil.move(str(stage_dir), str(final_dir))
    (final_dir / _PLIP_STATUS_FILE).write_text(json.dumps({
        "plip_status": status_str, "counts": counts, "inchikey": inchikey,
        "chosen_ligand_key": chosen, "png": png_rel, "pse": pse_rel,
    }))
    return {"plip_status": status_str, "counts": counts, "inchikey": inchikey,
            "contacts": contacts, "png": png_rel, "pse": pse_rel}


def analyze(yaml_dir: Path, out_dir: Path, campaign_dir: Path, need_affinity: bool,
            campaign: Campaign, skip_interactions: bool = False) -> pd.DataFrame:
    manifest = load_manifest(yaml_dir)
    pred_dir = find_any_predictions_dir(out_dir)
    cif_dst = campaign_dir / "boltz_cif"
    cif_dst.mkdir(exist_ok=True)

    run_plip = _plip_available() and not skip_interactions
    all_contacts = []
    plip_targets_done = 0
    plip_targets_total = sum(1 for t in manifest if pred_dir and (pred_dir / t.stem).is_dir()) if run_plip else 0

    ligand_by_id = {l.id: l for l in campaign.ligands}

    rows = []
    for t in manifest:
        lig = ligand_by_id.get(t.ligand_id)
        ligand_smiles = (lig.smiles or lig.ccd) if lig else None
        row = {"target_id": t.stem, "family_id": t.family_id, "ligand_id": t.ligand_id,
               "ligand_smiles": ligand_smiles, "flags": ""}
        d = pred_dir / t.stem if pred_dir else None
        if not d or not d.is_dir():
            row["flags"] = "MISSING_OUTPUTS"
            rows.append(row)
            continue

        conf_files = sorted(d.glob(f"confidence_{t.stem}_model_0.json"))
        aff_files = sorted(d.glob(f"affinity_{t.stem}.json"))
        cif_files = sorted(d.glob(f"{t.stem}_model_0.cif"))

        if conf_files:
            row.update(_load_json_flat(conf_files[0]))
        if aff_files:
            aff_flat = _load_json_flat(aff_files[0])
            row.update(aff_flat)
            row.update(_compute_pic50_columns(aff_flat))
        if cif_files:
            shutil.copy2(cif_files[0], cif_dst / cif_files[0].name)
            row["cif_file"] = cif_files[0].name

            if run_plip:
                plip_targets_done += 1
                result = _analyze_target_interactions(t, cif_dst / cif_files[0].name, campaign, campaign_dir,
                                                       plip_targets_done, plip_targets_total)
                row["plip_status"] = result["plip_status"]
                row["plip_png_path"] = result["png"]
                row["plip_pse_path"] = result["pse"]
                for itype, n in result["counts"].items():
                    row[f"plip_{itype.replace(' ', '_')}_count"] = n
                all_contacts.extend(result["contacts"])
        elif not skip_interactions:
            row["plip_status"] = "skipped_no_env"

        if not conf_files or not cif_files or (need_affinity and not aff_files):
            row["flags"] = "MISSING_OUTPUTS"
        rows.append(row)

    df = pd.DataFrame(rows)
    if any(c.startswith("plip_") and c.endswith("_count") for c in df.columns):
        count_cols = [c for c in df.columns if c.startswith("plip_") and c.endswith("_count")]
        df[count_cols] = df[count_cols].fillna(0).astype(int)
    df = apply_confidence_flags(df)
    df = apply_pocket_plddt_flag(df, manifest)

    if all_contacts:
        pd.DataFrame(all_contacts).to_csv(campaign_dir / "boltz_interactions.csv", index=False)

    return df


# ==========================================================================
# Report writers: CSV / XLSX / self-contained HTML dashboard
# ==========================================================================

def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def write_xlsx(df: pd.DataFrame, path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="targets", index=False)
        has_pivot = "pIC50" in df.columns and df["family_id"].nunique() > 1
        pivot = df.pivot_table(index="ligand_id", columns="family_id", values="pIC50", aggfunc="mean") if has_pivot else None
        if pivot is not None:
            pivot.to_excel(writer, sheet_name="selectivity")

        wb = writer.book
        ws = wb["targets"]
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True)
        if len(df) > 0:
            ws.auto_filter.ref = ws.dimensions
            for col_name in (c for c in ("confidence_score", "ptm", "iptm", "pIC50") if c in df.columns):
                col_letter = get_column_letter(df.columns.get_loc(col_name) + 1)
                ws.conditional_formatting.add(
                    f"{col_letter}2:{col_letter}{len(df) + 1}",
                    ColorScaleRule(start_type="min", start_color="F8696B",
                                   mid_type="percentile", mid_value=50, mid_color="FFEB84",
                                   end_type="max", end_color="63BE7B"),
                )
        if pivot is not None and pivot.shape[0] and pivot.shape[1]:
            ws2 = wb["selectivity"]
            rng = f"B2:{get_column_letter(1 + pivot.shape[1])}{1 + pivot.shape[0]}"
            ws2.conditional_formatting.add(
                rng, ColorScaleRule(start_type="min", start_color="F8696B",
                                     mid_type="percentile", mid_value=50, mid_color="FFEB84",
                                     end_type="max", end_color="63BE7B"),
            )


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


_BAR_WIDTH = 0.6
_BAR_MIN_SLOTS = 5  # reserve room for at least this many category slots, so 1-2
                     # bars don't visually dominate the whole plot area

_AXIS_LABEL_FONTSIZE = 12
_TICK_FONTSIZE = 10
_LEGEND_FONTSIZE = 10
_ANNOTATION_FONTSIZE = 9


_CHART_HEIGHT_PX = 260  # matches the .md-chart-grid img sizing these replaced


def _plotly_font() -> dict:
    return dict(family="Inter, -apple-system, BlinkMacSystemFont, sans-serif", size=_TICK_FONTSIZE)


def _plotly_to_div(fig, div_id: str) -> str:
    fig.update_layout(margin=dict(l=60, r=20, t=10, b=100), height=_CHART_HEIGHT_PX,
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=_plotly_font())
    # Matplotlib draws a full rectangular border (all four spines) by default -- Plotly
    # doesn't unless told to, so mirror the axis line to the opposite side to match the
    # look of the charts these replaced.
    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=True)
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=div_id,
                        config={"responsive": True, "displaylogo": False})


def _make_bar_chart(df: pd.DataFrame, col: str, div_id: str):
    # No title set on the figure -- the HTML <h2> card header is the only title, so it
    # doesn't appear twice (once baked into the chart, once in the card).
    if col not in df.columns:
        return None
    d = df[["target_id", col]].dropna().sort_values(col, ascending=False)
    if d.empty:
        return None
    n = len(d)
    x = list(range(n))
    fig = go.Figure(go.Bar(x=x, y=d[col].tolist(), width=_BAR_WIDTH, marker_color="#4C72B0"))
    fig.update_xaxes(tickmode="array", tickvals=x, ticktext=d["target_id"].tolist(), tickangle=-75,
                      tickfont=dict(size=_TICK_FONTSIZE), range=[-0.75, max(n - 0.25, _BAR_MIN_SLOTS - 0.75)])
    fig.update_yaxes(title_text=col, title_font=dict(size=_AXIS_LABEL_FONTSIZE), tickfont=dict(size=_TICK_FONTSIZE))
    return _plotly_to_div(fig, div_id)


def _make_selectivity_heatmap(df: pd.DataFrame):
    if "pIC50" not in df.columns or df["family_id"].nunique() < 2:
        return None
    pivot = df.pivot_table(index="ligand_id", columns="family_id", values="pIC50", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(1.2 * len(pivot.columns) + 2, 0.4 * len(pivot.index) + 2))
    im = ax.imshow(pivot.values, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=45, ha="right", fontsize=_TICK_FONTSIZE)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=_TICK_FONTSIZE)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", color="white", fontsize=_ANNOTATION_FONTSIZE)
    cbar = fig.colorbar(im)
    cbar.set_label("pIC50", fontsize=_AXIS_LABEL_FONTSIZE)
    cbar.ax.tick_params(labelsize=_TICK_FONTSIZE)
    fig.tight_layout()
    return _fig_to_base64(fig)


def _make_scatter(df: pd.DataFrame, div_id: str):
    conf_col = "confidence_score" if "confidence_score" in df.columns else ("ptm" if "ptm" in df.columns else None)
    if not conf_col or "pIC50" not in df.columns:
        return None
    d = df.dropna(subset=[conf_col, "pIC50"])
    if d.empty:
        return None
    colors = d["flags"].apply(lambda f: "#d62728" if f else "#2ca02c")
    fig = go.Figure(go.Scatter(
        x=d[conf_col], y=d["pIC50"], mode="markers+text", text=d["target_id"],
        textposition="top center", textfont=dict(size=_ANNOTATION_FONTSIZE),
        marker=dict(color=colors, size=8),
    ))
    fig.update_xaxes(title_text=conf_col, title_font=dict(size=_AXIS_LABEL_FONTSIZE), tickfont=dict(size=_TICK_FONTSIZE))
    fig.update_yaxes(title_text="pIC50", title_font=dict(size=_AXIS_LABEL_FONTSIZE), tickfont=dict(size=_TICK_FONTSIZE))
    return _plotly_to_div(fig, div_id)


def _make_interaction_count_chart(df: pd.DataFrame, div_id: str):
    count_cols = [c for c in df.columns if c.startswith("plip_") and c.endswith("_count")]
    if not count_cols:
        return None
    d = df[["target_id"] + count_cols].fillna(0)
    if d[count_cols].to_numpy().sum() == 0:
        return None
    n = len(d)
    x = list(range(n))
    fig = go.Figure()
    for col in count_cols:
        label = col[len("plip_"):-len("_count")]
        fig.add_trace(go.Bar(x=x, y=d[col].tolist(), width=_BAR_WIDTH, name=label))
    fig.update_layout(barmode="stack", legend=dict(font=dict(size=_LEGEND_FONTSIZE)))
    fig.update_xaxes(tickmode="array", tickvals=x, ticktext=d["target_id"].tolist(), tickangle=-75,
                      tickfont=dict(size=_TICK_FONTSIZE), range=[-0.75, max(n - 0.25, _BAR_MIN_SLOTS - 0.75)])
    fig.update_yaxes(title_text="interactions", title_font=dict(size=_AXIS_LABEL_FONTSIZE), tickfont=dict(size=_TICK_FONTSIZE))
    return _plotly_to_div(fig, div_id)


def _make_fingerprint_heatmaps(df: pd.DataFrame, interactions_df) -> list:
    # One heatmap per protein family with interaction data, even a single ligand -- a
    # lone ligand's contacted-residue row is still useful (shows what it touches), it
    # just can't be compared/reordered against anything else. Binary ligand x
    # contacted-residue matrix; with >=3 ligands the ligand axis is reordered by
    # Jaccard-distance hierarchical clustering so ligands with a similar interaction
    # pattern group together (SAR ranking) -- guards the all-zero-row case (two ligands
    # sharing zero contacted residues -> Jaccard distance is 0/0 -> NaN).
    if interactions_df is None or interactions_df.empty:
        return []
    target_meta = df.set_index("target_id")[["family_id", "ligand_id"]]
    merged = interactions_df.merge(target_meta, left_on="target_id", right_index=True, how="left")

    results = []
    for family_id, fam_df in merged.groupby("family_id"):
        fam_df = fam_df.copy()
        fam_df["residue"] = fam_df["prot_restype"].astype(str) + fam_df["prot_resnr"].astype(str)
        pivot = fam_df.pivot_table(index="ligand_id", columns="residue", values="interaction_type",
                                    aggfunc="count", fill_value=0)
        pivot = (pivot > 0).astype(int)
        if pivot.shape[0] < 1 or pivot.shape[1] < 1:
            continue

        if pivot.shape[0] >= 3:
            import numpy as np
            from scipy.cluster.hierarchy import leaves_list, linkage
            from scipy.spatial.distance import pdist
            dist = np.nan_to_num(pdist(pivot.values.astype(float), metric="jaccard"))
            order = leaves_list(linkage(dist, method="average"))
            pivot = pivot.iloc[order]

        div_id = f"chart-fingerprint-{re.sub(r'[^a-zA-Z0-9_-]', '_', str(family_id))}"
        # Hard-step red/green colorscale (not a gradient) since z is strictly binary --
        # same red/green hex pair used for flags elsewhere on the dashboard (_make_scatter).
        fig = go.Figure(go.Heatmap(z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
                                    colorscale=[[0, "#d62728"], [0.5, "#d62728"], [0.5, "#2ca02c"], [1, "#2ca02c"]],
                                    zmin=0, zmax=1, showscale=False, xgap=2, ygap=2))
        # Heatmaps don't get a named-trace legend on their own -- two invisible marker
        # traces populate one, matching the interaction-counts chart's legend styling.
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                                  marker=dict(size=10, color="#2ca02c"), name="Interacting"))
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                                  marker=dict(size=10, color="#d62728"), name="Non-interacting"))
        fig.update_layout(legend=dict(font=dict(size=_LEGEND_FONTSIZE)))
        fig.update_xaxes(tickangle=-90, tickfont=dict(size=_TICK_FONTSIZE))
        fig.update_yaxes(tickfont=dict(size=_TICK_FONTSIZE), autorange="reversed")
        results.append((family_id, _plotly_to_div(fig, div_id)))
    return results


# ==========================================================================
# Ligand grid panel -- paginated 5x5 rendered-structure grid, building on the
# design of github.com/bellcheddar/smiles2grid (same author): per-cell 2D
# depiction + descriptors, with shared-substructure highlighting across the
# set. Adapted for a single campaign's typical scale (a handful to a few dozen
# ligands, often close SAR analogues) rather than smiles2grid's screening-scale
# use case, and wired into this campaign's own ligand-preparation findings.
# ==========================================================================

_LIGAND_GRID_PAGE_SIZE = 25  # 5x5, matching smiles2grid's page convention
_LIGAND_GRID_MIN_SCAFFOLD_ATOMS = 8  # suppress "they all contain a benzene ring"-style trivia
_LIGAND_GRID_MCS_SIMILARITY_THRESHOLD = 0.6
_LIGAND_GRID_IMG_SIZE = (260, 190)
_LIGAND_GRID_STEREO_COLOR = (0.847, 0.106, 0.549)     # magenta -- undefined stereocentre
_LIGAND_GRID_IONIZABLE_COLOR = (0.961, 0.620, 0.043)  # amber -- ionizable group
_LIGAND_GRID_FRAGMENT_COLOR = (0.70, 0.10, 0.10)      # red -- salt/counterion badge only (not atom-highlighted)
_LIGAND_GRID_CLUSTER_PALETTE = [                      # colour-blind-safe qualitative palette (Okabe-Ito derived)
    (0.000, 0.447, 0.698), (0.902, 0.624, 0.000), (0.000, 0.620, 0.451),
    (0.800, 0.475, 0.655), (0.835, 0.369, 0.000), (0.337, 0.706, 0.914),
]
_LIGAND_GRID_BADGE_LABELS = {
    "carboxylic acid": "A", "primary/secondary amine": "N", "phenol": "Ph", "sulfonic acid": "SO3",
}


def _rgb_css(color: tuple) -> str:
    return f"rgb({round(color[0] * 255)},{round(color[1] * 255)},{round(color[2] * 255)})"


def _rgb_hex(color: tuple) -> str:
    return f"#{round(color[0] * 255):02x}{round(color[1] * 255):02x}{round(color[2] * 255):02x}"


def _cluster_ligands_by_scaffold(mols_by_ligand: dict) -> list:
    # Two tiers, both defensible without a single hand-tuned "looks similar enough" call
    # driving what gets highlighted:
    #  1. Exact Bemis-Murcko scaffold match -- threshold-free, the dominant real case for
    #     an SAR series of close analogues sharing one core.
    #  2. For ligands left over, group by Morgan/Tanimoto similarity (a similarity
    #     *decision* is unavoidable here, so it's isolated to this fallback tier only) and
    #     verify the group with a real, whole-group MCS rather than asserting similarity
    #     alone -- the MCS substructure match is what actually gets highlighted, so the
    #     claim is geometrically proven, not just scored.
    #     (A "generic scaffold" tier -- bond/atom-type-abstracted Murcko cores, matched via
    #     RDKit's query-adjustment machinery -- was tried and dropped: it didn't reliably
    #     bridge aromatic vs. Kekulized-single-bond queries across independently-built
    #     molecules in testing, so a match could silently fail. A verified whole-group MCS
    #     has no such failure mode.)
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator, rdFMCS
    from rdkit.Chem.Scaffolds import MurckoScaffold

    clusters = []
    assigned = set()

    scaffold_by_lig = {}
    for lig_id, mol in mols_by_ligand.items():
        try:
            scaffold = MurckoScaffold.GetScaffoldForMol(mol)
        except Exception:
            continue
        if scaffold is not None and scaffold.GetNumHeavyAtoms() >= _LIGAND_GRID_MIN_SCAFFOLD_ATOMS:
            scaffold_by_lig[lig_id] = scaffold

    groups = {}
    for lig_id, scaffold in scaffold_by_lig.items():
        groups.setdefault(Chem.MolToSmiles(scaffold), []).append(lig_id)
    for members in groups.values():
        if len(members) >= 2:
            ref = scaffold_by_lig[members[0]]
            clusters.append({"level": "exact", "member_ids": members, "match_mol": ref, "template_mol": ref})
            assigned.update(members)

    remaining = [lig_id for lig_id in mols_by_ligand if lig_id not in assigned]
    fp_gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    fps = {lig_id: fp_gen.GetFingerprint(mols_by_ligand[lig_id]) for lig_id in remaining}

    parent = {lig_id: lig_id for lig_id in remaining}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(remaining):
        for b in remaining[i + 1:]:
            if DataStructs.TanimotoSimilarity(fps[a], fps[b]) >= _LIGAND_GRID_MCS_SIMILARITY_THRESHOLD:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

    fallback_groups = {}
    for lig_id in remaining:
        fallback_groups.setdefault(find(lig_id), []).append(lig_id)

    for members in fallback_groups.values():
        if len(members) < 2:
            continue
        mols = [mols_by_ligand[m] for m in members]
        try:
            res = rdFMCS.FindMCS(mols, timeout=5, ringMatchesRingOnly=True, completeRingsOnly=True)
        except Exception:
            continue
        if res.canceled or not res.smartsString:
            continue
        patt = Chem.MolFromSmarts(res.smartsString)
        if patt is None or patt.GetNumAtoms() < _LIGAND_GRID_MIN_SCAFFOLD_ATOMS:
            continue
        verified = [m for m in members if mols_by_ligand[m].HasSubstructMatch(patt)]
        if len(verified) >= 2:
            clusters.append({"level": "mcs", "member_ids": verified, "match_mol": patt, "template_mol": patt})
            assigned.update(verified)

    clusters.sort(key=lambda c: -len(c["member_ids"]))
    for i, cl in enumerate(clusters):
        cl["id"] = i
        cl["color"] = _LIGAND_GRID_CLUSTER_PALETTE[i % len(_LIGAND_GRID_CLUSTER_PALETTE)]
    return clusters


def _ligand_grid_descriptors(mol) -> dict:
    from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
    return {"mw": Descriptors.MolWt(mol), "clogp": Crippen.MolLogP(mol), "tpsa": rdMolDescriptors.CalcTPSA(mol)}


def _render_ligand_cell_image(mol, stereo_atoms: list, ionizable_atoms: dict, cluster) -> str:
    from rdkit.Chem import AllChem
    from rdkit.Chem.Draw import rdMolDraw2D

    # Scaffold-templated alignment: ligands sharing a cluster draw their common substructure
    # in the same position/orientation, so shared cores visibly line up across cells.
    aligned = False
    if cluster is not None:
        template = cluster["template_mol"]
        if not template.GetNumConformers():
            AllChem.Compute2DCoords(template)
        try:
            match = AllChem.GenerateDepictionMatching2DStructure(mol, template, refPatt=cluster["match_mol"],
                                                                   acceptFailure=True)
            aligned = bool(match)
        except Exception:
            aligned = False
    if not aligned:
        AllChem.Compute2DCoords(mol)

    # Highlight priority: a specific finding (stereocentre/ionizable atom) always wins over
    # the softer cluster-membership highlight, since it's the more actionable signal --
    # cluster colors are written first, then overwritten by finding colors.
    highlight_atoms, highlight_bonds = set(), set()
    atom_colors, bond_colors = {}, {}

    if cluster is not None:
        match = mol.GetSubstructMatch(cluster["match_mol"])
        if match:
            match_set = set(match)
            highlight_atoms |= match_set
            for idx in match_set:
                atom_colors[idx] = cluster["color"]
            for bond in mol.GetBonds():
                if bond.GetBeginAtomIdx() in match_set and bond.GetEndAtomIdx() in match_set:
                    highlight_bonds.add(bond.GetIdx())
                    bond_colors[bond.GetIdx()] = cluster["color"]

    for idx in {i for atoms in ionizable_atoms.values() for i in atoms}:
        highlight_atoms.add(idx)
        atom_colors[idx] = _LIGAND_GRID_IONIZABLE_COLOR
    for idx in stereo_atoms:
        highlight_atoms.add(idx)
        atom_colors[idx] = _LIGAND_GRID_STEREO_COLOR

    drawer = rdMolDraw2D.MolDraw2DCairo(*_LIGAND_GRID_IMG_SIZE)
    opts = drawer.drawOptions()
    opts.addStereoAnnotation = True  # draws RDKit's own (?) marker at undefined centres
    opts.padding = 0.08
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol, highlightAtoms=list(highlight_atoms),
                                        highlightAtomColors=atom_colors, highlightBonds=list(highlight_bonds),
                                        highlightBondColors=bond_colors)
    drawer.FinishDrawing()
    return base64.b64encode(drawer.GetDrawingText()).decode("ascii")


def _render_scaffold_thumbnail(mol) -> str:
    from rdkit.Chem import AllChem
    from rdkit.Chem.Draw import rdMolDraw2D
    if not mol.GetNumConformers():
        AllChem.Compute2DCoords(mol)
    drawer = rdMolDraw2D.MolDraw2DCairo(90, 70)
    drawer.drawOptions().padding = 0.1
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()
    return base64.b64encode(drawer.GetDrawingText()).decode("ascii")


def _compute_ligand_grid_cells(campaign: Campaign):
    # Shared by the HTML panel and the PDF export -- both renderers get the same
    # per-ligand data (rendered structure, severity, badges, cluster) so they can never
    # show different content, and the RDKit clustering/rendering work only happens once.
    from rdkit import Chem

    ccd_ligands = [lig for lig in campaign.ligands if lig.smiles is None]
    mols_by_ligand = {}
    for lig in campaign.ligands:
        if lig.smiles is None:
            continue
        mol = Chem.MolFromSmiles(lig.smiles)
        if mol is not None:
            mols_by_ligand[lig.id] = mol

    if not mols_by_ligand:
        return [], [], ccd_ligands, 0  # nothing renderable (all-CCD campaign)

    findings = _ligand_chemistry_notes(campaign)
    clusters = _cluster_ligands_by_scaffold(mols_by_ligand) if len(mols_by_ligand) >= 2 else []
    cluster_by_ligand = {m: cl for cl in clusters for m in cl["member_ids"]}

    cells = []
    for lig in campaign.ligands:
        if lig.id in mols_by_ligand:
            mol = mols_by_ligand[lig.id]
            info = findings.get(lig.id, {})
            stereo_atoms = info.get("stereo_atoms", [])
            ionizable_atoms = info.get("ionizable_atoms", {})
            has_fragments = info.get("has_fragments", False)
            cluster = cluster_by_ligand.get(lig.id)

            severity = "error" if (stereo_atoms or has_fragments) else ("review" if ionizable_atoms else "clean")
            badges = []
            if stereo_atoms:
                badges.append(("S", _LIGAND_GRID_STEREO_COLOR))
            if has_fragments:
                badges.append(("salt", _LIGAND_GRID_FRAGMENT_COLOR))
            for name in ionizable_atoms:
                badges.append((_LIGAND_GRID_BADGE_LABELS.get(name, name[:2]), _LIGAND_GRID_IONIZABLE_COLOR))

            img_b64 = _render_ligand_cell_image(mol, stereo_atoms, ionizable_atoms, cluster)
            desc = _ligand_grid_descriptors(mol)
            cells.append({"lig_id": lig.id, "kind": "smiles", "smiles": lig.smiles, "img_b64": img_b64,
                          "desc": desc, "severity": severity, "badges": badges, "cluster": cluster,
                          "stereo_atoms": stereo_atoms, "ionizable_atoms": ionizable_atoms,
                          "has_fragments": has_fragments})
        else:
            cells.append({"lig_id": lig.id, "kind": "ccd", "ccd_code": lig.ccd or "?"})

    return cells, clusters, ccd_ligands, len(mols_by_ligand)


def _write_ligand_grid_pdf(cells: list, path: Path) -> None:
    # Prints the same cells shown in the HTML grid (same 5x5 pagination, same rendered
    # PNGs decoded and re-embedded rather than redrawn -- no duplicate RDKit work) as a
    # PDF, matching the print-oriented output github.com/bellcheddar/smiles2grid (the
    # tool this panel's design builds on) produces natively.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    smiles_cells = [c for c in cells if c["kind"] == "smiles"]
    if not smiles_cells:
        return

    page_w, page_h = A4
    margin, gap = 24, 8
    cols, rows = 5, 5
    cell_w = (page_w - 2 * margin - (cols - 1) * gap) / cols
    cell_h = (page_h - 2 * margin - (rows - 1) * gap) / rows
    severity_colors = {"error": colors.HexColor(_rgb_hex(_LIGAND_GRID_STEREO_COLOR)),
                        "review": colors.HexColor(_rgb_hex(_LIGAND_GRID_IONIZABLE_COLOR)),
                        "clean": colors.HexColor("#dde4ed")}

    c = canvas.Canvas(str(path), pagesize=A4)
    pages = [cells[i:i + rows * cols] for i in range(0, len(cells), rows * cols)]
    for page_cells in pages:
        for idx, cell in enumerate(page_cells):
            row, col = divmod(idx, cols)
            x = margin + col * (cell_w + gap)
            y = page_h - margin - (row + 1) * cell_h - row * gap

            border = (colors.HexColor(_rgb_hex(cell["cluster"]["color"])) if cell.get("cluster")
                      else severity_colors.get(cell.get("severity"), colors.HexColor("#dde4ed")))
            c.setLineWidth(1.2)
            c.setStrokeColor(border)
            c.rect(x, y, cell_w, cell_h, stroke=1, fill=0)

            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(colors.black)
            c.drawCentredString(x + cell_w / 2, y + cell_h - 12, cell["lig_id"])

            if cell["kind"] == "smiles":
                img = ImageReader(io.BytesIO(base64.b64decode(cell["img_b64"])))
                iw, ih = img.getSize()
                avail_w, avail_h = cell_w - 12, cell_h - 42
                scale = min(avail_w / iw, avail_h / ih)
                draw_w, draw_h = iw * scale, ih * scale
                c.drawImage(img, x + (cell_w - draw_w) / 2, y + 24 + (avail_h - draw_h) / 2,
                            width=draw_w, height=draw_h, mask="auto")

                desc = cell["desc"]
                c.setFont("Helvetica", 6.5)
                c.drawCentredString(x + cell_w / 2, y + 12,
                                    f"MW {desc['mw']:.0f}  cLogP {desc['clogp']:.1f}  TPSA {desc['tpsa']:.0f}")
                if cell["badges"]:
                    c.setFont("Helvetica-Bold", 6.5)
                    c.setFillColor(colors.HexColor(_rgb_hex(cell["badges"][0][1])))
                    c.drawCentredString(x + cell_w / 2, y + 4, " ".join(lbl for lbl, _ in cell["badges"]))
                    c.setFillColor(colors.black)
            else:
                c.setFont("Courier-Bold", 9)
                c.drawCentredString(x + cell_w / 2, y + cell_h / 2 + 4, cell.get("ccd_code", "?"))
                c.setFont("Helvetica", 6.5)
                c.drawCentredString(x + cell_w / 2, y + cell_h / 2 - 8, "No 2D structure (CCD)")
        c.showPage()
    c.save()


def _build_ligand_grid_panel(campaign: Campaign, campaign_dir: Path) -> str:
    if not campaign.ligands:
        return ""

    cells, clusters, ccd_ligands, n_smiles = _compute_ligand_grid_cells(campaign)
    if not cells:
        return ""  # nothing renderable (all-CCD campaign) -- skip the panel entirely

    cells_html = []
    for cell in cells:
        if cell["kind"] == "smiles":
            badge_html = "".join(f"<span class='lig-badge' style='background:{_rgb_css(c)}'>{lbl}</span>"
                                  for lbl, c in cell["badges"])
            cluster, desc = cell["cluster"], cell["desc"]
            border = f"border-color:{_rgb_css(cluster['color'])};" if cluster else ""
            cells_html.append(
                f"<div class='lig-cell lig-severity-{cell['severity']}' style='{border}'>"
                f"<div class='lig-cell-header'><span>{cell['lig_id']}</span><span class='lig-badges'>{badge_html}</span></div>"
                f"<img src='data:image/png;base64,{cell['img_b64']}' alt='{cell['lig_id']} structure'>"
                f"<div class='lig-cell-desc'>MW {desc['mw']:.0f} &middot; cLogP {desc['clogp']:.1f} "
                f"&middot; TPSA {desc['tpsa']:.0f}</div></div>"
            )
        else:
            cells_html.append(
                f"<div class='lig-cell lig-cell-ccd-wrap'>"
                f"<div class='lig-cell-header'><span>{cell['lig_id']}</span></div>"
                f"<div class='lig-cell-ccd'>{cell['ccd_code']}<br><small>No 2D structure (CCD ligand)</small></div></div>"
            )

    pages = [cells_html[i:i + _LIGAND_GRID_PAGE_SIZE] for i in range(0, len(cells_html), _LIGAND_GRID_PAGE_SIZE)]
    pages_html = "".join(
        f"<div class='lig-page' data-page='{i}'{'' if i == 0 else ' hidden'}>{''.join(page)}</div>"
        for i, page in enumerate(pages))
    pager_html = ("<div id='lig-pager'><button id='lig-prev'>&lsaquo; Prev</button>"
                  "<span id='lig-pageinfo'></span><button id='lig-next'>Next &rsaquo;</button>"
                  "<button id='lig-all'>Show all</button></div>") if len(pages) > 1 else ""

    legend_items = []
    for cl in clusters:
        thumb = _render_scaffold_thumbnail(cl["match_mol"])
        label = "shared scaffold" if cl["level"] == "exact" else "shared substructure (fallback match)"
        legend_items.append(
            f"<span class='lig-legend-item'><img class='lig-legend-thumb' style='border-color:{_rgb_css(cl['color'])}' "
            f"src='data:image/png;base64,{thumb}'>{label} -- {len(cl['member_ids'])}/{n_smiles} ligands</span>")
    # Badge key: same chip styling as the actual grid cells (.lig-badge), so each
    # abbreviation shown on a ligand can be looked up directly against its meaning here.
    badge_key = [("S", _LIGAND_GRID_STEREO_COLOR, "undefined stereocentre")]
    badge_key += [(lbl, _LIGAND_GRID_IONIZABLE_COLOR, name) for name, lbl in _LIGAND_GRID_BADGE_LABELS.items()]
    badge_key.append(("salt", _LIGAND_GRID_FRAGMENT_COLOR, "salt/disconnected fragment"))
    for lbl, color, meaning in badge_key:
        legend_items.append(
            f"<span class='lig-legend-item'><span class='lig-badge' style='background:{_rgb_css(color)}'>{lbl}</span>"
            f"{meaning}</span>")
    legend_html = f"<div class='lig-grid-legend'>{''.join(legend_items)}</div>"

    if not clusters and n_smiles >= 2:
        commonality_note = ("<p>No shared scaffold or substructure detected across the set -- "
                             "ligands are structurally distinct.</p>")
    elif clusters and len(clusters[0]["member_ids"]) == n_smiles:
        commonality_note = f"<p>All {n_smiles} SMILES ligands share scaffold {clusters[0]['id'] + 1} below.</p>"
    else:
        commonality_note = ""

    ccd_note = (f"<p>{n_smiles} SMILES ligand(s) analyzed; {len(ccd_ligands)} CCD-code ligand(s) not depicted "
                "(no SMILES to render).</p>") if ccd_ligands else ""

    footnote = ("<p class='lig-footnote'>Scaffolds: Bemis-Murcko, exact match first, then Tanimoto-clustered "
                f"(Morgan r=2, 2048-bit, threshold {_LIGAND_GRID_MCS_SIMILARITY_THRESHOLD:.2f}) whole-group MCS as "
                f"a verified fallback. Minimum highlighted substructure size: {_LIGAND_GRID_MIN_SCAFFOLD_ATOMS} "
                "heavy atoms. Stereocentre/ionizable-group highlighting from this campaign's own ligand-preparation "
                "check (see above).</p>")

    download_links = []
    smiles_cells = [c for c in cells if c["kind"] == "smiles"]
    if smiles_cells:
        pdf_path = campaign_dir / "boltz_ligand_grid.pdf"
        _write_ligand_grid_pdf(cells, pdf_path)
        download_links.append(f"<a href='{pdf_path.name}' download>Download PDF</a>")

        smiles_rows = [{
            "ID": c["lig_id"], "SMILES": c["smiles"],
            "Undefined stereocentres": len(c["stereo_atoms"]),
            "Ionizable groups": "; ".join(c["ionizable_atoms"]),
            "Salts/disconnected fragments": "Yes" if c["has_fragments"] else "No",
            "MW": round(c["desc"]["mw"], 2), "cLogP": round(c["desc"]["clogp"], 2),
            "TPSA": round(c["desc"]["tpsa"], 2),
        } for c in smiles_cells]
        smiles_csv = pd.DataFrame(smiles_rows).to_csv(index=False)
        smiles_csv_b64 = base64.b64encode(smiles_csv.encode("utf-8")).decode("ascii")
        download_links.append(f"<a href='data:text/csv;base64,{smiles_csv_b64}' "
                              "download='boltz_ligands.csv'>Download SMILES</a>")
    # Same "one <p>, links joined by a middle dot" style as the Summary table's CSV links.
    download_links_html = f"<p>{' &middot; '.join(download_links)}</p>" if download_links else ""

    return (f"<div class='md-card table-card'><h2>Ligand structures</h2>{commonality_note}{ccd_note}"
            f"{legend_html}<div id='lig-grid'>{pages_html}</div>{pager_html}{download_links_html}{footnote}</div>")


# marcdeller.com brand theme (see marcs-vibe-coding skill) -- keep in sync with any
# future BoltzMaker HTML output so every generated report looks the same.
_BRAND_CSS = """
:root {
  --md-primary: #1e73be;
  --md-primary-dark: #155a9c;
  --md-primary-light: #4a9fd4;
  --md-bg: #ffffff;
  --md-bg-alt: #f4f7fb;
  --md-surface: #ffffff;
  --md-border: #dde4ed;
  --md-text: #1a1a2e;
  --md-text-muted: #6b7c93;
  --md-text-light: #ffffff;
  --md-accent-green: #00d084;
  --md-accent-orange: #ff6900;
  --md-accent-purple: #9b51e0;
  --md-accent-amber: #fcb900;
  --md-shadow-sm: 6px 6px 9px rgba(0,0,0,0.12);
  --md-shadow-md: 12px 12px 50px rgba(0,0,0,0.18);
  --md-radius: 8px;
  --md-radius-lg: 16px;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  overflow-x: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 15px;
  line-height: 1.6;
  color: var(--md-text);
  background: var(--md-bg-alt);
}
img, canvas { max-width: 100%; height: auto; }
.md-header {
  background: linear-gradient(135deg, var(--md-primary-dark) 0%, var(--md-primary) 100%);
  color: var(--md-text-light);
  box-shadow: var(--md-shadow-sm);
  position: sticky;
  top: 0;
  z-index: 100;
}
.md-header-inner {
  max-width: 1400px;
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.md-header-brand a {
  display: flex;
  align-items: center;
  gap: 8px;
  color: rgba(255,255,255,0.9);
  text-decoration: none;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.md-logo-dot { width: 10px; height: 10px; background: var(--md-accent-amber); border-radius: 50%; flex-shrink: 0; }
.md-header-title { flex: 1; min-width: 0; }
.md-header-title h1 { font-size: 16px; font-weight: 700; color: #fff; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.md-header-links { display: flex; gap: 10px; flex-shrink: 0; flex-wrap: wrap; }
.md-header-links a {
  color: rgba(255,255,255,0.85);
  text-decoration: none;
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: 20px;
  white-space: nowrap;
}
.md-main { max-width: 1400px; margin: 0 auto; padding: 24px; }
.md-card { background: var(--md-surface); border: 1px solid var(--md-border); border-radius: var(--md-radius); padding: 20px; box-shadow: var(--md-shadow-sm); margin-bottom: 24px; }
.md-card h2 { margin-top: 0; font-size: 16px; }
.md-card.table-card { overflow-x: auto; max-width: 100%; }
.md-chart-grid, .md-side-by-side { display: grid; gap: 16px; grid-template-columns: repeat(2, 1fr); margin-bottom: 24px; }
.md-side-by-side.md-side-3col { grid-template-columns: repeat(3, 1fr); }
.md-chart-grid .md-card, .md-side-by-side { margin-bottom: 0; }
.md-chart-grid .md-card img, .md-side-image img { width: 100%; height: 260px; object-fit: contain; display: block; }
.md-chart-grid .md-card-span2 { grid-column: 1 / -1; }
.md-side-table { overflow: visible; }
.md-side-table table { font-size: 10px; }
.md-side-table th, .md-side-table td { padding: 3px 6px; }
/* Each binding-site column stretches to the row's full height by default (grid items
   stretch to match the tallest cell in the row); turning each into a column flexbox and
   pushing its trailing download link down with margin-top:auto keeps every link aligned
   to the bottom of the row, even when the contacts table is much taller than the fixed
   260px image/3D-viewer columns next to it. */
.md-side-viewer, .md-side-image, .md-side-table-col { display: flex; flex-direction: column; }
.md-side-viewer .md-3dmol-viewer, .md-side-image img { flex-shrink: 0; }
.md-side-viewer p, .md-side-image p, .md-side-table-col p { margin-top: auto; }
.md-3dmol-viewer { width: 100%; height: 260px; position: relative; background: #fff; border-radius: var(--md-radius); }
table { border-collapse: collapse; font-family: 'Roboto Mono', monospace; font-size: 12px; width: 100%; max-width: 100%; }
th, td { border: 1px solid var(--md-border); padding: 5px 9px; text-align: left; white-space: nowrap; }
th { background: var(--md-bg-alt); font-weight: 600; position: sticky; top: 0; }
tr:nth-child(even) { background: var(--md-bg-alt); }
/* Full table: many columns of mostly-numeric data -- fixed layout + wrapping keeps
   the whole table within the viewport instead of forcing one-line-per-cell widths
   that overflow far past the browser width. */
.md-card.table-card table { table-layout: fixed; }
.md-card.table-card th, .md-card.table-card td { white-space: normal; word-break: break-word; font-size: 11px; }
/* Full table: grouped header (colspan) + narrow right-aligned numeric columns, so a
   campaign with 20+ raw fields still fits without the whole table needing to scroll --
   only the identity columns (family/ligand/flags) stay left-aligned and get to wrap. */
.full-table { table-layout: auto; }
.full-table th, .full-table td { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; padding: 4px 8px; }
.full-table th.ft-group { text-align: center; background: var(--md-bg-alt); }
.full-table td:not(.ft-num), .full-table th:not(.ft-group):not(.ft-num) { text-align: left; white-space: normal; }
.full-table th.ft-group-start, .full-table td.ft-group-start { border-left: 2px solid var(--md-primary); }
.md-footer { text-align: center; padding: 24px; color: var(--md-text-muted); font-size: 13px; }
.md-footer a { color: var(--md-primary); text-decoration: none; }
.lig-grid-legend { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-bottom: 14px; font-size: 12px; color: var(--md-text-muted); }
.lig-legend-item { display: inline-flex; align-items: center; gap: 6px; }
.lig-swatch { width: 13px; height: 13px; border-radius: 3px; display: inline-block; flex-shrink: 0; }
.lig-legend-thumb { width: 40px; height: 32px; object-fit: contain; border: 2px solid; border-radius: 4px; background: #fff; flex-shrink: 0; }
.lig-footnote { font-size: 11px; color: var(--md-text-muted); margin-top: 12px; }
#lig-grid { margin-bottom: 12px; }
.lig-page { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.lig-page[hidden] { display: none; }
.lig-cell { border: 2px solid var(--md-border); border-radius: var(--md-radius); padding: 8px; background: var(--md-bg-alt); display: flex; flex-direction: column; }
.lig-cell.lig-severity-error { border-color: #d81b8c; }
.lig-cell.lig-severity-review { border-color: #f59e0b; }
.lig-cell-header { display: flex; justify-content: space-between; align-items: center; font-size: 11px; font-weight: 600; margin-bottom: 4px; gap: 4px; }
.lig-badges { display: flex; gap: 3px; flex-wrap: wrap; justify-content: flex-end; }
.lig-badge { font-size: 9px; font-weight: 700; color: #fff; padding: 1px 5px; border-radius: 3px; white-space: nowrap; }
.lig-cell img { width: 100%; height: 140px; object-fit: contain; display: block; background: #fff; border-radius: 4px; }
.lig-cell-desc { font-size: 10px; color: var(--md-text-muted); text-align: center; margin-top: 4px; }
.lig-cell-ccd-wrap { align-items: center; }
.lig-cell-ccd { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 140px; width: 100%; color: var(--md-text-muted); font-family: 'Roboto Mono', monospace; text-align: center; }
#lig-pager { display: flex; align-items: center; gap: 12px; margin-top: 12px; font-size: 13px; }
#lig-pager button { padding: 4px 14px; border-radius: 20px; border: 1px solid var(--md-border); background: var(--md-surface); color: var(--md-text); cursor: pointer; }
#lig-pager button:disabled { opacity: 0.4; cursor: default; }
@media (max-width: 768px) {
  .md-header-inner { padding: 10px 16px; gap: 8px; }
  .md-header-title h1 { font-size: 14px; }
  .md-header-links a { font-size: 11px; padding: 3px 8px; }
  .md-main { padding: 14px; }
  .md-card { padding: 14px; }
  .md-chart-grid, .md-side-by-side, .md-side-by-side.md-side-3col { grid-template-columns: 1fr; }
  .lig-page { grid-template-columns: repeat(2, 1fr); }
}
"""

_BRAND_HEADER = """
<header class="md-header">
  <div class="md-header-inner">
    <div class="md-header-brand">
      <a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">
        <span class="md-logo-dot"></span>
        <span class="md-logo-text">Marc C. Deller, D.Phil.</span>
      </a>
    </div>
    <div class="md-header-title"><h1>BoltzMaker Report</h1></div>
    <div class="md-header-links">
      <a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">marcdeller.com</a>
      <a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a>
    </div>
  </div>
</header>
"""

_BRAND_FOOTER = """
<footer class="md-footer">
  Built with BoltzMaker by
  <a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">Marc C. Deller, D.Phil.</a>
  &middot; <a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a>
</footer>
"""

# All pages are already in the DOM (base64 PNGs pre-embedded by Python); this only
# toggles `hidden`. No lazy-loading/observers needed at this dashboard's scale.
_LIGAND_GRID_PAGER_JS = """
(function () {
  var pages = Array.prototype.slice.call(document.querySelectorAll('#lig-grid .lig-page'));
  var pager = document.getElementById('lig-pager');
  if (!pages.length || !pager) return;
  var prev = document.getElementById('lig-prev');
  var next = document.getElementById('lig-next');
  var showAllBtn = document.getElementById('lig-all');
  var info = document.getElementById('lig-pageinfo');
  var cur = 0;
  var allShown = false;
  function show(i) {
    allShown = false;
    cur = Math.max(0, Math.min(i, pages.length - 1));
    pages.forEach(function (p, idx) { p.hidden = (idx !== cur); });
    info.textContent = 'Page ' + (cur + 1) + ' / ' + pages.length;
    prev.disabled = (cur === 0);
    next.disabled = (cur === pages.length - 1);
  }
  prev.addEventListener('click', function () { show(cur - 1); });
  next.addEventListener('click', function () { show(cur + 1); });
  showAllBtn.addEventListener('click', function () {
    allShown = !allShown;
    if (allShown) {
      pages.forEach(function (p) { p.hidden = false; });
      info.textContent = 'Showing all ' + pages.length + ' pages';
      prev.disabled = true; next.disabled = true;
    } else {
      show(cur);
    }
  });
  show(0);
})();
"""


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _partner_display_id(partner_id) -> str:
    return partner_id if isinstance(partner_id, str) else "/".join(partner_id)


def _build_campaign_summary(campaign: Campaign, campaign_dir: Path) -> list:
    # Three columns: Field/Value stay short and scannable, Details carries everything
    # that would otherwise clutter Value -- ids, lengths, pointers to other cards, and a
    # plain-English gloss for the more cryptic run-parameter names.
    targets = _expand_targets(campaign)
    rows = []

    if campaign.source_path:
        fname = campaign.source_path.name
        rows.append(("Input file", fname, f"<a href='{fname}'>{fname}</a>"))
    else:
        rows.append(("Input file", "n/a", ""))

    fam_details = "; ".join(f"{f.id} ({len(f.sequence)} aa)" for f in campaign.families)
    rows.append(("Proteins", str(len(campaign.families)), fam_details))

    partner_list = list(campaign.partners.values())
    partner_details = "; ".join(f"{_partner_display_id(p.id)} ({p.type}, {len(p.sequence)} aa)"
                                 for p in partner_list) if partner_list else "none"
    rows.append(("Partners", str(len(partner_list)), partner_details))

    lig_details = "; ".join(f"{l.id} ({'SMILES' if l.smiles else f'CCD {l.ccd}'})" for l in campaign.ligands)
    rows.append(("Ligands", str(len(campaign.ligands)), lig_details))

    target_stems = ", ".join(f"{fam.id}_{lig.id}" for fam, lig in targets)
    rows.append(("Targets (protein x ligand)", str(len(targets)), target_stems))

    aff_detail = ("pIC50 predicted for every target" if campaign.settings.predict_affinity
                  else "structure only -- no affinity model run")
    rows.append(("Predict affinity", "yes" if campaign.settings.predict_affinity else "no", aff_detail))

    lig_notes = _ligand_chemistry_notes(campaign)
    if lig_notes:
        rows.append(("Ligand chemistry", f"{len(lig_notes)} of {len(campaign.ligands)} flagged",
                     f'{", ".join(lig_notes)} -- see "Ligand preparation" below'))
    else:
        rows.append(("Ligand chemistry", "clean", "no stereo/protonation/fragment concerns detected"))

    history_path = campaign_dir / RUN_HISTORY_FILENAME
    if history_path.exists():
        records = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
        if records:
            total_duration = sum(r.get("duration_seconds", 0) for r in records)
            last = records[-1]
            invocation_detail = (f"across {len(records)} run invocations" if len(records) > 1
                                  else "single run invocation")
            rows.append(("Boltz predict runtime", _format_duration(total_duration), invocation_detail))
            rows.append(("Accelerator", str(last.get("accelerator", "n/a")),
                         "gpu = Metal/CUDA backend used; cpu = no GPU available"))
            rows.append(("Workers", str(last.get("workers", "n/a")),
                         "parallel data-loading workers (Boltz's own default is 2)"))
            rows.append(("MPS watermark", str(last.get("mps_watermark", "n/a")),
                         "PYTORCH_MPS_HIGH_WATERMARK_RATIO cap -- lower avoids swap on Apple unified memory"))
            rows.append(("Max parallel samples", str(last.get("max_parallel_samples", "n/a")),
                         "Boltz's own --max_parallel_samples"))
            param_details = {
                "recycling_steps": "structure-refinement recycling iterations",
                "sampling_steps": "diffusion sampling steps for structure prediction",
                "diffusion_samples_affinity": "independent affinity-model ensemble members",
                "sampling_steps_affinity": "diffusion sampling steps for the affinity model",
                "max_msa_seqs": "cap on MSA sequences used for co-evolution features",
            }
            for key, label in (("recycling_steps", "Recycling steps"), ("sampling_steps", "Sampling steps"),
                               ("diffusion_samples_affinity", "Diffusion samples (affinity)"),
                               ("sampling_steps_affinity", "Sampling steps (affinity)"),
                               ("max_msa_seqs", "Max MSA sequences")):
                if last.get(key) is not None:
                    rows.append((label, str(last[key]), param_details.get(key, "")))
    return rows


_FULL_TABLE_HIDE_PATTERNS = [
    # Regex, not a fixed list -- so per-chain/per-pair columns are hidden regardless of
    # how many chains a campaign has (a hardcoded 2-chain list previously leaked
    # chains_ptm_2 and all six pair_chains_iptm_*_2/2_* columns for a 3-chain campaign).
    # Everything hidden here is either a raw concatenation of columns already shown, an
    # ensemble sub-model's individual number (the ensemble/primary value is shown
    # instead), a granular per-chain(-pair) breakdown of an interface summary number
    # already shown, or an internal file path already surfaced elsewhere in the
    # dashboard. All of it remains in the full "Download CSV" export.
    r"^target_id$", r"^ligand_smiles$", r"^notes$",
    r"^complex_iplddt$", r"^complex_pde$", r"^complex_ipde$",
    r"^chains_ptm_\d+$", r"^pair_chains_iptm_\d+_\d+$",
    r".*_path$", r"^plip_status$",
    r"^affinity_pred_value\d*$", r"^affinity_probability_binary[12]$",
    r"^pIC50_[12]$", r"^pIC50_ensemble_mean$",
]

_FULL_TABLE_RENAME = {
    "family_id": "Target", "ligand_id": "Ligand", "flags": "Flags",
    "confidence_score": "Score", "ptm": "pTM", "iptm": "ipTM",
    "ligand_iptm": "Lig ipTM", "protein_iptm": "PPI ipTM",
    "complex_plddt": "pLDDT", "pIC50": "pIC50", "pIC50_ensemble_std": "pIC50 SD",
    "affinity_probability_binary": "Binder p", "cif_file": "CIF",
}
_FULL_TABLE_GROUPS = {
    "family_id": "Identity", "ligand_id": "Identity", "flags": "Identity",
    "confidence_score": "Confidence", "ptm": "Confidence", "iptm": "Confidence",
    "ligand_iptm": "Confidence", "protein_iptm": "Confidence", "complex_plddt": "Confidence",
    "pIC50": "Affinity", "affinity_probability_binary": "Affinity",
    "cif_file": "Structure",
}
_FULL_TABLE_GROUP_ORDER = ["Identity", "Confidence", "Affinity", "Interactions", "Structure", "Other"]
_FULL_TABLE_TEXT_COLS = {"family_id", "ligand_id", "flags"}
_PLIP_COUNT_LABELS = {
    "hydrogen_bonds": "H-bond", "hydrophobic": "Phobic", "pi_stacks": "π-stack",
    "salt_bridges": "Salt", "pi_cation": "π-cation", "halogen_bonds": "Halogen",
    "water_bridges": "Water",
}


def _full_table_label(col: str) -> str:
    if col in _FULL_TABLE_RENAME:
        return _FULL_TABLE_RENAME[col]
    if col.startswith("plip_") and col.endswith("_count"):
        itype = col[len("plip_"):-len("_count")]
        return _PLIP_COUNT_LABELS.get(itype, itype.replace("_", " ").title())
    return col


def _full_table_group(col: str) -> str:
    if col in _FULL_TABLE_GROUPS:
        return _FULL_TABLE_GROUPS[col]
    if col.startswith("plip_") and col.endswith("_count"):
        return "Interactions"
    return "Other"


def _resolve_summary_table_columns(df: pd.DataFrame) -> list:
    # Shared by the HTML summary table and the summary CSV export, so the two can never
    # show different columns. Regex-based hiding (not a fixed list) so per-chain/
    # per-chain-pair columns are hidden regardless of how many chains a campaign has --
    # a hardcoded 2-chain list previously leaked chains_ptm_2 and all six 3-chain
    # pair_chains_iptm_*_2/2_* columns straight into the table.
    hidden = re.compile("|".join(_FULL_TABLE_HIDE_PATTERNS))
    cols = [c for c in df.columns if not hidden.match(c)]

    # Conditional-by-content, not by config: a column that's empty/zero for every row in
    # *this* campaign (no partner chain -> protein_iptm always 0; no flags raised at all)
    # is dropped, rather than hardcoding "only show for multi-chain campaigns".
    kept = []
    for c in cols:
        if c == "pIC50_ensemble_std":
            continue  # merged into the pIC50 cell/column as "± SD", never its own column
        s = df[c]
        if c == "flags":
            if not s.fillna("").astype(str).str.strip().any():
                continue
        elif c == "protein_iptm":
            if s.fillna(0).eq(0).all():
                continue
        elif pd.api.types.is_numeric_dtype(s) and s.isna().all():
            continue
        kept.append(c)
    cols = kept
    cols.sort(key=lambda c: _FULL_TABLE_GROUP_ORDER.index(_full_table_group(c)))
    return cols


def write_summary_csv(df: pd.DataFrame, path: Path) -> None:
    # Mirrors the HTML "Summary table" exactly (same columns, same renamed headers) --
    # unlike the HTML cell, pIC50's ensemble stdev stays its own numeric column here
    # rather than a merged "value ± SD" string, since a CSV is for further analysis.
    cols = _resolve_summary_table_columns(df)
    out_cols = list(cols)
    if "pIC50" in out_cols and "pIC50_ensemble_std" in df.columns:
        out_cols.insert(out_cols.index("pIC50") + 1, "pIC50_ensemble_std")
    export_df = df[out_cols].copy() if out_cols else df.iloc[:, :0].copy()
    export_df.columns = [_full_table_label(c) for c in out_cols]
    export_df.to_csv(path, index=False)


def _build_full_table_html(df: pd.DataFrame) -> str:
    cols = _resolve_summary_table_columns(df)
    if not cols:
        return "<p>No columns to display.</p>"

    groups = [_full_table_group(c) for c in cols]
    has_sd = "pIC50" in cols and "pIC50_ensemble_std" in df.columns

    def group_header_row() -> str:
        cells, i = [], 0
        while i < len(groups):
            j = i
            while j < len(groups) and groups[j] == groups[i]:
                j += 1
            cells.append(f"<th colspan='{j - i}' class='ft-group'>{groups[i]}</th>")
            i = j
        return f"<tr>{''.join(cells)}</tr>"

    def column_header_row() -> str:
        cells, prev = [], None
        for c, g in zip(cols, groups):
            classes = ([] if g == prev else ["ft-group-start"]) + ([] if c in _FULL_TABLE_TEXT_COLS else ["ft-num"])
            cells.append(f"<th class='{' '.join(classes)}'>{_full_table_label(c)}</th>")
            prev = g
        return f"<tr>{''.join(cells)}</tr>"

    def cell_html(row, c: str) -> str:
        v = row[c]
        if c == "cif_file":
            return "" if pd.isna(v) else f"<a href='boltz_cif/{v}'>CIF</a>"
        if c in _FULL_TABLE_TEXT_COLS:
            return "" if pd.isna(v) else str(v)
        if pd.isna(v):
            return ""
        text = f"{v:.2f}" if isinstance(v, float) else str(v)
        if c == "pIC50" and has_sd and not pd.isna(row.get("pIC50_ensemble_std")):
            text += f" ± {row['pIC50_ensemble_std']:.2f}"
        return text

    def body_row(row) -> str:
        cells, prev = [], None
        for c, g in zip(cols, groups):
            classes = ([] if g == prev else ["ft-group-start"]) + ([] if c in _FULL_TABLE_TEXT_COLS else ["ft-num"])
            cells.append(f"<td class='{' '.join(classes)}'>{cell_html(row, c)}</td>")
            prev = g
        return f"<tr>{''.join(cells)}</tr>"

    body = "".join(body_row(row) for _, row in df.iterrows())
    return (f"<table class='full-table'><thead>{group_header_row()}{column_header_row()}</thead>"
            f"<tbody>{body}</tbody></table>")


def write_html(df: pd.DataFrame, path: Path, campaign_dir: Path, campaign: Campaign) -> None:
    summary_rows = _build_campaign_summary(campaign, campaign_dir)
    summary_html = pd.DataFrame(summary_rows, columns=["Field", "Value", "Details"]).to_html(
        index=False, na_rep="", escape=False)
    parts = [f"<div class='md-card table-card'><h2>Campaign summary</h2>{summary_html}</div>"]

    summary_view_path = campaign_dir / "boltz_summary_view.csv"
    write_summary_csv(df, summary_view_path)
    csv_links = ("<p><a href='boltz_summary.csv'>Download full CSV</a> &middot; "
                 f"<a href='{summary_view_path.name}'>Download summary CSV</a></p>")
    parts.append(f"<div class='md-card table-card'><h2>Summary table</h2>"
                 f"{_build_full_table_html(df)}{csv_links}</div>")

    lig_notes = _ligand_chemistry_notes(campaign)
    if lig_notes:
        lig_rows = [{"Ligand": lig_id, "Chemistry notes": "; ".join(info["notes"])} for lig_id, info in lig_notes.items()]
        lig_html = pd.DataFrame(lig_rows).to_html(index=False, na_rep="")
        lig_note_text = (f"{len(lig_notes)} of {len(campaign.ligands)} ligand(s) flagged for chemistry review "
                          "-- these are advisory, not errors; verify the input SMILES reflects what you intended "
                          "before trusting the results below.")
        parts.append(f"<div class='md-card table-card'><h2>Ligand preparation</h2>"
                      f"<p>{lig_note_text}</p>{lig_html}</div>")
    else:
        parts.append("<div class='md-card table-card'><h2>Ligand preparation</h2>"
                      "<p>No stereocentre, protonation-state, or disconnected-fragment concerns detected.</p></div>")

    ligand_grid_html = _build_ligand_grid_panel(campaign, campaign_dir)
    if ligand_grid_html:
        parts.append(ligand_grid_html)

    chart_cards = []
    for col, title, div_id in (("pIC50", "Ranked predicted pIC50", "chart-pic50"),
                               ("confidence_score", "Ranked confidence", "chart-confidence")):
        chart_html = _make_bar_chart(df, col, div_id)
        if chart_html:
            chart_cards.append(f"<div class='md-card'><h2>{title}</h2>{chart_html}</div>")

    heat = _make_selectivity_heatmap(df)
    if heat:
        chart_cards.append(f"<div class='md-card'><h2>Family x ligand selectivity</h2><img src='data:image/png;base64,{heat}'></div>")

    scatter = _make_scatter(df, "chart-scatter")
    if scatter:
        chart_cards.append(f"<div class='md-card'><h2>Confidence vs affinity</h2>{scatter}</div>")

    interactions_csv = campaign_dir / "boltz_interactions.csv"
    interactions_df = pd.read_csv(interactions_csv) if interactions_csv.exists() else None

    ichart = _make_interaction_count_chart(df, "chart-interactions")
    if ichart:
        chart_cards.append(f"<div class='md-card'><h2>Interaction counts by type</h2>{ichart}</div>")

    for family_id, chart_html in _make_fingerprint_heatmaps(df, interactions_df):
        chart_cards.append(f"<div class='md-card md-card-span2'><h2>{family_id}: residue interaction fingerprint</h2>"
                            f"{chart_html}</div>")

    if chart_cards:
        parts.append(f"<div class='md-chart-grid'>{''.join(chart_cards)}</div>")

    need_3dmol = False
    if "plip_png_path" in df.columns:
        sessions_dir = campaign_dir / "boltz_dashboard_sessions"
        session_cards, total_bytes = [], 0
        viewer_scripts = []
        for _, row in df.iterrows():
            png_rel = row.get("plip_png_path")
            if not isinstance(png_rel, str):
                continue
            png_path = campaign_dir / png_rel
            if not png_path.exists():
                continue
            target_id = row["target_id"]
            b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
            img_download = f"boltz_binding_site_{target_id}.png"
            image_links = [f"<a href='data:image/png;base64,{b64}' download='{img_download}'>Download image</a>"]

            pse_rel = row.get("plip_pse_path")
            pse_link_html = None
            if isinstance(pse_rel, str) and (campaign_dir / pse_rel).exists():
                sessions_dir.mkdir(exist_ok=True)
                dest = sessions_dir / f"{target_id}.pse"
                shutil.copy2(campaign_dir / pse_rel, dest)
                total_bytes += dest.stat().st_size
                pse_link_html = f"<a href='boltz_dashboard_sessions/{dest.name}' download>Download PyMOL session</a>"

            # Interactive rotating structure view next to the static PyMOL image, built
            # from the same predicted CIF -- 3Dmol.js parses mmCIF natively (format "cif"),
            # so the raw file goes in directly; no PDB conversion needed (Boltz's own chain
            # names, e.g. a 3-letter family id, are longer than PDB's 1-character chain
            # field allows and would need remapping otherwise).
            # Everything for a grid column must be ONE element -- CSS Grid auto-places every
            # direct child of the grid container into its own cell, so a viewer div followed
            # by a sibling <p> (rather than both nested inside one wrapper) silently shifts
            # every column after it over by one, which is exactly what happened here.
            viewer_col = ""
            cif_rel = row.get("cif_file")
            if isinstance(cif_rel, str):
                cif_path = campaign_dir / "boltz_cif" / cif_rel
                if cif_path.exists():
                    div_id = f"viewer-{re.sub(r'[^a-zA-Z0-9_-]', '_', str(target_id))}"
                    cif_json = json.dumps(cif_path.read_text())
                    need_3dmol = True
                    viewer_scripts.append(f"""
(function() {{
  var el = document.getElementById({json.dumps(div_id)});
  if (!el || typeof $3Dmol === 'undefined') return;
  var viewer = $3Dmol.createViewer(el, {{backgroundColor: 'white'}});
  var model = viewer.addModel({cif_json}, 'cif');
  viewer.setStyle({{}}, {{cartoon: {{color: 'lightgrey'}}}});
  viewer.setStyle({{hetflag: true}}, {{stick: {{colorscheme: 'greenCarbon'}}}});
  var lig = model.selectedAtoms({{hetflag: true}});
  if (lig.length) {{ viewer.zoomTo({{hetflag: true}}); }} else {{ viewer.zoomTo(); }}
  viewer.render();
  viewer.spin('y', 0.5);
}})();""")
                    pse_p = f"<p>{pse_link_html}</p>" if pse_link_html else ""
                    viewer_col = f"<div class='md-side-viewer'><div class='md-3dmol-viewer' id='{div_id}'></div>{pse_p}</div>"

            if not viewer_col and pse_link_html:
                image_links.append(pse_link_html)
            image_col = (f"<div class='md-side-image'><img src='data:image/png;base64,{b64}'>"
                         f"<p>{' &middot; '.join(image_links)}</p></div>")

            contacts_table = "<p><em>No interaction data.</em></p>"
            contacts_csv_link = ""
            if interactions_df is not None:
                tdf = interactions_df[interactions_df["target_id"] == target_id]
                rename_map = {"interaction_type": "Interaction", "prot_restype": "Residue",
                              "prot_resnr": "Number", "prot_chain": "Chain", "distance_A": "Distance"}
                show_cols = [c for c in rename_map if c in tdf.columns]
                if not tdf.empty and show_cols:
                    contacts_df = tdf[show_cols].sort_values("interaction_type").rename(columns=rename_map)
                    contacts_table = contacts_df.to_html(index=False, na_rep="")
                    csv_b64 = base64.b64encode(contacts_df.to_csv(index=False).encode("utf-8")).decode("ascii")
                    contacts_csv_link = (f"<p><a href='data:text/csv;base64,{csv_b64}' "
                                         f"download='boltz_contacts_{target_id}.csv'>Download CSV</a></p>")
            layout_cls = "md-side-by-side md-side-3col" if viewer_col else "md-side-by-side"
            session_cards.append(
                f"<div class='md-card'><h2>{target_id}: binding site</h2>"
                f"<div class='{layout_cls}'>"
                f"{viewer_col}"
                f"{image_col}"
                f"<div class='md-side-table-col'><div class='md-side-table'>{contacts_table}</div>{contacts_csv_link}</div>"
                f"</div></div>"
            )
        if session_cards:
            if total_bytes:
                print(f"BoltzMaker: bundled {total_bytes / 1e6:.1f}MB of PyMOL session(s) into "
                      f"{sessions_dir} (this is why the dashboard is no longer a single file)")
            parts.extend(session_cards)
            if viewer_scripts:
                parts.append(f"<script>{''.join(viewer_scripts)}</script>")

    sse_csv = campaign_dir / "boltz_sse_comparison.csv"
    if sse_csv.exists():
        # Purely additive: compare-sse is a separate, explicitly opt-in command, so this
        # card only appears when its output already exists on disk (the same pattern
        # every other optional card here already follows -- e.g. the PLIP session cards
        # above only appear when boltz_plip/ data exists). analyze() itself never runs
        # compare-sse; re-run it manually, then re-run analyze, to refresh this card.
        from sse_comparison.report import _make_sse_heatmap, _make_sse_shift_chart
        sse_df = pd.read_csv(sse_csv)
        sse_table_html = sse_df.drop(columns=["flagged_residues"], errors="ignore").to_html(index=False, na_rep="")
        parts.append(f"<div class='md-card table-card'><h2>Secondary structure shifts (apo vs holo)</h2>"
                     f"{sse_table_html}<p><a href='boltz_sse_comparison.csv'>Download CSV</a></p></div>")
        sse_charts = []
        sse_bar = _make_sse_shift_chart(sse_df, "chart-sse-shift")
        if sse_bar:
            sse_charts.append(f"<div class='md-card'><h2>Per-motif Ca RMSD</h2>{sse_bar}</div>")
        sse_heat = _make_sse_heatmap(sse_df, "chart-sse-heatmap")
        if sse_heat:
            sse_charts.append(f"<div class='md-card md-card-span2'><h2>Motif x target RMSD</h2>{sse_heat}</div>")
        if sse_charts:
            parts.append(f"<div class='md-chart-grid'>{''.join(sse_charts)}</div>")

    if PLOTLY_JS_PATH.exists():
        plotly_script = f"<script>{PLOTLY_JS_PATH.read_text()}</script>"
    else:
        # Fresh checkouts always have vendor/plotly-2.35.2.min.js committed; this is only
        # a safety net (e.g. a shallow/sparse clone), and it reintroduces the exact
        # htmlpreview-breaking failure mode the vendored copy exists to avoid.
        print("BoltzMaker: WARNING: vendor/plotly-2.35.2.min.js not found -- falling back to "
              "the plotly.js CDN, which is known not to render in some HTML-preview contexts")
        plotly_script = "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>"

    threedmol_script = ""
    if need_3dmol:
        if THREEDMOL_JS_PATH.exists():
            threedmol_script = f"<script>{THREEDMOL_JS_PATH.read_text()}</script>"
        else:
            print("BoltzMaker: WARNING: vendor/3Dmol-2.5.5-min.js not found -- falling back to the 3Dmol.js CDN")
            threedmol_script = "<script src='https://cdn.jsdelivr.net/npm/3dmol@2.5.5/build/3Dmol-min.js'></script>"

    doc = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>BoltzMaker Report | Marc C. Deller</title>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
        "&family=Roboto+Mono:wght@400;500&display=swap' rel='stylesheet'>"
        + plotly_script + threedmol_script
        + f"<style>{_BRAND_CSS}</style></head><body>"
        + _BRAND_HEADER + "<main class='md-main'>" + "".join(parts) + "</main>" + _BRAND_FOOTER
        + f"<script>{_LIGAND_GRID_PAGER_JS}</script>"
        + "</body></html>"
    )
    path.write_text(doc)


# ==========================================================================
# CLI
# ==========================================================================

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="BoltzMaker.py", description="Manage Boltz-2 batch campaigns end-to-end.")
    sub = p.add_subparsers(dest="command")

    fmt = sub.add_parser("format", help="auto-align comments/blank-lines in a boltz_input.md (cosmetic only)")
    fmt.add_argument("md_path", type=Path, help="path to boltz_input.md")
    fmt.add_argument("--check", action="store_true", help="report whether reformatting is needed; exit 1 if so, without writing")

    new = sub.add_parser("new", help="interactively write a new boltz_input.md by answering plain questions")
    new.add_argument("md_path", type=Path, nargs="?", default=Path("boltz_input.md"), help="output path (default boltz_input.md)")

    cs = sub.add_parser("compare-sse", help="compare secondary-structure motif shifts between a "
                         "family's apo reference structure and its predicted holo target(s)")
    cs.add_argument("md_path", type=Path, help="path to boltz_input.md")
    cs.add_argument("--family", type=str, default=None, help="restrict to one Protein family id "
                     "(default: every family with an 'Apo structure:' set)")
    cs.add_argument("--target", type=str, default=None, help="restrict to one target stem "
                     "(default: every target for the selected family)")
    cs.add_argument("--out-dir", type=Path, default=None, help="default: alongside boltz_input.md")
    cs.add_argument("--phi-psi-threshold", type=float, default=30.0, help="degrees; per-residue "
                     "phi/psi delta above this is flagged (default 30)")
    cs.add_argument("--dfg-distance-threshold", type=float, default=8.0, help="angstroms; DFG-Asp to "
                     "catalytic-Lys Ca-Ca distance below this is classified DFG-in (default 8.0)")
    cs.add_argument("--alphac-distance-threshold", type=float, default=10.0, help="angstroms; "
                     "alphaC-Glu to catalytic-Lys Ca-Ca distance below this is classified alphaC-in (default 10.0)")
    cs.add_argument("--no-pymol", action="store_true", help="skip writing .pml session scripts")
    cs.add_argument("--refresh-cache", action="store_true", help="bypass the GPCRdb/KLIFS/PDBe "
                     "disk cache for this run")

    for name in ("generate", "preflight", "run", "analyze", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("md_path", type=Path, help="path to boltz_input.md")
        sp.add_argument("--output-dir", type=Path, default=None, help="override settings.output_dir")
        sp.add_argument("--out-dir", type=Path, default=None, help="boltz predict --out_dir (default ./boltz_output beside the md)")
        sp.add_argument("--workers", type=int, default=2, help="dataloader workers (Boltz's own default; "
                        "each worker can duplicate large in-memory structures for big complexes)")
        sp.add_argument("--accelerator", choices=["auto", "gpu", "cpu"], default="auto")
        sp.add_argument("--limit", type=int, default=None, help="cap how many pending targets `run` submits")
        sp.add_argument("--strict", action="store_true", help="promote preflight WARN to FAIL")
        sp.add_argument("-y", "--yes", action="store_true")
        sp.add_argument("--mps-watermark", type=float, default=1.0, help="PYTORCH_MPS_HIGH_WATERMARK_RATIO -- "
                        "caps MPS memory at this x the device's recommended max, so an oversized complex fails "
                        "fast with a clear OOM instead of swap-thrashing (default 1.0; set higher to allow more "
                        "overcommit, 0 to disable the cap entirely)")
        sp.add_argument("--max-parallel-samples", type=int, default=1, help="boltz --max_parallel_samples "
                        "(default 1 here for Mac memory safety; Boltz's own default is unbounded)")
        sp.add_argument("--recycling-steps", type=int, default=None, help="boltz --recycling_steps passthrough "
                        "(default: Boltz's own default of 3)")
        sp.add_argument("--sampling-steps", type=int, default=None, help="boltz --sampling_steps passthrough "
                        "(default: Boltz's own default of 200)")
        sp.add_argument("--diffusion-samples-affinity", type=int, default=None, help="boltz "
                        "--diffusion_samples_affinity passthrough (default: Boltz's own default of 5)")
        sp.add_argument("--sampling-steps-affinity", type=int, default=None, help="boltz "
                        "--sampling_steps_affinity passthrough (default: Boltz's own default of 200)")
        sp.add_argument("--max-msa-seqs", type=int, default=None, help="boltz --max_msa_seqs passthrough "
                        "(default: Boltz's own default of 8192)")
        sp.add_argument("--memory-warn-tokens", type=int, default=1000, help="preflight WARNs if a target's "
                        "total residue/atom count exceeds this (empirical heuristic, see preflight check)")
        sp.add_argument("--skip-interactions", action="store_true", help="skip cif2plip protein-ligand "
                        "interaction analysis during `analyze`, even if `setup-plip` has been run")
    return p


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print("usage: BoltzMaker.py [setup|setup-plip|new|format|compare-sse|generate|preflight|run|analyze|all] <boltz_input.md> [options]")
        sys.exit(1)

    known = {"format", "new", "compare-sse", "generate", "preflight", "run", "analyze", "all"}
    if argv[0] not in known:
        argv = ["all"] + argv
    args = _build_argparser().parse_args(argv)

    if args.command == "format":
        cmd_format(args.md_path.resolve(), check=args.check)
        return

    if args.command == "new":
        cmd_new(args.md_path.resolve())
        return

    md_path = args.md_path.resolve()
    campaign_dir = md_path.parent
    campaign = parse_md(md_path)

    if args.command == "compare-sse":
        from sse_comparison.cli import run_compare_sse
        run_compare_sse(campaign, campaign_dir, family_id=args.family, target_stem=args.target,
                         out_dir=args.out_dir or campaign_dir, phi_psi_threshold=args.phi_psi_threshold,
                         dfg_distance_threshold=args.dfg_distance_threshold,
                         alphac_distance_threshold=args.alphac_distance_threshold,
                         render_pymol=not args.no_pymol, refresh_cache=args.refresh_cache)
        return

    output_dir = args.output_dir if args.output_dir else Path(campaign.settings.output_dir)
    if not output_dir.is_absolute():
        output_dir = (campaign_dir / output_dir).resolve()
    out_dir = args.out_dir if args.out_dir else (campaign_dir / "boltz_output")
    need_affinity = campaign.settings.predict_affinity

    if args.command in ("generate", "all"):
        manifest = generate_yamls(campaign, output_dir)
        print(f"BoltzMaker: generated {len(manifest)} target YAML(s) in {output_dir}")
    else:
        manifest = load_manifest(output_dir)

    if args.command in ("preflight", "all"):
        ok = run_preflight(manifest, output_dir, campaign, md_path, strict=args.strict,
                            memory_warn_tokens=args.memory_warn_tokens)
        if not ok and args.command == "all":
            print("BoltzMaker: preflight failed, aborting before run.")
            sys.exit(1)

    if args.command in ("run", "all"):
        accelerator = resolve_accelerator(args.accelerator)
        run_boltz(output_dir, out_dir, manifest, args.workers, accelerator, need_affinity, campaign_dir,
                  limit=args.limit, mps_watermark=args.mps_watermark, max_parallel_samples=args.max_parallel_samples,
                  recycling_steps=args.recycling_steps, sampling_steps=args.sampling_steps,
                  diffusion_samples_affinity=args.diffusion_samples_affinity,
                  sampling_steps_affinity=args.sampling_steps_affinity, max_msa_seqs=args.max_msa_seqs)

    if args.command in ("analyze", "all"):
        df = analyze(output_dir, out_dir, campaign_dir, need_affinity, campaign,
                     skip_interactions=args.skip_interactions)
        write_csv(df, campaign_dir / "boltz_summary.csv")
        write_xlsx(df, campaign_dir / "boltz_summary.xlsx")
        write_html(df, campaign_dir / "boltz_dashboard.html", campaign_dir, campaign)
        print(f"BoltzMaker: analysis written to {campaign_dir} "
              "(boltz_summary.csv / .xlsx / boltz_summary_view.csv / boltz_dashboard.html)")


if __name__ == "__main__":
    main()
