from __future__ import annotations

import json
import shutil

from flask import Blueprint, current_app, render_template, request

from .app import new_scratch_dir
from .runner import BoltzMakerTimeout, extract_error_message, run_boltzmaker

bp = Blueprint("preflight", __name__)

# These two checks are meaningless on this server by design -- no GPU, no `boltz`
# package installed (see runner.py's own docstring on why). They always FAIL here,
# correctly, but that's not a verdict on the CAMPAIGN -- it's a statement about this
# server. Filtered out of the "campaign readiness" verdict computed below; still
# rendered in the full table, just visually de-emphasized, so nothing is hidden.
_NOT_APPLICABLE_HOSTED = {"boltz_cli", "gpu"}
_NOT_APPLICABLE_NOTE = (
    "Not applicable to hosted preflight -- this will show PASS when you run "
    "`preflight` locally, right before predicting."
)


def _read_md_from_request() -> str | None:
    uploaded = request.files.get("md_file")
    if uploaded and uploaded.filename:
        return uploaded.read().decode("utf-8", errors="replace")
    text = (request.form.get("md_text") or "").strip()
    return text or None


def _compute_readiness(checks: list[dict]) -> str:
    """Pure filter over the JSON check array, excluding the two hosted-
    environment-only checks -- zero change to run_preflight()'s own CLI
    semantics (that function's `worst` still correctly treats those two as
    blocking for local use, where they should)."""
    relevant = [c for c in checks if c["name"] not in _NOT_APPLICABLE_HOSTED]
    if any(c["status"] == "FAIL" for c in relevant):
        return "FAIL"
    if any(c["status"] == "WARN" for c in relevant):
        return "WARN"
    return "PASS"


@bp.route("/preflight", methods=["GET", "POST"])
def preflight():
    if request.method == "GET":
        return render_template("preflight.html", active="preflight")

    md_text = _read_md_from_request()
    if not md_text:
        return render_template(
            "preflight.html", active="preflight",
            error="Paste a boltz_input.md or upload one.",
        )

    scratch = new_scratch_dir(current_app)
    try:
        md_path = scratch / "boltz_input.md"
        md_path.write_text(md_text)

        gen_result = run_boltzmaker("generate", md_path)
        if gen_result.returncode != 0:
            return render_template(
                "preflight.html", active="preflight",
                error=extract_error_message(gen_result.stderr),
            )

        pf_result = run_boltzmaker("preflight", md_path, "--json")
        if pf_result.returncode not in (0, 1):
            # 0/1 are both legitimate outcomes of a completed preflight (PASS/FAIL);
            # anything else means the subprocess itself errored before finishing.
            return render_template(
                "preflight.html", active="preflight",
                error=extract_error_message(pf_result.stderr),
            )

        try:
            checks = json.loads(pf_result.stdout)
        except json.JSONDecodeError:
            return render_template(
                "preflight.html", active="preflight",
                error="Couldn't parse preflight's output -- please report this.",
            )

        readiness = _compute_readiness(checks)
        return render_template(
            "preflight.html", active="preflight",
            checks=checks, readiness=readiness,
            not_applicable=_NOT_APPLICABLE_HOSTED, not_applicable_note=_NOT_APPLICABLE_NOTE,
        )
    except BoltzMakerTimeout as exc:
        return render_template("preflight.html", active="preflight", error=str(exc))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
