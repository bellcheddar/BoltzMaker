"""create_app() factory -- what wsgi.py hands to gunicorn, and what a local
dev entrypoint hands to Flask's own dev server. Mirrors AlphaFraud's own
webapp.py factory pattern (see /Users/dellboy/Documents/Vibe_Coding/
AlphaFraud/alphafraud/webapp.py), adapted for this app's four independent,
stateless, upload-accepting tools instead of one DB-backed dashboard.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from flask import Flask, render_template

from . import banner

# 200MB, matching nginx's own client_max_body_size in deploy/nginx-boltzmaker.conf --
# these two MUST stay in sync; a mismatch means one layer accepts what the other
# rejects, producing a confusing raw connection reset instead of Flask's clean 413.
MAX_CONTENT_LENGTH = 200 * 1024 * 1024

# Dedicated scratch root for per-request temp dirs -- never bare /tmp, so disk usage
# here is trivially observable/quota-able separately from the rest of the host.
# Defaults to a local ./scratch/ for dev; overridden via BOLTZMAKER_SCRATCH_ROOT in
# production (set in deploy/boltzmaker-web.service's EnvironmentFile).
WEB_ROOT = Path(__file__).resolve().parent.parent  # web/boltzmaker_web/app.py -> web/
DEFAULT_SCRATCH_ROOT = WEB_ROOT / "scratch"


def create_app() -> Flask:
    # Flask's own default template_folder/static_folder are relative to this package
    # (boltzmaker_web/), but templates/ and static/ live one level up, as siblings of
    # the package -- matching the plan's directory layout (wsgi.py, requirements.txt,
    # deploy/ all live at that same web/ level too) -- so both must be passed explicitly.
    app = Flask(
        __name__,
        template_folder=str(WEB_ROOT / "templates"),
        static_folder=str(WEB_ROOT / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    scratch_root = Path(os.environ.get("BOLTZMAKER_SCRATCH_ROOT", str(DEFAULT_SCRATCH_ROOT)))
    scratch_root.mkdir(parents=True, exist_ok=True)
    app.config["SCRATCH_ROOT"] = scratch_root

    app.jinja_env.globals["SITE_TITLE"] = banner.SITE_TITLE

    from .views_new import bp as new_bp
    from .views_generate import bp as generate_bp
    from .views_preflight import bp as preflight_bp
    from .views_analyze import bp as analyze_bp

    app.register_blueprint(new_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(preflight_bp)
    app.register_blueprint(analyze_bp)

    @app.route("/")
    def index():
        return render_template("index.html", active="index")

    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    @app.errorhandler(413)
    def too_large(_e):
        return render_template(
            "error.html",
            active=None,
            message=f"Upload too large -- the limit is {MAX_CONTENT_LENGTH // (1024 * 1024)}MB.",
        ), 413

    return app


def new_scratch_dir(app: Flask) -> Path:
    """One isolated temp dir per request, under the app's configured scratch
    root (not bare /tmp). Callers MUST wrap their work in try/finally and
    call cleanup_scratch_dir on the way out -- a systemd timer (deploy/
    boltzmaker-scratch-clean.timer) is only the backstop for a SIGKILL'd
    worker skipping that finally, not a substitute for it."""
    return Path(tempfile.mkdtemp(dir=str(app.config["SCRATCH_ROOT"])))
