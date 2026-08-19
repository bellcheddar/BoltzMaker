"""Re-rendering the data-derived panels of an already-uploaded run.

The risk this tool carries is not that it fails -- it is that it succeeds too
broadly and quietly drops a panel it had no business touching. Most of these
tests are about what must survive it unchanged.
"""

from __future__ import annotations

import importlib.util
import pathlib
import zipfile

import pandas as pd
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def refresher():
    path = REPO_ROOT / "web" / "deploy" / "refresh_run_reports.py"
    spec = importlib.util.spec_from_file_location("refresh_run_reports", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bm(refresher):
    return refresher.load_boltzmaker()


CAMPAIGN_MD = """Settings:
Output folder: ./out
Predict affinity: yes
Pocket distance: 8

Protein: RECP
Sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ
Pocket contact: RECP residue 12 as V6G

Ligand: LIG1
SMILES: CCO
"""

DASHBOARD = (
    "<html><body><main>"
    "<div class='md-card table-card'><h2>Campaign summary</h2>"
    "<table><tr><th>Field</th></tr></table></div>"
    "<div class='md-card table-card'><h2>Summary table</h2>"
    "<table class='full-table'><thead><tr><th>old</th></tr></thead>"
    "<tbody><tr><td>stale</td></tr></tbody></table>"
    "<div class='summary-table-footer'><p><a href='boltz_summary.csv'>Download full CSV</a></p></div>"
    "</div>"
    "<div class='md-card table-card'><h2>Ligand preparation</h2><p>none</p></div>"
    "<div class='md-card'><h2>RECP_LIG1: binding site</h2>"
    "<div class='md-3dmol-viewer' id='v'></div></div>"
    "</main></body></html>"
)


def _bundle(tmp_path, dashboard=DASHBOARD, md=CAMPAIGN_MD):
    path = tmp_path / "run.bmz"
    # family_group, not just family_id: the table substitutes it into family_id's
    # column slot, so a frame carrying only family_id is not a real summary CSV.
    df = pd.DataFrame([{"family_id": "RECP", "family_group": "RECP", "ligand_id": "LIG1",
                        "affinity_probability_binary": 0.3, "pIC50": 7.0},
                       {"family_id": "RECP", "family_group": "RECP", "ligand_id": "LIG2",
                        "affinity_probability_binary": 0.9, "pIC50": 9.0}])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("boltz_input.md", md)
        z.writestr("summary/boltz_summary.csv", df.to_csv(index=False))
        if dashboard is not None:
            z.writestr("reports/boltz_dashboard.html", dashboard)
    return path


def _dashboard_of(path):
    with zipfile.ZipFile(path) as z:
        return z.read("reports/boltz_dashboard.html").decode()


def test_summary_table_is_regenerated(refresher, bm, tmp_path):
    path = _bundle(tmp_path)
    refresher.process(path, bm, dry_run=False)
    assert "stale" not in _dashboard_of(path)


def test_the_footer_and_legend_survive(refresher, bm, tmp_path):
    """They are not derived from the CSV, so rebuilding the whole card would lose them."""
    path = _bundle(tmp_path)
    refresher.process(path, bm, dry_run=False)
    assert "Download full CSV" in _dashboard_of(path)


def test_unrelated_panels_are_untouched(refresher, bm, tmp_path):
    """A panel this cannot rebuild is a panel it must not touch."""
    path = _bundle(tmp_path)
    refresher.process(path, bm, dry_run=False)
    html = _dashboard_of(path)
    assert "RECP_LIG1: binding site" in html and "md-3dmol-viewer" in html
    assert "<h2>Campaign summary</h2>" in html


def test_pockets_panel_lands_above_ligand_preparation(refresher, bm, tmp_path):
    path = _bundle(tmp_path)
    refresher.process(path, bm, dry_run=False)
    html = _dashboard_of(path)
    assert html.index("<h2>Pockets</h2>") < html.index("<h2>Ligand preparation</h2>")


def test_running_twice_does_not_accumulate_panels(refresher, bm, tmp_path):
    path = _bundle(tmp_path)
    refresher.process(path, bm, dry_run=False)
    second = refresher.process(path, bm, dry_run=False)
    assert _dashboard_of(path).count("<h2>Pockets</h2>") == 1
    assert "already current" in second[0]


def test_dry_run_writes_nothing(refresher, bm, tmp_path):
    path = _bundle(tmp_path)
    before = path.read_bytes()
    out = refresher.process(path, bm, dry_run=True)
    assert path.read_bytes() == before and "WOULD" in out[0]


def test_a_bundle_without_a_dashboard_is_skipped(refresher, bm, tmp_path):
    path = _bundle(tmp_path, dashboard=None)
    assert "skipped" in refresher.process(path, bm, dry_run=False)[0]


def test_every_other_entry_is_preserved_byte_for_byte(refresher, bm, tmp_path):
    path = _bundle(tmp_path)
    with zipfile.ZipFile(path) as z:
        before = {n: z.read(n) for n in z.namelist() if n != "reports/boltz_dashboard.html"}
    refresher.process(path, bm, dry_run=False)
    with zipfile.ZipFile(path) as z:
        after = {n: z.read(n) for n in z.namelist() if n != "reports/boltz_dashboard.html"}
    assert after == before


def test_a_backup_is_left_behind(refresher, bm, tmp_path):
    path = _bundle(tmp_path)
    refresher.process(path, bm, dry_run=False)
    assert path.with_suffix(".bmz.before_refresh").is_file()


def test_card_span_counts_nesting(refresher):
    """The first </div> is never the card's -- these cards contain tables and viewers."""
    html = "<div class='md-card'><h2>X</h2><div><div>deep</div></div></div>TAIL"
    start, end = refresher._card_span(html, "X")
    assert html[start:end].endswith("</div>") and html[end:] == "TAIL"
