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

from flask import Flask, abort, render_template, request, send_from_directory, url_for

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
REPO_ROOT = WEB_ROOT.parent

# Allowlisted rather than open: see the /vendor route below.
VENDORED_ASSETS = ("plotly-2.35.2.min.js", "3Dmol-2.5.5-min.js")
DEFAULT_SCRATCH_ROOT = WEB_ROOT / "scratch"
DEFAULT_SESSION_ROOT = WEB_ROOT / "sessions"
DEFAULT_RUNS_ROOT = WEB_ROOT / "runs"


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

    # Analysis sessions live beside scratch, never inside it. The systemd cleaner
    # (deploy/boltzmaker-scratch-clean.service) deletes anything in scratch/ older
    # than 15 minutes, which is right for a per-request temp dir and quite wrong
    # for a session someone is still reading -- putting sessions under scratch/
    # would silently expire the explorer mid-use.
    sessions_root = Path(os.environ.get("BOLTZMAKER_SESSION_ROOT", str(DEFAULT_SESSION_ROOT)))
    sessions_root.mkdir(parents=True, exist_ok=True)
    app.config["SESSION_ROOT"] = sessions_root

    # The Runs archive: bundles and results the user did not mark private. Capped
    # in runs.py -- see the note there about this host's free space.
    runs_root = Path(os.environ.get("BOLTZMAKER_RUNS_ROOT", str(DEFAULT_RUNS_ROOT)))
    runs_root.mkdir(parents=True, exist_ok=True)
    app.config["RUNS_ROOT"] = runs_root

    app.jinja_env.globals["SITE_TITLE"] = banner.SITE_TITLE

    from .views_auto import bp as auto_bp
    from .views_auto import runs_bp
    from .views_auto import share_bp
    from .views_new import bp as new_bp
    from .views_generate import bp as generate_bp
    from .views_preflight import bp as preflight_bp
    from .views_analyze import bp as analyze_bp

    app.register_blueprint(auto_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(share_bp)
    app.register_blueprint(new_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(preflight_bp)
    app.register_blueprint(analyze_bp)

    @app.context_processor
    def _asset_helper():
        """Cache-bust static files by appending their mtime as ?v=.

        nginx serves /static/ as `public, max-age=31536000, immutable`, which
        is a promise that the bytes at a URL never change. base.html was asking
        for a bare /static/css/brand.css, so that promise was a lie: an edited
        stylesheet kept the same URL and every returning visitor stayed on the
        old one for a year, with no way to force it short of renaming the file.
        The mtime in the query string makes the URL change when the file does,
        which is what the immutable header requires to be safe.
        """
        def asset(filename: str) -> str:
            try:
                version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
            except OSError:
                version = 0
            return url_for("static", filename=filename, v=version)
        return {"asset": asset}

    @app.after_request
    def _no_html_caching(response):
        """Make HTML always revalidate -- the other half of asset().

        Versioning the assets only helps if the browser re-reads the page that
        names them. Flask sends no Cache-Control on a rendered template, so
        browsers fall back to heuristic freshness and hold the page, which
        keeps requesting the previous asset URL -- and that one really is
        cached for a year. no-cache means revalidate, not no-store: an
        unchanged page still comes back as a 304.
        """
        if response.mimetype == "text/html":
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.context_processor
    def _nav_mode():
        """Which mode's nav to render, derived from the request path.

        Deriving it here rather than passing `mode=` from every render_template
        call is deliberate: the four stepwise views render their template from
        several branches each (GET, validation error, success), and a mode
        argument missed on any one of those branches would silently drop the
        user out of their mode's chrome on exactly the error paths where
        orientation matters most.
        """
        path = request.path
        if path.startswith("/auto") or path.startswith("/runs"):
            return {"nav_mode": "auto"}
        if path in ("/stepwise", "/new", "/generate", "/preflight", "/analyze"):
            return {"nav_mode": "stepwise"}
        return {"nav_mode": None}

    @app.route("/")
    def index():
        # The most recent handful only. The full table lives at /runs; this is a
        # sign of life -- what the site has actually been used for lately.
        from .runs import Archive
        try:
            # Same filter /runs applies. A destroyed run is tombstoned rather than
            # erased -- the registry is append-only -- so without this the front page
            # kept listing runs that had been removed at the owner's request, with
            # their files already deleted. Removing a run has to remove it from every
            # listing, not from the one that happens to filter.
            recent = [run for run in Archive(Path(app.config["RUNS_ROOT"])).list()
                      if run.has_bundle or run.has_results][:5]
        except OSError:
            recent = []
        return render_template("index.html", active="index", recent_runs=recent)

    @app.route("/stepwise")
    def stepwise():
        return render_template("stepwise.html", active="stepwise")

    @app.route("/vendor/<path:filename>")
    def vendor(filename):
        """Serve the repo's vendored Plotly and 3Dmol builds.

        They already exist at the repo root for BoltzMaker's own offline
        dashboard, so they are served from there rather than copied into
        static/ -- 5MB of duplicated third-party JS in the tree, kept in sync
        by hand, is a worse problem than one extra route. The explorer is the
        only consumer, and the allowlist keeps this from becoming a general
        read primitive over the repo.
        """
        if filename not in VENDORED_ASSETS:
            abort(404)
        path = REPO_ROOT / "vendor" / filename
        if not path.is_file():
            abort(404)
        # Version-pinned filenames that never change, so a long immutable cache
        # is safe and the 4.5MB Plotly build is fetched once per visitor.
        return send_from_directory(path.parent, path.name, max_age=31536000)

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


def runs_root(app: Flask) -> Path:
    return Path(app.config["RUNS_ROOT"])


def session_root(app: Flask) -> Path:
    """Where Analysis sessions live. See create_app on why this is not under
    the scratch root."""
    return Path(app.config["SESSION_ROOT"])


def new_scratch_dir(app: Flask) -> Path:
    """One isolated temp dir per request, under the app's configured scratch
    root (not bare /tmp). Callers MUST wrap their work in try/finally and
    call cleanup_scratch_dir on the way out -- a systemd timer (deploy/
    boltzmaker-scratch-clean.timer) is only the backstop for a SIGKILL'd
    worker skipping that finally, not a substitute for it."""
    return Path(tempfile.mkdtemp(dir=str(app.config["SCRATCH_ROOT"])))
