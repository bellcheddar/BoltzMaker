#!/usr/bin/env python3
"""Re-render the data-derived panels of an already-uploaded run's dashboard.

The analysis page does not build the summary table itself -- it lifts the panels out
of the `boltz_dashboard.html` stored inside each `.bmz`, sanitises them, and reorders
them. So a change to how BoltzMaker *generates* that table (column order, row order, a
new panel) reaches new campaigns only. Runs already sitting under the Runs tab keep
whatever their dashboard said the day it was analysed.

Re-running `analyze` is the obvious fix and is not available here: it needs the whole
result tree -- every CIF, the PLIP output, the PyMOL sessions -- and a bundle carries
only what the web page needs. What a bundle *does* carry is the two inputs these
panels are computed from: `boltz_input.md` and `summary/boltz_summary.csv`. So rather
than regenerate the dashboard, this rewrites only the parts that are a pure function
of those two files, and leaves every other panel byte-for-byte as it was. A panel this
cannot rebuild is a panel it must not touch.

Idempotent: running it twice produces the same archive, because it replaces the table
element wholesale rather than editing it, and it removes an existing Pockets card
before inserting the new one.

    python3 web/deploy/refresh_run_reports.py <bundle.bmz> [...] [--dry-run]
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import re
import shutil
import sys
import types
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARD = "reports/boltz_dashboard.html"


def load_boltzmaker():
    """The generator itself, so the panels here are the ones a fresh analyze writes.

    Reimplementing the table would guarantee the two drift apart -- which is the whole
    problem this script exists to fix, reintroduced one level down.
    """
    source = (REPO_ROOT / "BoltzMaker.py").read_text()
    source = source.replace("_bootstrap_or_relaunch(sys.argv)", "pass  # not relaunching here")
    module = types.ModuleType("boltzmaker_for_refresh")
    module.__file__ = str(REPO_ROOT / "BoltzMaker.py")
    module.__spec__ = importlib.util.spec_from_loader(module.__name__, loader=None)
    sys.modules[module.__name__] = module
    exec(compile(source, str(REPO_ROOT / "BoltzMaker.py"), "exec"), module.__dict__)
    return module


def _card_span(html: str, title: str):
    """(start, end) of the whole `md-card` div whose <h2> is `title`.

    Counts div nesting rather than matching to the first `</div>`: these cards contain
    tables, footers and viewer divs, so the first closing tag is never the card's.
    """
    m = re.search(r"<div class='md-card[^']*'>(?:(?!</div>).)*?<h2>" + re.escape(title) + r"</h2>",
                  html, re.S)
    if not m:
        return None
    i, depth = m.start(), 0
    for tag in re.finditer(r"<div\b|</div>", html[m.start():]):
        depth += 1 if tag.group(0) == "<div" else -1
        if depth == 0:
            return (i, m.start() + tag.end())
    return None


def refresh(html: str, bm, campaign, df) -> tuple:
    """Returns (new_html, [what changed])."""
    changed = []

    span = _card_span(html, "Summary table")
    if span is not None:
        card = html[span[0]:span[1]]
        # Only the <table> is regenerated. The card also holds the CSV download links
        # and the affinity/confidence legend, which are not derived from the CSV and
        # would be lost by rebuilding the card.
        new_card, n = re.subn(r"<table class='full-table'>.*?</table>",
                              bm._build_full_table_html(df), card, count=1, flags=re.S)
        if n:
            html = html[:span[0]] + new_card + html[span[1]:]
            changed.append("summary table re-ranked and regrouped")

    old = _card_span(html, "Pockets")
    if old is not None:                       # idempotence: replace, never accumulate
        html = html[:old[0]] + html[old[1]:]
    pockets = bm._build_pockets_panel_html(campaign)
    if pockets:
        # Above ligand preparation, matching where a fresh dashboard puts it. Falling
        # back through the panels that follow it keeps the position sensible on a
        # dashboard that predates any of them.
        for anchor in ("Ligand preparation", "Ligand structures", "Ranked predicted pIC50"):
            at = _card_span(html, anchor)
            if at is not None:
                html = html[:at[0]] + pockets + html[at[0]:]
                changed.append(f"pockets panel inserted above '{anchor}'")
                break
        else:
            html = html.replace("</main>", pockets + "</main>", 1)
            changed.append("pockets panel appended")
    return html, changed


def process(path: Path, bm, dry_run: bool) -> list:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if DASHBOARD not in names:
            return [f"{path.name}: no dashboard in bundle -- skipped"]
        import pandas as pd
        html = z.read(DASHBOARD).decode("utf-8", "replace")
        campaign = bm.parse_md_text(z.read("boltz_input.md").decode("utf-8", "replace")) \
            if hasattr(bm, "parse_md_text") else None
        if campaign is None:
            tmp = path.with_suffix(".input.tmp.md")
            tmp.write_bytes(z.read("boltz_input.md"))
            try:
                campaign = bm.parse_md(tmp)
            finally:
                tmp.unlink(missing_ok=True)
        df = pd.read_csv(io.BytesIO(z.read("summary/boltz_summary.csv")))
        payload = {n: z.read(n) for n in names}

    new_html, changed = refresh(html, bm, campaign, df)
    if not changed or new_html == html:
        return [f"{path.name}: already current"]
    if dry_run:
        return [f"{path.name}: WOULD {'; '.join(changed)}"]

    shutil.copy2(path, path.with_suffix(".bmz.before_refresh"))
    payload[DASHBOARD] = new_html.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for n in names:                       # original order, so diffs stay readable
            out.writestr(n, payload[n])
    return [f"{path.name}: {'; '.join(changed)}"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundles", nargs="+", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    bm = load_boltzmaker()
    failures = 0
    for path in args.bundles:
        # One malformed bundle must not stop the rest: this runs over every stored run
        # on the server, and stopping halfway would leave the Runs tab showing a mix of
        # refreshed and stale campaigns with nothing saying which was which.
        try:
            lines = process(path, bm, args.dry_run)
        except Exception as exc:                      # noqa: BLE001 -- reported, not swallowed
            failures += 1
            lines = [f"{path.name}: FAILED ({type(exc).__name__}: {exc}) -- left unchanged"]
        for line in lines:
            print(line)
    if failures:
        print(f"{failures} bundle(s) failed and were left as they were")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
