from __future__ import annotations

import io
import shutil
import zipfile

from flask import Blueprint, current_app, render_template, request, send_file

from .app import new_scratch_dir
from .runner import BoltzMakerTimeout, extract_error_message, run_boltzmaker
from .uploads import UnsafeZipError, safe_extract

bp = Blueprint("analyze", __name__)


@bp.route("/analyze", methods=["GET", "POST"])
def analyze():
    if request.method == "GET":
        return render_template("analyze.html", active="analyze")

    uploaded = request.files.get("campaign_zip")
    if not uploaded or not uploaded.filename:
        return render_template(
            "analyze.html", active="analyze",
            error="Upload a zip of your local campaign folder "
                  "(boltz_input.md + boltz_yamls/ + boltz_output/).",
        )

    scratch = new_scratch_dir(current_app)
    try:
        zip_path = scratch / "upload.zip"
        uploaded.save(str(zip_path))

        extract_dir = scratch / "campaign"
        extract_dir.mkdir()
        try:
            safe_extract(zip_path, extract_dir)
        except UnsafeZipError as exc:
            return render_template("analyze.html", active="analyze", error=str(exc))

        md_path = extract_dir / "boltz_input.md"
        if not md_path.is_file():
            return render_template(
                "analyze.html", active="analyze",
                error="No boltz_input.md found at the top level of the zip.",
            )

        result = run_boltzmaker("analyze", md_path, "--skip-interactions", "--skip-sse")
        if result.returncode != 0:
            return render_template(
                "analyze.html", active="analyze",
                error=extract_error_message(result.stderr),
            )

        dashboard = extract_dir / "boltz_dashboard.html"
        if not dashboard.is_file():
            return render_template(
                "analyze.html", active="analyze",
                error="analyze reported success but boltz_dashboard.html wasn't created "
                      "-- please report this.",
            )

        # Bundle dashboard + CSV/XLSX + boltz_cif/ into one download; also inline the
        # dashboard's own HTML so the user sees it immediately without a second request.
        zip_out = scratch / "boltz_analysis_results.zip"
        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in ("boltz_summary.csv", "boltz_summary.xlsx", "boltz_dashboard.html"):
                f = extract_dir / name
                if f.is_file():
                    zf.write(f, arcname=name)
            cif_dir = extract_dir / "boltz_cif"
            if cif_dir.is_dir():
                for f in sorted(cif_dir.rglob("*")):
                    if f.is_file():
                        zf.write(f, arcname=f.relative_to(extract_dir))

        dashboard_html = dashboard.read_text(encoding="utf-8", errors="replace")
        zip_bytes = zip_out.read_bytes()

        if request.form.get("download_only") == "1":
            return send_file(
                io.BytesIO(zip_bytes), mimetype="application/zip",
                as_attachment=True, download_name="boltz_analysis_results.zip",
            )

        return render_template(
            "analyze.html", active="analyze",
            dashboard_html=dashboard_html,
        )
    except BoltzMakerTimeout as exc:
        return render_template("analyze.html", active="analyze", error=str(exc))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
