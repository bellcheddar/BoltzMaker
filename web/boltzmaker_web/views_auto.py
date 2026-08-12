"""Fully Automated Mode: two steps, Prepare and Analysis.

The split from Stepwise Mode is not cosmetic. Stepwise exposes BoltzMaker's
four non-GPU stages as four independent tools, each taking an upload and
handing back a download; the user is the thing holding the pipeline together.
Fully Automated inverts that -- the server does the configuring and the
interpreting, and the user's machine does the one thing only it can do, which
is run `boltz predict` on a GPU.

That is why the bundle runs the whole `all` pipeline locally rather than just
`run`: once a machine has the pinned environment, `analyze` costs seconds more
and produces the PLIP interactions and compare-sse comparisons that this
droplet would otherwise need its own ~1.5GB .plip_env and a 900-second request
to compute. What comes back is small and already structured, so Analysis is a
reader rather than a compute step.

**Sessions.** Analysis is the only stateful thing in this app. The explorer
serves a structure per target on demand, so the extracted upload has to outlive
the POST that created it -- unlike every other view here, which deletes its
scratch dir in a finally. Sessions therefore live under their own root with
their own TTL, deliberately NOT under scratch/: the systemd cleaner deletes
anything in scratch/ older than 15 minutes, which is correct for a request but
would delete a session out from under someone still reading it.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from pathlib import Path

from flask import (
    Blueprint, Response, current_app, render_template, request, send_file, url_for,
)

from . import bundle, options, results as bmz
from .app import new_scratch_dir, session_root
from .runner import BoltzMakerTimeout, extract_error_message, run_boltzmaker
from .views_new import _parse_form
from .wizard import WizardValidationError, assemble_boltz_input_md

bp = Blueprint("auto", __name__, url_prefix="/auto")

# Long enough to actually read a campaign, short enough that the droplet's disk
# is not a museum. The systemd cleaner sweeps this root on the same schedule.
SESSION_TTL_SECONDS = 2 * 60 * 60

# A token is only ever produced by secrets.token_urlsafe here, so anything not
# matching this is a hand-crafted path, not a typo. Validated before it is ever
# joined to a filesystem path.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
# Target ids come from BoltzMaker's own 5-character chain-id namespace joined
# with a ligand id, so this is generous. Checked against the loaded results as
# well; this is only the cheap first gate before any path is built.
_TARGET_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")


# ===========================================================================
#  Sessions
# ===========================================================================

def _sweep_sessions(root: Path, ttl: int = SESSION_TTL_SECONDS) -> int:
    """Delete sessions past their TTL. Opportunistic -- called on each upload
    rather than on a schedule, so a busy site cleans itself and an idle one
    leaves the systemd timer to do it."""
    cutoff = time.time() - ttl
    removed = 0
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _session_dir(token: str) -> Path | None:
    """Resolve a token to its session directory, or None if the token is
    malformed, unknown or expired. Never raises on user input."""
    if not _TOKEN_RE.match(token or ""):
        return None
    root = session_root(current_app)
    path = (root / token).resolve()
    # Belt and braces over the regex: the resolved path must still be a direct
    # child of the session root.
    if path.parent != root.resolve() or not path.is_dir():
        return None
    if path.stat().st_mtime < time.time() - SESSION_TTL_SECONDS:
        shutil.rmtree(path, ignore_errors=True)
        return None
    return path


# ===========================================================================
#  Overview
# ===========================================================================

# strict_slashes=False so /auto and /auto/ both serve directly. With the default,
# every link to the bare /auto (the landing page's own, and the nav's) costs a 308
# redirect first.
@bp.route("/", strict_slashes=False)
def overview():
    return render_template("auto.html", active="auto")


# ===========================================================================
#  Step 1 -- Prepare
# ===========================================================================

def _render_prepare(**kwargs):
    return render_template(
        "auto_prepare.html", active="prepare",
        option_groups=[(key, title, [o for o in options.RUN_OPTIONS if o.group == key])
                       for key, title in options.GROUP_TITLES.items()],
        **kwargs,
    )


@bp.route("/prepare", methods=["GET", "POST"])
def prepare():
    if request.method == "GET":
        return _render_prepare(defaults=options.defaults())

    campaign_name = (request.form.get("campaign_name") or "").strip() or "campaign"

    try:
        cfg = options.parse_form(request.form)
    except options.OptionError as exc:
        return _render_prepare(defaults=options.defaults(), error=str(exc), form=request.form)

    try:
        predict_affinity, proteins, partners, ligands = _parse_form()
        md_text = assemble_boltz_input_md(predict_affinity, proteins, partners, ligands)
    except WizardValidationError as exc:
        return _render_prepare(defaults=cfg, error=str(exc), form=request.form)

    scratch = new_scratch_dir(current_app)
    try:
        md_path = scratch / "boltz_input.md"
        md_path.write_text(md_text)

        # `format` first: it validates the spec parses and tidies it to the house
        # style, so what ships in the bundle is what BoltzMaker itself would write.
        result = run_boltzmaker("format", md_path)
        if result.returncode != 0:
            return _render_prepare(
                defaults=cfg, error=extract_error_message(result.stderr), form=request.form,
            )

        # Then `generate`, for the target count and, more importantly, to fail here
        # rather than on the user's machine. Preflight is deliberately NOT run: its
        # checks are about the machine that will predict (GPU, boltz CLI, weights
        # cache), and this droplet has none of them, so every answer it gave would be
        # about the wrong computer. The bundle runs preflight where it means something.
        result = run_boltzmaker("generate", md_path)
        if result.returncode != 0:
            return _render_prepare(
                defaults=cfg, error=extract_error_message(result.stderr), form=request.form,
            )

        target_count = _count_targets(scratch)
        final_md = md_path.read_text()
    except BoltzMakerTimeout as exc:
        return _render_prepare(defaults=cfg, error=str(exc), form=request.form)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    config_json = json.dumps({
        "campaign_name": campaign_name,
        "prepared_by": bundle.SITE_URL,
        "run_settings": cfg,
        "cli_args": options.to_cli_args(cfg),
    }, indent=2, sort_keys=True)

    try:
        built = bundle.build(campaign_name, final_md, cfg, target_count, config_json)
    except bundle.BundleError as exc:
        return _render_prepare(defaults=cfg, error=str(exc), form=request.form)

    return Response(
        built.content,
        mimetype="application/x-sh",
        headers={
            "Content-Disposition": f'attachment; filename="{built.filename}"',
            "Content-Length": str(len(built.content)),
        },
    )


def _count_targets(scratch: Path) -> int:
    """How many targets `generate` actually wrote.

    Counting YAML files is the fallback rather than the primary: the manifest is
    what `run` itself iterates, so it is the number that will really be predicted.
    Both are only used to tell the user what to expect, so a disagreement is worth
    resolving toward the manifest rather than erroring.
    """
    manifest = scratch / "boltz_yamls" / ".boltzmaker_manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text())
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                for key in ("targets", "manifest", "entries"):
                    if isinstance(data.get(key), list):
                        return len(data[key])
        except (json.JSONDecodeError, OSError):
            pass
    yaml_dir = scratch / "boltz_yamls"
    if yaml_dir.is_dir():
        return sum(1 for f in yaml_dir.glob("*.yaml"))
    return 0


# ===========================================================================
#  Step 2 -- Analysis
# ===========================================================================

@bp.route("/analysis", methods=["GET", "POST"])
def analysis():
    if request.method == "GET":
        return render_template("auto_analysis.html", active="analysis")

    uploaded = request.files.get("results_file")
    if not uploaded or not uploaded.filename:
        return render_template(
            "auto_analysis.html", active="analysis",
            error="Choose the .bmz results file your bundle wrote.",
        )

    root = session_root(current_app)
    _sweep_sessions(root)

    token = secrets.token_urlsafe(24)
    session = root / token
    session.mkdir(parents=True)
    try:
        raw = session / "upload.bmz"
        uploaded.save(str(raw))

        extracted = session / "campaign"
        extracted.mkdir()
        bmz.extract(raw, extracted)
        loaded = bmz.load(extracted)
    except bmz.BmzError as exc:
        shutil.rmtree(session, ignore_errors=True)
        return render_template("auto_analysis.html", active="analysis", error=str(exc))
    except Exception:
        shutil.rmtree(session, ignore_errors=True)
        raise

    return _render_explorer(token, loaded)


@bp.route("/analysis/<token>")
def analysis_session(token: str):
    """Re-render an existing session, so a refresh or a shared link within the
    TTL does not mean uploading the file again."""
    session = _session_dir(token)
    if session is None:
        return render_template(
            "auto_analysis.html", active="analysis",
            error="That results session has expired or does not exist. Upload the file again.",
        ), 404
    try:
        loaded = bmz.load(session / "campaign")
    except bmz.BmzError as exc:
        return render_template("auto_analysis.html", active="analysis", error=str(exc)), 400
    return _render_explorer(token, loaded)


def _render_explorer(token: str, loaded: bmz.Results):
    return render_template(
        "auto_explorer.html", active="analysis",
        token=token, results=loaded,
        payload=bmz.to_json(loaded),
        low_confidence=bmz.LOW_CONFIDENCE_THRESHOLD,
    )


def _session_asset(token: str, target: str, subdir: str, suffix: str, mimetype: str):
    """Serve one per-target file out of a session.

    Both the token and the target id are validated by pattern before any path is
    built, and the target is then checked against the summary the session
    actually loaded -- so a request can only ever name a file this campaign
    produced, not an arbitrary path that happens to match the regex.
    """
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    if not _TARGET_RE.match(target or ""):
        return Response("bad target id", status=400, mimetype="text/plain")

    try:
        loaded = bmz.load(session / "campaign")
    except bmz.BmzError:
        return Response("session unreadable", status=404, mimetype="text/plain")
    if target not in {t.target_id for t in loaded.targets}:
        return Response("no such target", status=404, mimetype="text/plain")

    path = (session / "campaign" / subdir / f"{target}{suffix}").resolve()
    root = (session / "campaign" / subdir).resolve()
    if path.parent != root or not path.is_file():
        return Response("not found", status=404, mimetype="text/plain")
    # Immutable: a session's contents never change, and the token is already
    # unique per upload, so the URL is safe to cache for as long as it exists.
    return send_file(path, mimetype=mimetype, max_age=SESSION_TTL_SECONDS)


@bp.route("/analysis/<token>/structure/<target>")
def structure(token: str, target: str):
    return _session_asset(token, target, "structures", ".cif", "chemical/x-cif")


@bp.route("/analysis/<token>/image/<target>")
def image(token: str, target: str):
    return _session_asset(token, target, "plip", ".png", "image/png")


@bp.route("/analysis/<token>/summary.csv")
def summary_csv(token: str):
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    path = session / "campaign" / "summary" / "boltz_summary.csv"
    if not path.is_file():
        return Response("not found", status=404, mimetype="text/plain")
    return send_file(path, mimetype="text/csv", as_attachment=True,
                     download_name="boltz_summary.csv")
