"""Lifting BoltzMaker's panels out of its reports and onto the analysis page.

The reports were framed in an iframe first, which put a scrolling document
inside a card inside the page. Flattening them means their markup is rendered by
this site, from a file a user uploaded -- so the sanitiser is the load-bearing
part here, and most of these tests are about what must NOT survive it.
"""

from __future__ import annotations

import json
import re

import pytest

from boltzmaker_web import reports

DASHBOARD = """
<html><head><style>.x{color:red}</style></head><body>
<header><div class="md-header-inner">chrome that should not come across</div></header>
<main>
  <div class='md-card table-card'><h2>Campaign summary</h2>
    <table><tr><th>Field</th><td>Value</td></tr></table>
  </div>
  <div class='md-chart-grid'>
    <div class='md-card'><h2>Ranked predicted pIC50</h2>
      <div id="chart-pic50" class="plotly-graph-div"></div>
      <script>Plotly.newPlot("chart-pic50", [{"x":[1],"y":[2],"type":"bar"}],
              {"title":"p"}, {"responsive": true})</script>
    </div>
  </div>
  <div class='md-card'><h2>HTR2A_8NU: binding site</h2>
    <div class='md-3dmol-viewer' id='viewer-HTR2A_8NU'></div>
    <script>var v = $3Dmol.createViewer("viewer-HTR2A_8NU"); v.addModel("...");</script>
  </div>
</main>
<footer>more chrome</footer></body></html>
"""


def test_panels_come_across_with_their_titles():
    panels, _ = reports.extract(DASHBOARD)
    titles = [panel.title for panel in panels]
    assert "Campaign summary" in titles
    assert "Ranked predicted pIC50" in titles


def test_the_page_chrome_is_left_behind():
    """Only what is inside <main>. The report has its own header, footer and
    brand bar, and this page already has all three."""
    panels, _ = reports.extract(DASHBOARD)
    joined = " ".join(panel.html for panel in panels)
    assert "chrome that should not come across" not in joined
    assert "more chrome" not in joined


def test_binding_site_panels_are_dropped():
    """This page already gives every target a pose viewer with its interactions
    beside it, and the PyMOL sessions those panels link to are not in the results
    archive."""
    panels, _ = reports.extract(DASHBOARD)
    assert not [p for p in panels if "binding site" in p.title]


def test_charts_come_back_as_data_not_as_code():
    """The three arguments to Plotly.newPlot are JSON. Parsing them and handing
    the page values is what makes this safe: a payload that survives JSON parsing
    and re-serialising is inert text, not a script."""
    _panels, specs = reports.extract(DASHBOARD)
    assert len(specs) == 1
    spec = specs[0]
    assert spec["id"] == "chart-pic50"
    assert spec["data"][0]["type"] == "bar"
    assert spec["layout"]["title"] == "p"
    # It must survive a round trip through JSON, since that is how it reaches the page.
    assert json.loads(json.dumps(spec))["id"] == "chart-pic50"


def test_no_script_survives_from_the_upload():
    panels, _ = reports.extract(DASHBOARD)
    joined = " ".join(panel.html for panel in panels).lower()
    assert "<script" not in joined
    assert "plotly.newplot" not in joined
    assert "$3dmol" not in joined


@pytest.mark.parametrize("hostile,banned", [
    ("<div class='md-card'><h2>T</h2><img src=x onerror='alert(1)'></div>", "onerror"),
    ("<div class='md-card'><h2>T</h2><a href='javascript:alert(1)'>x</a></div>", "javascript:"),
    ("<div class='md-card'><h2>T</h2><script>alert(1)</script></div>", "alert"),
    ("<div class='md-card'><h2>T</h2><iframe src='//evil'></iframe></div>", "<iframe"),
    ("<div class='md-card'><h2>T</h2><svg onload=alert(1)></svg></div>", "onload"),
    ("<div class='md-card'><h2>T</h2><a href=\"data:text/html,<script>\">x</a></div>", "data:text/html"),
])
def test_hostile_markup_does_not_survive(hostile, banned):
    """A results file is user input and this page is served from the site's own
    origin, so anything that could execute has to be gone before it is rendered."""
    panels, _ = reports.extract(f"<main>{hostile}</main>")
    joined = " ".join(panel.html for panel in panels).lower()
    assert banned.lower() not in joined


def test_event_handlers_are_stripped_from_allowed_tags():
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>T</h2>"
        "<td onclick='steal()' class='keep'>cell</td></div></main>")
    html = panels[0].html
    assert "onclick" not in html
    assert 'class="keep"' in html      # the allowed attribute stays
    assert "cell" in html              # and so does the content


def test_a_malformed_chart_call_is_skipped_not_fatal():
    panels, specs = reports.extract(
        "<main><div class='md-card'><h2>T</h2><div id='chart-x'></div>"
        "<script>Plotly.newPlot('chart-x', notJson, )</script></div></main>")
    assert specs == []
    assert panels[0].title == "T"


def test_nested_divs_do_not_truncate_a_panel():
    """A card contains divs of its own, so ending it at the first </div> would cut
    every panel short at its first inner element."""
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>T</h2><div><div>deep</div></div>"
        "<p>last</p></div></main>")
    assert "deep" in panels[0].html
    assert "last" in panels[0].html


def test_it_survives_a_report_with_no_main():
    panels, _ = reports.extract("<div class='md-card'><h2>T</h2><p>x</p></div>")
    assert [p.title for p in panels] == ["T"]


# ===========================================================================
#  Panel order
# ===========================================================================

def _panels(*titles):
    return [reports.Panel(title=title, html="<p>x</p>") for title in titles]


def test_the_campaign_summary_comes_first():
    slots = reports.ordered_slots(_panels("Motif x target RMSD", "Campaign summary"))
    first_report = next(s for s in slots if s["kind"] == "report")
    assert first_report["panel"].title == "Campaign summary"


def test_this_pages_own_panels_are_placed_by_name():
    """Both sequences are one list, so reordering the page is a line moved in
    PANEL_ORDER rather than a template edit."""
    slots = reports.ordered_slots(_panels("Campaign summary", "pIC50 vs confidence score"))
    kinds = [(s["kind"], s.get("which") or s["panel"].title) for s in slots]
    assert kinds == [
        ("report", "Campaign summary"),
        ("own", "targets"),
        ("report", "pIC50 vs confidence score"),
        ("own", "detail"),
    ]


def test_an_unknown_panel_still_appears():
    """A future dashboard may add a panel this order does not name. It should land
    at the end rather than disappear."""
    slots = reports.ordered_slots(_panels("Campaign summary", "Something brand new"))
    titles = [s["panel"].title for s in slots if s["kind"] == "report"]
    assert titles == ["Campaign summary", "Something brand new"]


def test_a_panel_appears_once_even_if_both_reports_carry_it():
    slots = reports.ordered_slots(_panels("Per-motif Ca RMSD", "Per-motif Ca RMSD"))
    titles = [s["panel"].title for s in slots if s["kind"] == "report"]
    assert titles == ["Per-motif Ca RMSD"]


def test_the_combined_secondary_structure_panel_is_dropped():
    """The dashboard stacks the family-coverage and motif tables into one panel;
    the compare-sse page carries both separately plus the overall statistics the
    dashboard leaves out. Keeping the granular three repeats nothing."""
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>Secondary structure shifts (apo vs holo)</h2>"
        "<p>x</p></div>"
        "<div class='md-card'><h2>Family coverage</h2><p>y</p></div></main>")
    assert [p.title for p in panels] == ["Family coverage"]


# ===========================================================================
#  Panel kinds -- what the stylesheet hangs off
# ===========================================================================

def test_a_ligand_panel_is_recognised():
    """The reports carry their own <style>, which is stripped with every other
    style and script, so their class names arrive here unstyled. The kind is what
    lets this page dress them without matching on the title."""
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>Ligand structures</h2>"
        "<div id='lig-grid'><div class='lig-page'><div class='lig-cell'>x</div></div></div>"
        "</div></main>")
    assert panels[0].kind == "ligands"


def test_a_wide_table_is_recognised():
    """Eighteen columns at the normal size wraps every header onto four lines."""
    headers = "".join(f"<th>c{i}</th>" for i in range(18))
    panels, _ = reports.extract(
        f"<main><div class='md-card'><h2>SSE motif shifts</h2>"
        f"<table><tr>{headers}</tr></table></div></main>")
    assert panels[0].kind == "wide-table"


def test_an_ordinary_table_is_not_treated_as_wide():
    headers = "".join(f"<th>c{i}</th>" for i in range(3))
    panels, _ = reports.extract(
        f"<main><div class='md-card'><h2>Family coverage</h2>"
        f"<table><tr>{headers}</tr></table></div></main>")
    assert panels[0].kind == "table"


def test_a_chart_panel_has_no_table_styling_applied():
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>Ranked confidence</h2>"
        "<div id='chart-confidence'></div></div></main>")
    assert panels[0].kind == "plain"


# ===========================================================================
#  Dimensions and icons
# ===========================================================================

def test_inline_dimensions_are_dropped():
    """The report sizes its own containers for its own full-width page. Kept,
    they win: a chart plotted at 420px sat inside a wrapper the report had pinned
    to 260px and spilled across the card below. Every element measured correctly
    except that one wrapper, which is why it took measuring the whole ancestor
    chain to find."""
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>T</h2>"
        "<div style='height:260px; width:100%; background:#fff'>"
        "<div id='chart-x' style='height:260px'></div></div></div></main>")
    html = panels[0].html
    assert "height" not in html
    assert "background:#fff" in html, "other declarations must survive"


def test_the_confidence_and_affinity_icons_survive():
    """Every confidence and affinity cell is marked with a small inline svg. They
    were being dropped wholesale, which removed the column's entire visual
    language and left a legend explaining symbols no longer on the page."""
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>Summary table</h2><table><tr><td>"
        "<span style='color:#00d084'><svg width='14' height='14' viewBox='0 0 24 24'>"
        "<circle cx='12' cy='12' r='9' stroke='currentColor' stroke-width='2'/>"
        "<path d='M12 2 L20 6'/></svg></span></td></tr></table></div></main>")
    html = panels[0].html
    assert "<svg" in html and "<circle" in html and "<path" in html
    assert 'viewBox="0 0 24 24"' in html or 'viewbox="0 0 24 24"' in html


@pytest.mark.parametrize("hostile,banned", [
    ("<svg onload='steal()'><circle r='5'/></svg>", "onload"),
    ("<svg><foreignObject><b>escape</b></foreignObject></svg>", "escape"),
    ("<svg><use href='//evil#x'/></svg>", "evil"),
    ("<svg><animate onbegin='steal()'/></svg>", "onbegin"),
    ("<svg><image href='//evil.png'/></svg>", "evil"),
])
def test_the_dangerous_half_of_svg_is_still_refused(hostile, banned):
    """Allowing the drawing subset must not let the acting part back in:
    foreignObject is how arbitrary HTML re-enters an svg, and use/image can pull
    in an external document."""
    panels, _ = reports.extract(f"<main><div class='md-card'><h2>T</h2>{hostile}</div></main>")
    joined = " ".join(p.html for p in panels).lower()
    assert banned.lower() not in joined


def test_an_image_only_panel_is_marked_as_a_plot():
    """Matplotlib heatmaps arrive as images at whatever aspect their data implies;
    a one-family, one-ligand heatmap is a wide letterbox with a rotated label
    longer than the plot."""
    panels, _ = reports.extract(
        "<main><div class='md-card'><h2>Family x ligand selectivity</h2>"
        "<img src='data:image/png;base64,AAA'></div></main>")
    assert panels[0].kind == "plot"
