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
import zipfile
import math
import re
import secrets
import shutil
import time
from pathlib import Path

from flask import (
    Blueprint, Response, abort, current_app, redirect, render_template, request,
    send_file, send_from_directory, url_for,
)

from . import (alphafold, apo, bundle, options, package,
               reports as report_panels, results as bmz,
               pocket as pocket_finder, runs as runs_archive, sequences, shares)
from .app import REPO_ROOT, WEB_ROOT, new_scratch_dir, runs_root, session_root
from .runner import BoltzMakerTimeout, extract_error_message, run_boltzmaker
from .views_new import _parse_form
from .wizard import WizardValidationError, assemble_boltz_input_md

bp = Blueprint("auto", __name__, url_prefix="/auto")

# Sessions do not expire on a clock. An analysis link should still work tomorrow,
# and a two-hour timer meant a link shared in the morning was dead by lunch for no
# reason the reader could see. What bounds them is space: the oldest are removed
# only when the archive would otherwise outgrow the host, which is a limit with a
# cause rather than an arbitrary countdown.
MAX_SESSIONS = 60
MAX_SESSION_BYTES = 4 * 1024 * 1024 * 1024   # 4GB of extracted uploads

# Still used as the cache lifetime on served session files: the contents of a
# session never change, so this only says how long a browser may reuse them.
SESSION_CACHE_SECONDS = 7 * 24 * 60 * 60

# A token is only ever produced by secrets.token_urlsafe here, so anything not
# matching this is a hand-crafted path, not a typo. Validated before it is ever
# joined to a filesystem path.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
# Target ids come from BoltzMaker's own 5-character chain-id namespace joined
# with a ligand id, so this is generous. Checked against the loaded results as
# well; this is only the cheap first gate before any path is built.
_TARGET_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
# The same grammar the Prepare form validates against. Checked again here
# because this one reaches the filesystem and two external APIs.
_ACCESSION_RE = re.compile(r"^[A-Z0-9]{6,10}$")


# ===========================================================================
#  Sessions
# ===========================================================================

def _directory_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _sweep_sessions(root: Path) -> int:
    """Remove the oldest sessions, but only once the archive is over its limits.

    Nothing is deleted for being old. A session is deleted because keeping it
    would push the host past what it can hold, which is why the newest are the
    ones kept: the limit is space, and the least recently opened is the least
    likely to be missed.
    """
    try:
        sessions = [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return 0

    def touched(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    sessions.sort(key=touched, reverse=True)      # newest first
    sizes = {session: _directory_bytes(session) for session in sessions}

    removed, running = 0, 0
    for index, session in enumerate(sessions):
        running += sizes[session]
        if index >= MAX_SESSIONS or running > MAX_SESSION_BYTES:
            shutil.rmtree(session, ignore_errors=True)
            removed += 1
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
    # Touched so that "oldest" means least recently opened rather than least
    # recently uploaded: a session someone keeps coming back to should be the last
    # thing removed when space runs short.
    try:
        path.touch(exist_ok=True)
    except OSError:
        pass
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

def archiving_allowed() -> tuple[bool, str]:
    """Whether this request may leave a row on the public /runs page.

    The archive gate used to be a single check of the "Keep private" box, which
    trusts every caller to have ticked it. Automated form submissions made while
    testing against the live site did not, and three bundles of a real, private
    campaign were published on /runs and the front page, downloadable by anyone.
    Ticking a box is the wrong place for that guarantee to live.

    So archiving now requires positive evidence that a person submitted the form
    from this site in a browser, and fails closed otherwise. `Sec-Fetch-Site` is
    sent by every current browser on a form POST and by no scripted HTTP client;
    where it is absent we fall back to a same-origin Referer. A browser that
    strips both still gets its bundle -- it simply is not listed, which is the
    safe direction to fail in. `X-BoltzMaker-No-Archive` lets any client opt out
    explicitly, which is what automated tests should send.
    """
    if request.headers.get("X-BoltzMaker-No-Archive"):
        return False, "client sent X-BoltzMaker-No-Archive"
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None:
        if fetch_site == "same-origin":
            return True, ""
        return False, f"Sec-Fetch-Site: {fetch_site}"
    referer = request.headers.get("Referer", "")
    if referer.startswith(request.url_root):
        return True, ""
    return False, "no same-origin Sec-Fetch-Site or Referer (not a browser form submission)"


#: A page state larger than this is not a form, it is someone posting a file at the
#: endpoint. The real thing is a few KB even for a matrix campaign.
_MAX_PAGE_STATE_BYTES = 512 * 1024

#: The member a bundle and its results archive both store the wizard state under.
PAGE_STATE_NAME = "page_state.json"


def _page_state_from(form) -> str:
    """The wizard's serialised state, validated before it goes into a bundle.

    Stored verbatim rather than rebuilt from the parsed campaign, because the point
    is fidelity: the spec has no idea which PDB id a pocket came from, or that a
    checkbox was ticked rather than absent. Checked for shape all the same -- this
    arrives from a browser and ends up in a file other people download.
    """
    raw = (form.get("page_state") or "").strip()
    if not raw or len(raw.encode("utf-8")) > _MAX_PAGE_STATE_BYTES:
        return ""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    # Re-serialised rather than passed through: whatever arrives is now a JSON
    # document this server produced, not a string it forwarded unread.
    return json.dumps(parsed, indent=2, sort_keys=True)


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
        return _render_prepare(defaults=options.defaults(), error=str(exc), form=request.form,
                               error_field=getattr(exc, 'field', ''))

    # compare-sse only runs for families naming an apo structure, so unticking it is
    # what turns the whole apo arrangement off -- no companion predictions, no
    # references, nothing extra to compute.
    compare_sse = not cfg.get("skip_sse")

    try:
        predict_affinity, proteins, partners, ligands = _parse_form()
        use_same_pocket = request.form.get("use_same_pocket") in ("1", "on", "true", "yes")
        raw_distance = (request.form.get("pocket_distance") or "8").strip()
        try:
            pocket_distance = float(raw_distance)
        except ValueError:
            raise WizardValidationError(
                f"Pocket distance: '{raw_distance}' is not a number.", field="pocket_distance")
        if use_same_pocket and not 1.0 <= pocket_distance <= 50.0:
            raise WizardValidationError(
                f"Pocket distance: {raw_distance} A is outside the sensible range of 1-50 A.",
                field="pocket_distance")
        # One entry per rendered protein row; a <select> always posts, so these line
        # up with protein_name[] even when a row is blank.
        # One entry per rendered ligand row; a <select> always posts, so these line up
        # with ligand_name[] even when a row is left blank.
        # Pocket rows repeat inside repeating protein rows, so each carries the
        # ordinal of the protein it belongs to rather than relying on position.
        # Names are read from the same ordinals so a blank protein row cannot shift
        # a pocket onto the wrong protein.
        row_names = request.form.getlist("protein_name[]")
        pockets_by_protein: dict = {}
        for owner, pdb_id, chosen in zip(request.form.getlist("pocket_owner[]"),
                                         request.form.getlist("pocket_pdb[]"),
                                         request.form.getlist("pocket_ligand[]")):
            if not (pdb_id or "").strip() or not (chosen or "").strip():
                continue
            try:
                name = row_names[int(owner)]
            except (ValueError, IndexError):
                continue
            pockets_by_protein.setdefault(name, []).append((pdb_id.strip(), chosen.strip()))
    except WizardValidationError as exc:
        return _render_prepare(defaults=cfg, error=str(exc), form=request.form,
                               error_field=getattr(exc, 'field', ''))

    # Fetch any named experimental apo structures now, while the person who typed
    # the id is still here to correct it. Shipping them in the bundle also means the
    # run never stops to ask the network for something checkable in advance.
    extra_files: dict[str, bytes] = {}
    apo_paths: dict[str, str] = {}
    if compare_sse:
        for protein in proteins:
            if not protein.apo_pdb:
                continue
            try:
                data, extension = apo.fetch(protein.apo_pdb)
            except apo.ApoFetchError as exc:
                return _render_prepare(defaults=cfg, error=str(exc), form=request.form,
                               error_field=getattr(exc, 'field', ''))
            path = apo.reference_path(protein.apo_pdb, extension)
            extra_files[path] = data
            apo_paths[protein.name] = path

            # The apo reference is for compare-sse, which measures what changes
            # between ligand-free and ligand-bound. A structure with a ligand in it is
            # not apo, and comparing holo against holo measures nothing -- a real
            # campaign ran for weeks with 6ln2 (a modulator+Fab complex) and 7dty
            # (peptide-bound) as its "apo" references.
            if extension == "cif":
                bound = pocket_finder.ligand_candidates(data.decode("utf-8", errors="replace"))
                if bound:
                    return _render_prepare(
                        defaults=cfg, form=request.form, error_field="protein_apo_pdb[]",
                        error=f"{protein.name}: {protein.apo_pdb.upper()} is not an apo "
                              f"structure -- it contains {bound[0].code}. The apo reference is "
                              "for the apo-vs-holo comparison, so a bound ligand makes it "
                              "meaningless. Use a ligand-free structure here; the pocket comes "
                              "from a holo structure on the ligand rows.")

    # Each protein's pockets are the sites its ligands are run against, plus an
    # unconstrained baseline. A site is applied to the protein that named it; when the
    # reference was solved on a different protein the contacts are projected through a
    # sequence alignment, which is a hypothesis rather than a reproduction and worth
    # labelling as such in the write-up.
    if use_same_pocket:
        seen_codes: dict = {}
        for protein in proteins:
            for pdb_id, chosen in pockets_by_protein.get(protein.name, []):
                try:
                    data, extension = apo.fetch(pdb_id)
                except apo.ApoFetchError as exc:
                    return _render_prepare(defaults=cfg, form=request.form,
                                           error_field="pocket_pdb[]",
                                           error=f"{protein.name}: {exc}")
                if extension != "cif":
                    return _render_prepare(
                        defaults=cfg, form=request.form, error_field="pocket_pdb[]",
                        error=f"{protein.name}: {pdb_id.upper()} is only available in a format "
                              "the pocket finder cannot read.")
                text = data.decode("utf-8", errors="replace")
                found = pocket_finder.ligand_candidates(text)
                if not found:
                    return _render_prepare(
                        defaults=cfg, form=request.form, error_field="pocket_pdb[]",
                        error=f"{protein.name}: {pdb_id.upper()} contains no ligand, so it is "
                              "an apo structure. A pocket has to come from a holo one.")
                candidate = next((c for c in found if c.key == chosen), None)
                if candidate is None:
                    return _render_prepare(
                        defaults=cfg, form=request.form, error_field="pocket_ligand[]",
                        error=f"{protein.name}: '{chosen}' is not a ligand in "
                              f"{pdb_id.upper()}. Re-pick it from the list.")
                # Target stems are keyed by the ligand code, so two references
                # contributing the same code would overwrite each other's targets.
                previous = seen_codes.get((protein.name, candidate.code))
                if previous and previous != pdb_id.upper():
                    return _render_prepare(
                        defaults=cfg, form=request.form, error_field="pocket_ligand[]",
                        error=f"{protein.name}: two pocket references both use ligand "
                              f"{candidate.code} ({previous} and {pdb_id.upper()}). Target "
                              "names are keyed by that code, so they would collide.")
                seen_codes[(protein.name, candidate.code)] = pdb_id.upper()

                chain = pocket_finder.best_chain_for_sequence(text, protein.sequence)
                if not chain:
                    return _render_prepare(
                        defaults=cfg, form=request.form, error_field="pocket_pdb[]",
                        error=f"{protein.name}: no chain of {pdb_id.upper()} aligns to this "
                              "protein, so its site cannot be placed here.")
                contacts = pocket_finder.contact_residues(text, candidate, pocket_distance, chain)
                positions = pocket_finder.map_to_sequence(text, chain, contacts, protein.sequence)
                if not positions:
                    return _render_prepare(
                        defaults=cfg, form=request.form, error_field="pocket_distance",
                        error=f"{protein.name}: no residues lie within {pocket_distance:g} A of "
                              f"{candidate.code} in {pdb_id.upper()}. Try a larger distance.")
                protein.pockets[candidate.code] = positions
                protein.pocket_pdb, protein.pocket_ligand = pdb_id.upper(), candidate.code

    try:
        md_text = assemble_boltz_input_md(predict_affinity, proteins, partners, ligands,
                                          compare_sse=compare_sse,
                                          apo_reference_paths=apo_paths,
                                          pocket_distance=pocket_distance if use_same_pocket else 0.0)
    except WizardValidationError as exc:
        return _render_prepare(defaults=cfg, error=str(exc), form=request.form,
                               error_field=getattr(exc, 'field', ''))

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
        return _render_prepare(defaults=cfg, error=str(exc), form=request.form,
                               error_field=getattr(exc, 'field', ''))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    # The key exists only when the user asked for privacy, and only inside their
    # own files. Nothing about a private run is written here, so there is nothing
    # to consult later and nothing to leak -- which is precisely why the marker
    # travels in the bundle rather than in a table on this server.
    run_key = runs_archive.new_private_key()
    # Either the user asked for privacy, or the request cannot be shown to have come
    # from a person using this site -- both mean nothing is archived, and the marker
    # travels in the bundle so the results upload is not archived later either.
    may_archive, why_not = archiving_allowed()
    private = bool(cfg.get("keep_private")) or not may_archive
    if not may_archive and not cfg.get("keep_private"):
        current_app.logger.info("not archiving this run: %s", why_not)

    config_json = json.dumps({
        "campaign_name": campaign_name,
        "prepared_by": bundle.SITE_URL,
        "run_settings": cfg,
        "cli_args": options.to_cli_args(cfg),
        "run_key": run_key,
        "private": private,
        # Only the ones actually given. An empty map is the normal case and means
        # the explorer falls back to matching the sequence.
        "uniprot": {**{p.name: p.uniprot for p in proteins if p.uniprot},
                    **{p.name: p.uniprot for p in partners if p.uniprot}},
    }, indent=2, sort_keys=True)

    try:
        built = bundle.build(campaign_name, final_md, cfg, target_count, config_json,
                             run_key=run_key, private=private, extra_files=extra_files,
                             page_state=_page_state_from(request.form))
    except bundle.BundleError as exc:
        return _render_prepare(defaults=cfg, error=str(exc), form=request.form,
                               error_field=getattr(exc, 'field', ''))

    if not private:
        try:
            archive = runs_archive.Archive(runs_root(current_app))
            archive.record_bundle(run_key, campaign_name,
                                  target_count, built.filename, built.content)
        except OSError:
            # A full disk must not cost the user their bundle -- they came here for
            # the download, and the archive is a convenience on top of it.
            current_app.logger.exception("could not archive the bundle")

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

@bp.route("/prepare/page-state", methods=["POST"])
def page_state_from_bundle():
    """Pull the wizard state out of a finished campaign's results file.

    So a campaign can be extended on the page it was built on: upload its .bmz,
    the form comes back exactly as it was, add the new ligands, download a new
    bundle. The alternative is retyping every protein, ligand and pocket, or
    editing boltz_input.md by hand, which is what this whole step exists to avoid.

    Only ever reads one named member, and only after checking its declared size --
    a zip is an archive of whatever its author chose, including a member that
    claims to be small and expands to fill the disk.
    """
    uploaded = request.files.get("results_file")
    if not uploaded or not uploaded.filename:
        return Response('{"error": "no file"}', status=400, mimetype="application/json")
    try:
        with zipfile.ZipFile(uploaded.stream) as archive:
            try:
                info = archive.getinfo(PAGE_STATE_NAME)
            except KeyError:
                return Response(
                    '{"error": "This bundle has no saved page. It was built before the '
                    'wizard started storing one, so the form cannot be restored from it."}',
                    status=404, mimetype="application/json")
            if info.file_size > _MAX_PAGE_STATE_BYTES:
                return Response('{"error": "saved page is implausibly large"}',
                                status=413, mimetype="application/json")
            raw = archive.read(PAGE_STATE_NAME).decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError, ValueError):
        return Response('{"error": "That file is not a readable .bmz."}',
                        status=400, mimetype="application/json")
    try:
        parsed = json.loads(raw)
    except ValueError:
        return Response('{"error": "the saved page inside it is not valid JSON"}',
                        status=422, mimetype="application/json")
    if not isinstance(parsed, dict):
        return Response('{"error": "the saved page inside it is not a form"}',
                        status=422, mimetype="application/json")
    return Response(json.dumps(parsed), mimetype="application/json")


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

        upload_may_archive, upload_why_not = archiving_allowed()
        if loaded.private or not upload_may_archive:
            # Recognised as private from the file itself, or not demonstrably a
            # person uploading through this site. Nothing is archived, and the
            # upload is removed as soon as it has been read -- the explorer serves
            # from the extracted copy, which the session sweep removes.
            if not loaded.private:
                current_app.logger.info("not archiving this upload: %s", upload_why_not)
            raw.unlink(missing_ok=True)
        else:
            try:
                archive = runs_archive.Archive(runs_root(current_app))
                archive.record_results(
                    loaded.run_key or token, loaded.campaign_name, raw, len(loaded.targets),
                )
            except OSError:
                current_app.logger.exception("could not archive the results file")
            raw.unlink(missing_ok=True)
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


def _report_panels(session: Path, loaded: bmz.Results) -> tuple:
    """The generated reports' panels, lifted out to sit on this page.

    Cached beside the extracted campaign: the dashboard is several megabytes and
    the extraction runs over all of it, which is not work to repeat every time
    someone reloads the page or comes back to the session link.
    """
    cache = session / "panels.json"
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text())
            return cached["panels"], cached["charts"], cached["ligands"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass          # regenerate rather than fail on a half-written cache

    # The two reports overlap: the dashboard embeds the compare-sse charts that the
    # compare-sse page also carries, under the SAME element ids. Rendered together
    # that is two divs sharing an id, which is invalid and leaves the second one
    # unreachable -- so only one of each pair would ever draw, silently. Panels are
    # therefore taken once, first report wins, and a later panel is dropped if
    # everything it would draw is already on the page.
    panels, charts = [], []
    seen_charts, seen_titles = set(), set()
    for report in loaded.reports:
        path = session / "campaign" / "reports" / report["name"]
        if not path.is_file():
            continue
        extracted, specs = report_panels.extract(path.read_text(encoding="utf-8", errors="replace"))
        spec_ids = {spec["id"] for spec in specs}
        for panel in extracted:
            panel_charts = set(re.findall(r'id="(chart-[^"]+)"', panel.html)) & spec_ids
            if panel_charts and panel_charts <= seen_charts:
                continue                      # every chart in it is already drawn
            if not panel_charts and panel.title in seen_titles:
                continue                      # a duplicated table or note
            seen_charts |= panel_charts
            seen_titles.add(panel.title)
            panels.append({"title": panel.title, "html": panel.html,
                           "wide": panel.wide, "kind": panel.kind})
        charts.extend(spec for spec in specs if spec["id"] not in
                      {existing["id"] for existing in charts})

    ligands = report_panels.ligand_cells(panels)
    try:
        cache.write_text(json.dumps({"panels": panels, "charts": charts,
                                     "ligands": ligands}))
    except OSError:
        pass
    return panels, charts, ligands


def _render_explorer(token: str, loaded: bmz.Results):
    session = _session_dir(token)
    panels, charts, ligands = _report_panels(session, loaded) if session else ([], [], {})
    slots = report_panels.ordered_slots(report_panels.rebuild_panels(panels))
    return render_template(
        "auto_explorer.html", active="analysis",
        token=token, results=loaded,
        payload=bmz.to_json(loaded),
        low_confidence=bmz.LOW_CONFIDENCE_THRESHOLD,
        slots=slots, nav=report_panels.navigation(slots),
        has_panels=bool(panels), report_charts=json.dumps(charts),
        ligand_cards=json.dumps(ligands),
        counts=bmz.campaign_counts(loaded),
        kpi_fields=bmz.KPI_FIELDS, kpi_labels=bmz.KPI_LABELS,
        kpi_titles=bmz.KPI_TITLES,
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
    return send_file(path, mimetype=mimetype, max_age=SESSION_CACHE_SECONDS)


def _sequence_payload(session: Path, loaded: bmz.Results, target: str) -> dict:
    """The sequence track for one target, and the conservation logo above it.

    Cached beside the extracted campaign for the same reason the panels are: the
    alignment is over every distinct protein in the campaign, and it does not
    change between page loads.

    The logo is aligned across the campaign's DISTINCT proteins, not across a
    family_group. A group here is one receptor in its holo, no-partner and apo
    forms -- the same sequence three times, whose conservation logo would be a
    solid wall saying nothing. Across groups it is 5HT2A against 5HT2B against
    5HT2C, which is the comparison that has something in it.
    """
    cache = session / f"sequence-{target}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    structures = session / "campaign" / "structures"
    chains = sequences.chains_from_cif(structures / f"{target}.cif")
    if not chains:
        return {"chains": [], "logo": [], "columns": []}

    by_id = {t.target_id: t for t in loaded.targets}
    this = by_id.get(target)
    # The receptor, not a partner: the chain named after the target's family. Boltz
    # writes the target protein first, so its position is the fallback.
    proteins = [c for c in chains if c["kind"] == "protein"]
    receptor = next((c for c in proteins if this and c["id"] == this.family_id),
                    proteins[0] if proteins else None)

    # One representative per distinct protein across the campaign, so the same
    # receptor appearing as holo, no-partner and apo is counted once.
    others: dict[str, str] = {}
    for other in loaded.targets:
        path = structures / f"{other.target_id}.cif"
        if not path.is_file():
            continue
        other_chains = sequences.chains_from_cif(path)
        other_proteins = [c for c in other_chains if c["kind"] == "protein"]
        pick = next((c for c in other_proteins if c["id"] == other.family_id),
                    other_proteins[0] if other_proteins else None)
        if pick and pick["letters"] not in others.values():
            others[other.target_id] = pick["letters"]

    logo: list = []
    columns: list = []
    if receptor and len(others) > 1:
        ordered = list(others.values())
        # The selected target's own sequence must be in the set and identifiable,
        # because the track is drawn against it and every column has to map back.
        if receptor["letters"] not in ordered:
            ordered.append(receptor["letters"])
        aligned = sequences.align_to_reference(ordered)
        mine = aligned[ordered.index(receptor["letters"])]
        logo = sequences.logo_columns(aligned)
        # Column index for each residue of the track, so the logo can be drawn in
        # register with it: the alignment has gaps, the track does not.
        position = 0
        for index, letter in enumerate(mine):
            if letter != "-":
                columns.append(index)
                position += 1

    payload = {
        "chains": [{k: c[k] for k in ("id", "letter", "kind")} for c in chains],
        "receptor": receptor["id"] if receptor else "",
        "letter": receptor["letter"] if receptor else "",
        "letters": receptor["letters"] if receptor else "",
        "numbers": receptor["numbers"] if receptor else [],
        "restypes": receptor["restypes"] if receptor else [],
        "logo": logo,
        "columns": columns,
        "aligned_count": len(others),
    }
    # Written here rather than by the route that usually asks for it: the package
    # builder calls this function directly, and a cache that only the route fills
    # meant every package shipped without a single sequence track.
    try:
        cache.write_text(json.dumps(payload))
    except OSError:
        pass
    return payload


def _rmsd_over(fit: dict, core: set, rotation: list, centres: list):
    """This target's RMSD to the reference over the shared region."""
    centre_m, centre_f = centres
    total, count = 0.0, 0
    for index, (_, ref_number) in enumerate(fit["pairs"]):
        if ref_number not in core or index >= len(fit["mobile"]):
            continue
        point = [fit["mobile"][index][i] - centre_m[i] for i in range(3)]
        moved = [sum(rotation[i][j] * point[j] for j in range(3)) + centre_f[i]
                 for i in range(3)]
        target = fit["fixed"][index]
        total += sum((moved[i] - target[i]) ** 2 for i in range(3))
        count += 1
    return math.sqrt(total / count) if count else None


def _as_int(raw: str):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _receptor_of(chains: list, target) -> dict | None:
    proteins = [c for c in chains if c["kind"] == "protein"]
    return next((c for c in proteins if target and c["id"] == target.family_id),
                proteins[0] if proteins else None)


def _centroid_of(cif_text: str) -> list:
    """Mean position of a written-out ligand, or None if it has no atoms."""
    xs = ys = zs = 0.0
    n = 0
    for line in cif_text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            x, y, z = float(parts[10]), float(parts[11]), float(parts[12])
        except ValueError:
            continue
        xs += x; ys += y; zs += z; n += 1
    return None if not n else [round(xs / n, 2), round(ys / n, 2), round(zs / n, 2)]


def _overlay_payload(session: Path, loaded: bmz.Results) -> dict:
    """Every target superposed onto one reference, for the two overlay panes.

    Both panes want the same thing -- all the targets in one frame -- so the
    superposition is done once and each target is written out twice, very small:
    its receptor's CA atoms, and its ligand's atoms. A pane that draws fifteen
    targets then fetches a few hundred KB rather than the fifteen megabytes the
    full complexes would be.

    The reference is the first target that has a structure, so it is the same for
    everyone looking at this campaign and the RMSDs are comparable to each other.

    Every trace is the SAME region of the protein, not each target's own best-
    fitting part. Drawing whole chains put a correctly superposed core inside a
    haze of the parts that were never fitted -- a 5-HT2A N-terminus and ICL3 are
    long, disordered, differ between predictions, and take the picture from 0.8A
    of agreement to 9.8A of spray. Drawing each target's own core instead would
    have every trace covering a different stretch, which is a different way of not
    being comparable. So the region is decided once, in the reference's numbering:
    the residues that most of the fits agreed on.
    """
    cache = session / "overlay.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # The campaign file is the only record of which pockets exist: the manifest
    # keeps the contacts a target used but never the code that names them.
    pocket_codes = pocket_finder.campaign_pocket_codes(loaded.md_text)
    unnamed_pocket = pocket_finder.has_unnamed_pocket(loaded.md_text)

    structures = session / "campaign" / "structures"
    reference = None
    fits = []
    # Targets whose ligand came apart are not predictions. BoltzMaker judges that at
    # analysis time and says so in the flags; repeating the geometry test here would
    # be a second opinion that can disagree with the report the reader is looking at.
    # Their ligands are left out of the overlay panes entirely: a single atom flung
    # 1400A out sets the camera's bounding box and leaves every real pose sub-pixel,
    # which is what made two panes look empty on the first campaign it happened to.
    broken = {t.target_id for t in loaded.targets if "BROKEN_LIGAND_GEOMETRY" in (t.flags or [])}
    for target in loaded.targets:
        path = structures / f"{target.target_id}.cif"
        if not path.is_file():
            continue
        chains = sequences.chains_from_cif(path)
        receptor = _receptor_of(chains, target)
        if not receptor:
            continue
        if reference is None:
            reference = {"id": target.target_id, "chain": receptor}

        mobile, fixed, pairs = sequences.paired_ca(reference["chain"], receptor)
        try:
            rotation, centres, rmsd, kept = alphafold.superpose_core(mobile, fixed)
        except alphafold.AlphaFoldError:
            fits.append({"target": target, "chains": chains, "path": path,
                         "receptor": receptor, "pairs": pairs, "rmsd": None,
                         "kept": [], "matched": len(mobile), "transform": None})
            continue
        fits.append({"target": target, "chains": chains, "path": path,
                     "receptor": receptor, "pairs": pairs, "rmsd": rmsd,
                     "kept": kept, "matched": len(mobile), "mobile": mobile,
                     "fixed": fixed, "transform": (rotation, centres)})

    # The shared region, in the reference's numbering: a residue is in it when at
    # least half the fits kept it. An intersection would be at the mercy of the
    # single worst target; a union would put the disordered parts back.
    votes: dict[int, int] = {}
    fitted = [f for f in fits if f["transform"]]
    for fit in fitted:
        for index in fit["kept"]:
            if index >= len(fit["pairs"]):
                continue
            ref_number = fit["pairs"][index][1]
            if ref_number is not None:
                votes[ref_number] = votes.get(ref_number, 0) + 1
    threshold = max(1, len(fitted) // 2)
    core = {number for number, count in votes.items() if count >= threshold}

    rows = []
    for fit in fits:
        target = fit["target"]
        if not fit["transform"]:
            rows.append({"id": target.target_id, "name": target.display_name,
                         "ligand": target.ligand_id, "rmsd": None,
                         "matched": fit["matched"], "core": 0})
            continue
        rotation, centres = fit["transform"]
        # The shared region translated into this target's own numbering.
        mine = {mine_number for mine_number, ref_number in fit["pairs"]
                if ref_number in core and mine_number is not None}
        # And the RMSD over exactly that region, rather than over this target's
        # own best-fitting part. The panel draws one region for everybody, so the
        # number beside each row has to be the one the picture shows -- and only
        # then are the fifteen numbers measurements of the same thing.
        shared_rmsd = _rmsd_over(fit, core, rotation, centres)
        text = fit["path"].read_text(encoding="utf-8", errors="replace")
        ligand_chains = {c["id"] for c in fit["chains"] if c["kind"] == "ligand"}
        receptor = fit["receptor"]
        wrote_ligand = False
        centroid = None
        try:
            trace = alphafold.transform_subset(
                text, rotation, centres,
                lambda f, c: (f[c["auth_asym_id"]] == receptor["id"]
                              and f[c["label_atom_id"]] == "CA"
                              and _as_int(f[c["auth_seq_id"]]) in mine))
            (session / f"overlay-ca-{target.target_id}.cif").write_text(trace)
            if ligand_chains and target.target_id not in broken:
                ligand = alphafold.transform_subset(
                    text, rotation, centres,
                    lambda f, c: f[c["auth_asym_id"]] in ligand_chains)
                (session / f"overlay-lig-{target.target_id}.cif").write_text(ligand)
                wrote_ligand = True
                centroid = _centroid_of(ligand)
        except (alphafold.AlphaFoldError, OSError):
            continue

        rows.append({
            "id": target.target_id, "name": target.display_name,
            "ligand": target.ligand_id,
            # Which pocket this target was run against, so the pockets pane can
            # colour it to match the row of the table above it -- and the family, so
            # clicking a row of that table can select exactly the targets it counts.
            # The table's Protein column is the family id, so that is what matches.
            "pocket": pocket_finder.group_for(target.target_id, target.family_id,
                                              target.ligand_id, pocket_codes, unnamed_pocket),
            "family": target.family_id,
            "rmsd": None if shared_rmsd is None else round(shared_rmsd, 2),
            "matched": fit["matched"], "core": len(fit["kept"]),
            "shared": len(mine), "has_ligand": wrote_ligand,
            # Where the ligand actually ended up, in the reference's frame. Two panes
            # draw these and both looked broken on the first campaign where the answer
            # was interesting: a third of the ligands landed ~110A away, on the G
            # protein rather than the receptor, so framing everything zoomed out until
            # the ligands were sub-pixel. Reporting the spread turns a viewer that
            # looks empty into the campaign's actual result.
            "centroid": centroid,
            # Said out loud rather than silently omitted: the row still appears in the
            # list, greyed by having no ligand, so the reader can see the target ran
            # and why its pose is not drawn.
            "broken_ligand": target.target_id in broken,
        })

    # Ordered exactly as the Pockets table orders its rows -- named pockets
    # alphabetically, the baseline last -- because that ordering is what assigns
    # each pocket its colour, and a legend that disagrees with the table above it
    # is worse than no legend.
    groups = [g for g in sorted({r["pocket"] for r in rows})
              if g not in (pocket_finder.UNCONSTRAINED, pocket_finder.UNNAMED)]
    groups += [g for g in (pocket_finder.UNNAMED, pocket_finder.UNCONSTRAINED)
               if any(r["pocket"] == g for r in rows)]
    payload = {"reference": reference["id"] if reference else "",
               "shared": len(core), "targets": rows, "pocket_order": groups}
    try:
        cache.write_text(json.dumps(payload))
    except OSError:
        pass
    return payload


def _package_bytes(session: Path, token: str, loaded: bmz.Results) -> bytes:
    panels, charts, ligands = _report_panels(session, loaded)
    slots = report_panels.ordered_slots(report_panels.rebuild_panels(panels))
    markup = render_template(
        "_explorer_panels.html", results=loaded, token="", package=True,
        slots=slots, nav=report_panels.navigation(slots),
        has_panels=bool(panels), low_confidence=bmz.LOW_CONFIDENCE_THRESHOLD,
        # Same context as the live page: this template is rendered from two places,
        # and a variable added for one of them leaves the other rendering an
        # exception into a file nobody opens until they are offline.
        counts=bmz.campaign_counts(loaded),
        kpi_fields=bmz.KPI_FIELDS, kpi_labels=bmz.KPI_LABELS,
        kpi_titles=bmz.KPI_TITLES,
    )
    # The overlay files and the per-target sequence and pocket files are written
    # on demand, so a campaign nobody has scrolled through has none of them yet.
    # Asking for them here means the package holds a working copy rather than one
    # that quietly lacks half its panels.
    _overlay_payload(session, loaded)
    for target in loaded.targets:
        _sequence_payload(session, loaded, target.target_id)
        try:
            pocket(token, target.target_id)
        except Exception:
            pass
    return package.build(session, WEB_ROOT, REPO_ROOT, loaded,
                         bmz.to_json(loaded), markup, json.dumps(charts),
                         json.dumps(ligands))


@bp.route("/analysis/<token>/package.zip")
def package_zip(token: str):
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    try:
        loaded = bmz.load(session / "campaign")
    except bmz.BmzError:
        return Response("session unreadable", status=404, mimetype="text/plain")
    body = _package_bytes(session, token, loaded)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", loaded.campaign_name or "campaign")
    return Response(body, mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}_html.zip"',
    })


@bp.route("/analysis/<token>/destroy", methods=["POST"])
def destroy(token: str):
    """Remove everything this server holds for a campaign.

    Not a GET, and not reachable by following a link: a prefetching browser or a
    link-scanning mail client would otherwise delete somebody's campaign on their
    behalf. The archived bundle and results are removed as well as the session --
    "all data" has to mean all of it or the button is a lie.
    """
    session = _session_dir(token)
    if session is None:
        return Response(json.dumps({"status": "gone"}), mimetype="application/json")
    removed = []
    try:
        loaded = bmz.load(session / "campaign")
        key = loaded.run_key
    except bmz.BmzError:
        key = ""
    if key:
        removed += runs_archive.Archive(runs_root(current_app)).forget(key)
        # Scoped to this campaign's shares. Wiping the whole shares directory would
        # take other campaigns' links down too, which this button does not promise.
        removed += shares.forget_for_run(runs_root(current_app), key)
    shutil.rmtree(session, ignore_errors=True)
    removed.append("session")
    return Response(json.dumps({"status": "destroyed", "removed": removed}),
                    mimetype="application/json")


_PDB_ID_RE = re.compile(r"^[0-9][A-Za-z0-9]{3}$")


@bp.route("/pocket-ligands/<pdb_id>.json")
def pocket_ligands(pdb_id: str):
    """The ligands in a reference structure that could define a pocket.

    Proxied rather than fetched from the browser for the same reasons as the
    UniProt route, and filtered here rather than in the page so the exclusion list
    lives in one place. Waters, ions, buffers, sugars and lipids are dropped
    entirely: a reference whose only heteroatom is cholesterol has no pocket to
    offer, and saying so is more useful than offering the cholesterol.
    """
    pdb_id = (pdb_id or "").strip()
    if not _PDB_ID_RE.match(pdb_id):
        return Response(json.dumps({"error": "That is not a 4-character PDB id."}),
                        mimetype="application/json", status=400)
    try:
        content, extension = apo.fetch(pdb_id)
    except Exception:
        return Response(json.dumps({"error": f"Could not download {pdb_id.upper()} from RCSB."}),
                        mimetype="application/json", status=502)
    if extension != "cif":
        return Response(json.dumps({"error": f"{pdb_id.upper()} is only available in a format "
                                             "this pocket finder cannot read."}),
                        mimetype="application/json", status=415)
    found = pocket_finder.ligand_candidates(content.decode("utf-8", errors="replace"))
    return Response(json.dumps({"pdb_id": pdb_id.upper(),
                                "ligands": [c.to_json() for c in found]}),
                    mimetype="application/json")


@bp.route("/uniprot/<accession>.json")
def uniprot(accession: str):
    """One UniProt entry, for the Prepare form's autofill.

    Proxied rather than fetched from the browser so the accession is validated
    against the same grammar the form validates, and so the page keeps talking
    only to this server.
    """
    accession = (accession or "").strip().upper()
    if not _ACCESSION_RE.match(accession):
        return Response(json.dumps({"error": "That is not a UniProt accession."}),
                        mimetype="application/json", status=400)
    try:
        return Response(json.dumps(alphafold.entry(accession)), mimetype="application/json")
    except alphafold.AlphaFoldError as exc:
        return Response(json.dumps({"error": str(exc)}), mimetype="application/json",
                        status=404)


@bp.route("/analysis/<token>/pocket/<target>.cif")
def pocket(token: str, target: str):
    """The ligand and the residues PLIP found touching it, as their own structure.

    Mol* can only draw sticks over a component, and this build of the viewer
    exports no query language to build a "ligand plus surroundings" component
    with -- modifyByCurrentSelection takes union/subtract/intersect and silently
    does nothing for anything else, which is why the first attempt drew no sticks
    and reported success. A second structure needs no component at all, and the
    coordinates are the same ones, so it lands exactly on top of the first.
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

    cached = session / f"pocket-{target}.cif"
    if not cached.is_file():
        path = session / "campaign" / "structures" / f"{target}.cif"
        if not path.is_file():
            return Response("no structure", status=404, mimetype="text/plain")
        chains = sequences.chains_from_cif(path)
        by_letter = {c["letter"]: c["id"] for c in chains}
        ligands = {c["id"] for c in chains if c["kind"] == "ligand"}
        wanted = set()
        for row in loaded.interactions.get(target, []):
            chain = by_letter.get(row.get("chain"), row.get("chain"))
            if row.get("resnr") is not None:
                wanted.add((chain, row["resnr"]))
        if not wanted and not ligands:
            return Response("nothing in contact", status=404, mimetype="text/plain")

        text = path.read_text(encoding="utf-8", errors="replace")
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        try:
            carved = alphafold.transform_subset(
                text, identity, [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                lambda f, c: (f[c["auth_asym_id"]] in ligands
                              or (f[c["auth_asym_id"]], _as_int(f[c["auth_seq_id"]])) in wanted))
            cached.write_text(carved)
        except (alphafold.AlphaFoldError, OSError) as exc:
            return Response(f"could not carve the pocket: {exc}", status=500,
                            mimetype="text/plain")
    return send_file(cached, mimetype="chemical/x-cif", max_age=SESSION_CACHE_SECONDS)


@bp.route("/analysis/<token>/overlay.json")
def overlay(token: str):
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    try:
        loaded = bmz.load(session / "campaign")
    except bmz.BmzError:
        return Response("session unreadable", status=404, mimetype="text/plain")
    return Response(json.dumps(_overlay_payload(session, loaded)),
                    mimetype="application/json")


@bp.route("/analysis/<token>/overlay/<kind>/<target>.cif")
def overlay_file(token: str, kind: str, target: str):
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    if kind not in ("ca", "lig") or not _TARGET_RE.match(target or ""):
        return Response("bad request", status=400, mimetype="text/plain")
    path = (session / f"overlay-{kind}-{target}.cif").resolve()
    if path.parent != session.resolve() or not path.is_file():
        return Response("not found", status=404, mimetype="text/plain")
    return send_file(path, mimetype="chemical/x-cif", max_age=SESSION_CACHE_SECONDS)


#: AlphaFold's own threshold for a confident residue. Superposing on everything
#: is dominated by the disordered tails a model puts in arbitrary places: for
#: 5-HT2A that is 18.6A over all 471 residues against 2.9A over the 289 confident
#: ones, and the first number describes the tails rather than the protein.
PLDDT_CUTOFF = 70.0


def _alphafold_payload(session: Path, loaded: bmz.Results, target: str,
                       typed: str) -> dict:
    """Resolve, fetch and superpose an AlphaFold model for one target.

    The superposed file is cached in the session, keyed by accession, so toggling
    the overlay off and on again costs nothing and the external services are asked
    once.
    """
    structures = session / "campaign" / "structures"
    chains = sequences.chains_from_cif(structures / f"{target}.cif")
    proteins = [c for c in chains if c["kind"] == "protein"]
    this = {t.target_id: t for t in loaded.targets}.get(target)
    receptor = next((c for c in proteins if this and c["id"] == this.family_id),
                    proteins[0] if proteins else None)
    if not receptor:
        return {"status": "error", "message": "This structure has no protein chain."}

    # Most trustworthy first, and each route is named in the answer: an overlay is
    # a claim that this is the same protein, and the reader should see what it
    # rests on.
    if typed:
        accession, source = typed, "typed here"
    elif loaded.accessions.get(receptor["id"]):
        accession, source = loaded.accessions[receptor["id"]], "from the campaign spec"
    else:
        try:
            accession = alphafold.accession_from_sequence(receptor["letters"])
        except alphafold.AlphaFoldError as exc:
            return {"status": "error", "message": str(exc), "chain": receptor["id"]}
        source = "matched by sequence"

    cached = session / f"alphafold-{target}-{accession}.cif"
    meta = session / f"alphafold-{target}-{accession}.json"
    if cached.is_file() and meta.is_file():
        try:
            payload = json.loads(meta.read_text())
            payload["cached"] = True
            return payload
        except (json.JSONDecodeError, OSError):
            pass

    try:
        url, entry_id = alphafold.model_url(accession)
        model_text = alphafold.fetch_model(url)
    except alphafold.AlphaFoldError as exc:
        return {"status": "error", "message": str(exc), "accession": accession,
                "source": source, "chain": receptor["id"]}

    scratch = session / f"alphafold-{target}-{accession}.raw.cif"
    try:
        scratch.write_text(model_text)
        model_chains = sequences.chains_from_cif(scratch)
    finally:
        scratch.unlink(missing_ok=True)
    model_chain = next((c for c in model_chains if c["kind"] == "protein"), None)
    if not model_chain:
        return {"status": "error", "message": "The AlphaFold file has no protein chain.",
                "accession": accession, "source": source}

    # Confident residues only, and only where both chains agree on the residue.
    keep = {number for number, score in zip(model_chain["numbers"], model_chain["score"])
            if score is None or score >= PLDDT_CUTOFF}
    filtered = dict(model_chain)
    indices = [i for i, number in enumerate(model_chain["numbers"]) if number in keep]
    for key in ("numbers", "restypes", "ca"):
        filtered[key] = [model_chain[key][i] for i in indices]
    mobile, fixed = alphafold.matched_atoms(filtered, receptor)
    try:
        rotation, centres, rmsd = alphafold.superpose(mobile, fixed)
    except alphafold.AlphaFoldError as exc:
        return {"status": "error", "message": str(exc), "accession": accession,
                "source": source}

    try:
        cached.write_text(alphafold.apply_transform(model_text, rotation, centres))
    except (alphafold.AlphaFoldError, OSError) as exc:
        return {"status": "error", "message": str(exc), "accession": accession,
                "source": source}

    payload = {
        "status": "ok",
        "accession": accession,
        "source": source,
        "entry": entry_id,
        "chain": receptor["id"],
        "rmsd": round(rmsd, 2),
        "matched": len(mobile),
        "cutoff": PLDDT_CUTOFF,
        "url": url,
        "file": cached.name,
    }
    try:
        meta.write_text(json.dumps(payload))
    except OSError:
        pass
    return payload


@bp.route("/analysis/<token>/alphafold/<target>.json")
def alphafold_model(token: str, target: str):
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

    typed = (request.args.get("accession") or "").strip().upper()
    if typed and not _ACCESSION_RE.match(typed):
        return Response(json.dumps({"status": "error",
                                    "message": "That is not a UniProt accession."}),
                        mimetype="application/json")
    payload = _alphafold_payload(session, loaded, target, typed)
    return Response(json.dumps(payload), mimetype="application/json")


@bp.route("/analysis/<token>/alphafold/<target>/<accession>.cif")
def alphafold_file(token: str, target: str, accession: str):
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    if not _TARGET_RE.match(target or "") or not _ACCESSION_RE.match(accession or ""):
        return Response("bad request", status=400, mimetype="text/plain")
    path = (session / f"alphafold-{target}-{accession}.cif").resolve()
    if path.parent != session.resolve() or not path.is_file():
        return Response("not found", status=404, mimetype="text/plain")
    return send_file(path, mimetype="chemical/x-cif", max_age=SESSION_CACHE_SECONDS)


@bp.route("/analysis/<token>/sequence/<target>.json")
def sequence(token: str, target: str):
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

    payload = _sequence_payload(session, loaded, target)
    return Response(json.dumps(payload), mimetype="application/json",
                    headers={"Cache-Control": f"private, max-age={SESSION_CACHE_SECONDS}"})


@bp.route("/analysis/<token>/structure/<target>")
def structure(token: str, target: str):
    return _session_asset(token, target, "structures", ".cif", "chemical/x-cif")


@bp.route("/analysis/<token>/image/<target>")
def image(token: str, target: str):
    return _session_asset(token, target, "plip", ".png", "image/png")


# Only the names results.py recognises, so this route can never be asked for an
# arbitrary path inside a session.
_REPORT_NAMES = ("boltz_dashboard.html", "boltz_sse_comparison.html")


@bp.route("/analysis/<token>/report/<name>")
def report(token: str, name: str):
    """Serve a report out of the uploaded results file.

    This is HTML that arrived in someone's upload, served from our own origin, so
    it is treated as hostile even though BoltzMaker generated it: a crafted .bmz
    could otherwise put arbitrary script on boltzmaker.mdeller.com. The response
    carries a sandbox CSP and the page frames it with a `sandbox` attribute that
    withholds allow-same-origin, so its scripts run -- Plotly needs them -- while
    the document sits in an opaque origin with no access to ours.
    """
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    if name not in _REPORT_NAMES:
        return Response("no such report", status=404, mimetype="text/plain")

    path = (session / "campaign" / "reports" / name).resolve()
    root = (session / "campaign" / "reports").resolve()
    if path.parent != root or not path.is_file():
        return Response("not found", status=404, mimetype="text/plain")

    response = send_file(path, mimetype="text/html", max_age=SESSION_CACHE_SECONDS)
    # `sandbox` with no tokens: scripts are allowed by the frame's own sandbox
    # attribute, and this stops the document reaching anything of ours regardless.
    response.headers["Content-Security-Policy"] = "sandbox allow-scripts"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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


# ===========================================================================
#  Runs -- what was kept
# ===========================================================================

share_bp = Blueprint("share", __name__, url_prefix="/share")

SHARE_COOKIE = "bm_share"


@bp.route("/analysis/<token>/share", methods=["POST"])
def share_create(token: str):
    """Host this private campaign's HTML package behind a password.

    POST only, for the same reason Destroy is: a prefetching browser or a
    link-scanning mail client must not be able to publish somebody's private
    campaign by following a link.
    """
    session = _session_dir(token)
    if session is None:
        return Response("session expired", status=404, mimetype="text/plain")
    try:
        loaded = bmz.load(session / "campaign")
    except bmz.BmzError:
        return Response("session unreadable", status=404, mimetype="text/plain")
    if not loaded.private:
        # A public campaign is already on /runs with an explore link; a second,
        # password-gated copy of the same data would only be confusing.
        return Response("this campaign is not private", status=400, mimetype="text/plain")

    package = _package_bytes(session, token, loaded)
    try:
        share, password, revoke_token = shares.create(
            runs_root(current_app), package, loaded.campaign_name or "campaign",
            run_key=loaded.run_key or "")
    except shares.ShareError as exc:
        return render_template("share_created.html", active="analysis", error=str(exc),
                               back_token=token), 507

    return render_template(
        "share_created.html", active="analysis", share=share, password=password,
        share_url=url_for("share.view", token=share.token, _external=True),
        revoke_url=url_for("share.revoke", token=share.token,
                           revoke_token=revoke_token, _external=True),
        back_token=token,
    )


def _authorised(token: str) -> bool:
    return shares.cookie_valid(runs_root(current_app), token,
                               request.cookies.get(f"{SHARE_COOKIE}_{token}", ""))


@share_bp.route("/<token>", methods=["GET", "POST"])
def view(token: str):
    share = shares.get(runs_root(current_app), token)
    if share is None:
        abort(404)
    if _authorised(token):
        return redirect(url_for("share.page", token=token, filename="index.html"))

    error = ""
    if request.method == "POST":
        if share.is_locked:
            error = "Too many attempts. Try again in a few minutes."
        elif shares.verify_password(runs_root(current_app), token, request.form.get("password", "")):
            response = redirect(url_for("share.page", token=token, filename="index.html"))
            value = shares.cookie_value(runs_root(current_app), token)
            response.set_cookie(
                f"{SHARE_COOKIE}_{token}", value or "", httponly=True, samesite="Lax",
                secure=request.url.startswith("https://"), path=f"/share/{token}",
            )
            return response
        else:
            error = "That password is not right."
    # The campaign name is deliberately not shown before the password is accepted.
    return render_template("share_password.html", active=None, token=token, error=error), \
        (200 if request.method == "GET" else 401)


@share_bp.route("/<token>/page/<path:filename>")
def page(token: str, filename: str):
    if shares.get(runs_root(current_app), token) is None:
        abort(404)
    if not _authorised(token):
        return redirect(url_for("share.view", token=token))
    site = shares.site_dir(runs_root(current_app), token)
    if site is None:
        abort(404)
    banner = _superseded_banner(token) if filename == "index.html" else ""
    if banner:
        # Injected at serve time rather than written into the stored package: the
        # package is the campaign as it was, and rewriting it would edit history to
        # announce the future. Only index.html, only when a newer share exists, and
        # only the one insertion -- every other asset is served untouched.
        page_html = (site / filename).read_text(encoding="utf-8", errors="replace")
        marker = "<body>"
        if marker in page_html:
            page_html = page_html.replace(marker, marker + banner, 1)
        else:
            page_html = banner + page_html
        return Response(page_html, mimetype="text/html")
    # send_from_directory refuses to escape the directory it is given, which is
    # what keeps a crafted filename from reading the rest of the disk.
    return send_from_directory(site, filename)


def _superseded_banner(token: str) -> str:
    """A pointer to the current version, for a share that has been replaced.

    The older share keeps its content and its link: someone was given that URL and
    it should keep answering. What it gains is a way forward, resolved through the
    whole chain so a campaign extended three times still costs the reader one click.
    """
    root = runs_root(current_app)
    share = shares.get(root, token)
    if share is None or not share.superseded_by:
        return ""
    newest = shares.newest(root, token)
    if newest == token:
        return ""
    href = url_for("share.view", token=newest)
    return (
        '<div class="md-alert md-alert-info" style="margin:0;border-radius:0;text-align:center">'
        "This campaign has been extended since this report was shared. "
        f'<a href="{href}">Open the current version</a> '
        "&mdash; you will need the password for it. This page stays as it was."
        "</div>"
    )


@share_bp.route("/<token>/supersede/<revoke_token>", methods=["GET", "POST"])
def supersede(token: str, revoke_token: str):
    """Point this share at the one that replaced it.

    Behind the revoke token, and POST to apply, for the same reasons Revoke is:
    this changes what a reader is told, and a link-scanning mail client must not be
    able to do it by following a URL.
    """
    root = runs_root(current_app)
    share = shares.get(root, token)
    if share is None:
        abort(404)
    error = ""
    if request.method == "POST":
        raw = (request.form.get("newer") or "").strip()
        # Accept the whole URL, since that is what the owner has to hand.
        newer = raw.rstrip("/").rsplit("/", 1)[-1] if "/" in raw else raw
        error = shares.supersede(root, token, revoke_token, newer)
        if not error:
            return render_template("share_superseded.html", active=None, share=share,
                                    newer=newer, done=True)
    return render_template("share_superseded.html", active=None, share=share,
                            revoke_token=revoke_token, error=error, done=False)


@share_bp.route("/<token>/revoke/<revoke_token>", methods=["GET", "POST"])
def revoke(token: str, revoke_token: str):
    """GET renders a confirmation; only POST deletes.

    A revoke link ends up in mail clients and chat apps that fetch URLs to build
    previews, and a GET that deletes would let one of them destroy the share
    before its recipient ever saw it.
    """
    share = shares.get(runs_root(current_app), token)
    if request.method == "GET":
        return render_template("share_revoke.html", active=None, token=token,
                               revoke_token=revoke_token, gone=share is None)
    done = shares.revoke(runs_root(current_app), token, revoke_token)
    return render_template("share_revoke.html", active=None, token=token,
                           revoke_token=revoke_token, gone=True, done=done), \
        (200 if done or share is None else 403)


runs_bp = Blueprint("runs", __name__, url_prefix="/runs")


@runs_bp.route("/", strict_slashes=False)
def index():
    archive = runs_archive.Archive(runs_root(current_app))
    entries = [run for run in archive.list() if run.has_bundle or run.has_results]
    return render_template(
        "runs.html", active="runs", runs=entries,
        total_bytes=archive.total_bytes(),
        max_bytes=runs_archive.MAX_TOTAL_BYTES,
        max_runs=runs_archive.MAX_RUNS,
    )


def _archived_file(key: str, kind: str, download_name: str, mimetype: str):
    if not _TOKEN_RE.match(key or "") and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key or ""):
        abort(400)
    archive = runs_archive.Archive(runs_root(current_app))
    run = archive.get(key)
    if run is None:
        abort(404)
    path = archive.path_for(run, kind)
    if path is None:
        abort(404)
    return send_file(path, mimetype=mimetype, as_attachment=True,
                     download_name=download_name)


@runs_bp.route("/<key>/bundle")
def bundle_file(key: str):
    archive = runs_archive.Archive(runs_root(current_app))
    run = archive.get(key)
    name = f"boltzmaker_{bundle.slugify(run.campaign)}.command" if run else "bundle.command"
    return _archived_file(key, "bundle", name, "application/x-sh")


@runs_bp.route("/<key>/results")
def results_file(key: str):
    archive = runs_archive.Archive(runs_root(current_app))
    run = archive.get(key)
    name = f"{bundle.slugify(run.campaign)}.bmz" if run else "results.bmz"
    return _archived_file(key, "results", name, "application/zip")


@runs_bp.route("/<key>/explore")
def explore(key: str):
    """Open an archived results file in the explorer without re-uploading it."""
    archive = runs_archive.Archive(runs_root(current_app))
    run = archive.get(key)
    if run is None:
        abort(404)
    stored = archive.path_for(run, "results")
    if stored is None:
        abort(404)

    root = session_root(current_app)
    _sweep_sessions(root)
    token = secrets.token_urlsafe(24)
    session = root / token
    (session / "campaign").mkdir(parents=True)
    try:
        bmz.extract(stored, session / "campaign")
        loaded = bmz.load(session / "campaign")
    except bmz.BmzError as exc:
        shutil.rmtree(session, ignore_errors=True)
        return render_template("auto_analysis.html", active="analysis", error=str(exc)), 400
    return _render_explorer(token, loaded)
