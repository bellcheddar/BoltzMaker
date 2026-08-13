"""Assemble a self-extracting run bundle from a campaign spec and run settings.

The output is one file: a bash self-extractor carrying a base64 tar.gz payload.
It holds the campaign spec, BoltzMaker.py itself, the pinned environment
lockfile, and the scripts that tie them together.

Three decisions worth stating, because each could have gone the other way:

**One file, not a zip of files.** A zip needs the user to find it, unzip it,
find the script inside, make it executable, and know to run it from a terminal.
The self-extractor is double-clickable on macOS (hence the `.command`
extension) and `bash <file>` everywhere else, and it puts its own contents in a
named directory next to itself.

**The payload is base64, not appended binary.** It costs 33% in size and buys a
file that survives being emailed, put in Drive, or served by something that
decides to be helpful about line endings. A truncated binary payload fails in
baffling ways; a truncated base64 one fails immediately and says so.

**The environment is pinned by shipping pixi.lock, not by solving fresh.** The
lock in this repo is the one BoltzMaker is tested against and it covers both
osx-arm64 and linux-64. Letting the user's machine solve its own would mean the
bundle installs whatever is newest that day, which is exactly the class of
difference that makes a result impossible to reproduce later.
"""

from __future__ import annotations

import base64
import gzip
import io
import re
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import options as opts

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
# web/boltzmaker_web/bundle.py -> web/boltzmaker_web -> web -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SITE_URL = "https://boltzmaker.mdeller.com"

# The .bmz layout pack_results.py.j2 writes and results.py reads. Bump both
# together; results.py refuses a version it does not understand rather than
# guessing at a layout that has moved.
BMZ_VERSION = 1

# Files copied verbatim from the repo into every bundle.
REPO_FILES = ("BoltzMaker.py", "pixi.toml", "pixi.lock")

# Directories copied whole. BoltzMaker.py is not self-contained: it imports
# sse_comparison for compare-sse, and reads the vendored Plotly and 3Dmol builds
# off disk when it writes the dashboard. Shipping only the script produced a
# bundle that ran a 45-minute campaign successfully and then died in `analyze`
# with "ModuleNotFoundError: No module named 'sse_comparison'" -- the worst
# possible place to discover a missing file.
#
# vendor/ is 4.9MB of third-party JavaScript and dominates the bundle size. It
# is included anyway: the whole promise is a self-contained run, and without it
# the offline dashboard cannot embed its own charts.
REPO_DIRS = ("sse_comparison", "vendor")

# Never packed: compiled bytecode is per-interpreter, and the bundle's Python is
# not necessarily the one that produced it.
_SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}

# Guard against a pathological spec turning into a multi-hundred-MB download.
# Real campaigns are tiny here -- the payload is dominated by pixi.lock (~300KB)
# and BoltzMaker.py (~200KB), so anything near this is a bug, not a big campaign.
MAX_BUNDLE_BYTES = 32 * 1024 * 1024

# 1980-01-01T00:00:00Z, the earliest timestamp the zip format can represent.
_ZIP_SAFE_EPOCH = 315532800


class BundleError(ValueError):
    """A bundle could not be built. Message is safe to show the user."""


@dataclass(frozen=True)
class Bundle:
    filename: str
    content: bytes
    manifest: dict[str, Any]

    @property
    def size_human(self) -> str:
        n = float(len(self.content))
        for unit in ("B", "KB", "MB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"


def slugify(name: str) -> str:
    """A filesystem- and shell-safe stem for the campaign's own files.

    Deliberately strict rather than clever: the result becomes a directory name,
    part of a download filename, and a shell word inside the generated script.
    Anything outside [A-Za-z0-9._-] is replaced rather than escaped, so there is
    no quoting question to get wrong later.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("._-")
    return slug[:48] or "campaign"


def _environment() -> Environment:
    # StrictUndefined so a template referencing a context key that was never
    # supplied fails here, at build time, instead of rendering an empty string
    # into a shell script that then does something subtly different on the
    # user's machine.
    return Environment(
        loader=FileSystemLoader(str(RUNTIME_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def build_context(campaign_name: str, cfg: dict[str, Any], target_count: int,
                  run_key: str = "", private: bool = False) -> dict[str, Any]:
    slug = slugify(campaign_name)
    return {
        "campaign_name": campaign_name,
        "campaign_slug": slug,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "site_url": SITE_URL,
        "target_count": target_count,
        "cli_args": opts.to_cli_args(cfg),
        "cli_lines": opts.to_cli_lines(cfg),
        "results_filename": f"{slug}.bmz",
        "bundle_filename": f"boltzmaker_{slug}.command",
        "bmz_version": BMZ_VERSION,
        # Two separate things, deliberately. `run_key` identifies the run and is
        # always present: it is what lets the results file uploaded weeks later be
        # matched to the bundle it came from, so the Runs table shows one row
        # rather than two unrelated ones. `private` is the instruction, carried in
        # the file itself so the site needs no record of its own to honour it --
        # which is the point, since a private run must leave no record.
        "run_key": run_key,
        "private": bool(private),
    }


def _pack(files: dict[str, bytes]) -> bytes:
    """tar.gz the payload deterministically.

    Every member gets a fixed mtime and uid/gid. Two bundles built from the same
    inputs are then byte-identical, which is what makes the checksum in the
    manifest worth anything and lets the tests compare builds directly.
    """
    buf = io.BytesIO()
    # gzip, explicitly, with mtime=0. tarfile's own "w:gz" writes a gzip header
    # containing the current time, so two builds a second apart differed in their
    # first bytes however carefully the tar members were normalised -- which made
    # the determinism this function claims quietly untrue.
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
      with tarfile.open(fileobj=gz, mode="w") as tar:
          for name in sorted(files):
              data = files[name]
              info = tarfile.TarInfo(name=name)
              info.size = len(data)
              # 1980-01-01, not 0. A fixed timestamp is what makes two builds of the
              # same inputs byte-identical, but the epoch is before the earliest date
              # a zip can represent -- and the campaign's own pack_results.py zips
              # these very files at the end of a run, so epoch-dated members made it
              # die with "ZIP does not support timestamps before 1980" after the
              # compute was already done.
              info.mtime = _ZIP_SAFE_EPOCH
              info.uid = info.gid = 0
              info.uname = info.gname = ""
              # The two scripts must arrive executable; the user is told to run
              # ./run_campaign.sh directly, and a 0644 script would stop that.
              info.mode = 0o755 if name.endswith((".sh", ".py")) else 0o644
              tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


_EXTRACTOR = """#!/usr/bin/env bash
# BoltzMaker campaign bundle: {campaign_name}
# Prepared at {site_url} on {created}
#
# Self-extracting. Double-click it on macOS, or run it from a terminal:
#     sh ./{filename}
# It unpacks into ./{slug}/ next to itself and starts the campaign.

# Re-exec under bash when started by a shell that is not bash. This is what makes
# `sh ./{filename}` work everywhere rather than only on macOS: macOS /bin/sh IS
# bash, so it happens to work there, but on most Linux distributions /bin/sh is
# dash, which has no `set -o pipefail` and no BASH_SOURCE -- the script would die
# on its second line with "Illegal option -o pipefail". Everything above this
# point must stay POSIX, so the guard uses [ ] and $0 rather than [[ ]].
if [ -z "${{BASH_VERSION:-}}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
TARGET="$DIR/{slug}"

# GNU coreutils and macOS (FreeBSD) base64 disagree on the decode flag: GNU has
# -d/--decode and no -D, macOS has -D and, on current releases, -d. --decode is
# the only spelling both have always accepted, so it is the one used here.
if [ -e "$TARGET" ]; then
    echo "  $TARGET already exists."
    echo "  Remove it (or move it aside) and run this again -- refusing to overwrite."
    exit 1
fi

mkdir -p "$TARGET"
echo "  unpacking into $TARGET"
if ! sed -n '/^__BOLTZMAKER_PAYLOAD__$/,$p' "${{BASH_SOURCE[0]}}" \\
     | tail -n +2 \\
     | base64 --decode \\
     | tar xzf - -C "$TARGET"; then
    echo "  extraction failed -- this file looks truncated or corrupted." >&2
    echo "  Download it again from {site_url}/auto/prepare" >&2
    rm -rf "$TARGET"
    exit 1
fi

chmod +x "$TARGET/run_campaign.sh" 2>/dev/null || true
echo "  unpacked."
exec bash "$TARGET/run_campaign.sh"

# Nothing below this marker is executed -- it is the tar.gz payload, base64'd.
__BOLTZMAKER_PAYLOAD__
"""


def build(campaign_name: str, md_text: str, cfg: dict[str, Any], target_count: int,
          config_json: str, run_key: str = "", private: bool = False,
          extra_files: dict[str, bytes] = None) -> Bundle:
    """Render every runtime template and assemble the self-extracting bundle.

    `extra_files` carries campaign data that is neither a template nor part of the
    repo -- today, an experimental apo structure fetched for compare-sse. It is
    keyed by the path the spec refers to, so `Apo structure: reference/2rh1.pdb`
    resolves inside the unpacked campaign exactly as written.
    """
    context = build_context(campaign_name, cfg, target_count, run_key, private)
    env = _environment()

    files: dict[str, bytes] = {
        **(extra_files or {}),
        "boltz_input.md": md_text.encode("utf-8"),
        "config.json": config_json.encode("utf-8"),
        "run_campaign.sh": env.get_template("run_campaign.sh.j2").render(**context).encode("utf-8"),
        "pack_results.py": env.get_template("pack_results.py.j2").render(**context).encode("utf-8"),
        "README.md": env.get_template("README.md.j2").render(**context).encode("utf-8"),
    }

    for name in REPO_FILES:
        path = REPO_ROOT / name
        if not path.is_file():
            # A deploy that flattened web/ out of the repo would land here. Say so
            # plainly rather than shipping a bundle missing its own pipeline.
            raise BundleError(
                f"{name} not found at {path} -- the web app is not sitting inside a "
                "BoltzMaker checkout, so the bundle cannot be assembled."
            )
        files[name] = path.read_bytes()

    for dirname in REPO_DIRS:
        root = REPO_ROOT / dirname
        if not root.is_dir():
            raise BundleError(
                f"{dirname}/ not found at {root} -- BoltzMaker.py imports it at "
                "analyze time, so a bundle without it would fail after the run."
            )
        found = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix in _SKIP_SUFFIXES:
                continue
            if _SKIP_DIR_NAMES.intersection(path.relative_to(REPO_ROOT).parts):
                continue
            files[str(path.relative_to(REPO_ROOT))] = path.read_bytes()
            found += 1
        if not found:
            raise BundleError(f"{dirname}/ contains no files to ship -- refusing to build.")

    payload = base64.b64encode(_pack(files))
    slug = context["campaign_slug"]
    filename = context["bundle_filename"]

    header = _EXTRACTOR.format(
        campaign_name=campaign_name, site_url=SITE_URL, created=context["created"],
        slug=slug, filename=filename,
    )

    # Wrap the base64 so no line is pathologically long: some mail systems and
    # copy-paste paths rewrap long lines, and a rewrapped payload still decodes,
    # whereas one arbitrarily broken mid-transfer does not.
    wrapped = b"\n".join(payload[i:i + 76] for i in range(0, len(payload), 76))
    content = header.encode("utf-8") + wrapped + b"\n"

    if len(content) > MAX_BUNDLE_BYTES:
        raise BundleError(
            f"the assembled bundle is {len(content) // 1024 // 1024}MB, over the "
            f"{MAX_BUNDLE_BYTES // 1024 // 1024}MB ceiling -- please report this."
        )

    return Bundle(
        filename=filename,
        content=content,
        manifest={
            "campaign_name": campaign_name,
            "campaign_slug": slug,
            "created": context["created"],
            "target_count": target_count,
            "cli_args": context["cli_args"],
            "results_filename": context["results_filename"],
            "run_key": run_key,
            "private": bool(private),
            "members": sorted(files),
        },
    )


def unpack(content: bytes) -> dict[str, bytes]:
    """Recover the payload from an assembled bundle. Used by the tests, and by
    anyone who wants to inspect a bundle without executing it."""
    marker = b"__BOLTZMAKER_PAYLOAD__\n"
    # The marker appears twice: once in the extractor's own sed expression and
    # once as the real separator. rsplit takes the last, which is the separator.
    if content.count(marker) < 1:
        raise BundleError("not a BoltzMaker bundle: payload marker not found.")
    b64 = content.rsplit(marker, 1)[1]
    raw = base64.b64decode(b64)
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile():
                out[member.name] = tar.extractfile(member).read()
    return out
