"""Imported dashboard panels have to be styled by the explorer, not by the dashboard.

The explorer takes a panel's markup and drops its <style> block, so any CSS added
to BoltzMaker.py's dashboard has no effect on the hosted page. A heading-spacing
fix made offline looked done and changed nothing on the page people actually read.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).parent.parent / "web"
REPO = Path(__file__).parent.parent


def _brand_css() -> str:
    return (WEB / "static/css/brand.css").read_text()


def test_the_explorer_styles_sub_headings_inside_imported_panels():
    css = _brand_css()
    assert ".md-report-panel h3.md-sub" in css, (
        "without this the panel's own headings fall back to browser defaults")
    assert ".md-report-panel table + h3.md-sub" in css


def test_the_two_renderers_agree_on_the_after_a_table_spacing():
    """One number, two stylesheets. They drift the moment only one is edited."""
    css = _brand_css()
    dashboard = (REPO / "BoltzMaker.py").read_text()

    def after_table(text: str, selector: str) -> str:
        m = re.search(re.escape(selector) + r"\s*\{[^}]*margin-top:\s*([0-9]+)px", text)
        assert m, f"no margin-top found for {selector}"
        return m.group(1)

    assert after_table(css, ".md-report-panel table + h3.md-sub") == \
           after_table(dashboard, ".md-card table + h3")


def test_the_explorer_page_links_the_stylesheet_that_carries_them():
    """A rule in a file the page does not load is not a fix."""
    template = (WEB / "templates").glob("*explor*")
    linked = any("brand.css" in p.read_text() for p in WEB.glob("templates/*.html"))
    assert linked, "brand.css must be linked from the explorer's template chain"
    assert list(template), "explorer template not found"
