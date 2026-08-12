from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from flask import Blueprint, current_app, render_template, request, send_file

from .app import new_scratch_dir
from .runner import BoltzMakerTimeout, extract_error_message, run_boltzmaker

bp = Blueprint("generate", __name__)


def _read_md_from_request() -> str | None:
    """Accepts either a file upload (`md_file`) or pasted text (`md_text`)."""
    uploaded = request.files.get("md_file")
    if uploaded and uploaded.filename:
        return uploaded.read().decode("utf-8", errors="replace")
    text = (request.form.get("md_text") or "").strip()
    return text or None


@bp.route("/generate", methods=["GET", "POST"])
def generate():
    if request.method == "GET":
        return render_template("generate.html", active="generate")

    md_text = _read_md_from_request()
    if not md_text:
        return render_template(
            "generate.html", active="generate",
            error="Paste a boltz_input.md or upload one.",
        )

    scratch = new_scratch_dir(current_app)
    try:
        md_path = scratch / "boltz_input.md"
        md_path.write_text(md_text)

        result = run_boltzmaker("generate", md_path)
        if result.returncode != 0:
            return render_template(
                "generate.html", active="generate",
                error=extract_error_message(result.stderr),
            )

        yaml_dir = scratch / "boltz_yamls"
        if not yaml_dir.is_dir():
            return render_template(
                "generate.html", active="generate",
                error="generate reported success but boltz_yamls/ wasn't created -- please report this.",
            )

        zip_path = scratch / "boltz_yamls.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(yaml_dir.rglob("*")):
                if f.is_file():
                    zf.write(f, arcname=f.relative_to(scratch))

        # send_file streams from disk -- read it into memory first so the scratch dir
        # can be safely removed in `finally` even though the response body hasn't
        # finished sending yet (Flask's send_file with a BytesIO doesn't need the
        # file to still exist after the call returns).
        data = zip_path.read_bytes()
        import io
        return send_file(
            io.BytesIO(data),
            mimetype="application/zip",
            as_attachment=True,
            download_name="boltz_yamls.zip",
        )
    except BoltzMakerTimeout as exc:
        return render_template("generate.html", active="generate", error=str(exc))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
