"""Lift BoltzMaker's generated panels out of its reports, to sit on this page.

The reports were framed in an iframe first, which put a scrolling document inside
a card inside a page -- three nested scroll contexts to read one chart. This
takes the panels out and renders them as siblings of the explorer's own, so the
page is flat and every panel can be reordered or dropped later.

**No script from the upload is executed.** That is the whole difficulty: a
results file is user input, this page is served from the site's own origin, and
inlining a report's `<script>` blocks would put whatever they contain on
boltzmaker.mdeller.com. So the markup is sanitised to a tag allowlist with every
script and event handler removed, and the charts are rebuilt from their data --
each `Plotly.newPlot(id, data, layout, config)` call has its three arguments
JSON-parsed and handed back to the page as data, which the page's own code then
plots. JSON cannot carry behaviour: once parsed and re-serialised, an injected
payload is inert text.

The binding-site panels are dropped rather than sanitised. They exist to show a
3Dmol viewer and a PyMOL session download, and this page already gives every
target a viewer of its own with the interactions beside it -- keeping both would
be the same thing twice, and the session files are not in the results archive.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser

# Tags worth keeping from a report: tables, headings, images, text. Anything not
# named here is dropped along with its attributes.
_ALLOWED_TAGS = {
    "div", "span", "p", "br", "hr", "h2", "h3", "h4", "b", "strong", "i", "em",
    "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "img", "code", "pre", "small", "sup", "sub", "a",
    # A drawing-only subset of SVG. The reports mark every confidence and affinity
    # cell with a small inline icon -- a shield and a target -- and dropping svg
    # wholesale silently removed the column's entire visual language, leaving a
    # legend that explained symbols no longer on the page. What is NOT here is the
    # part of SVG that can act: script, foreignObject, use, image, and the
    # animation elements, all of which stay in _DANGEROUS_CONTENT_TAGS or are
    # simply absent from this list.
    "svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon",
}
# Attributes worth keeping. `style` is allowed because the report uses it for
# table column widths; `on*` handlers never are.
_ALLOWED_ATTRS = {
    "class", "id", "src", "alt", "title", "colspan", "rowspan", "style", "href",
    # Geometry and paint for the icon subset above. None of these can execute; the
    # attributes that can (every on*) are excluded by not being named here.
    "width", "height", "viewbox", "fill", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "stroke-dasharray", "d", "cx", "cy", "r", "rx", "ry",
    "x", "y", "x1", "y1", "x2", "y2", "points", "transform", "opacity",
    "fill-rule", "clip-rule", "aria-hidden",
}

_SCRIPT_RE = re.compile(r"<script\b.*?</script\s*>", re.S | re.I)
_STYLE_RE = re.compile(r"<style\b.*?</style\s*>", re.S | re.I)

# Panels this page already covers better, or that depend on files the results
# archive does not carry.
_DROP_TITLE_PATTERNS = (
    # This page gives every target a pose viewer with its interactions beside it,
    # and the PyMOL sessions these panels link to are not in the archive.
    re.compile(r": binding site$", re.I),
    # The dashboard's combined secondary-structure panel is the family-coverage
    # table and the motif table stacked together, and the compare-sse page carries
    # both separately along with the overall statistics the dashboard omits. Keeping
    # the granular three and dropping the combined one loses nothing and repeats
    # nothing.
    re.compile(r"^Secondary structure shifts", re.I),
)

# The order panels appear in. Titles not listed keep their original order and fall
# in at the end, so a new panel in a future dashboard appears rather than vanishing.
# Two entries are not report panels at all but this page's own, placed by name so
# the whole sequence is legible in one list.
PANEL_ORDER = (
    "Campaign summary",
    "Summary table",
    "@targets",                     # the sortable, filterable target table
    "pIC50 vs confidence score",    # clickable: a point opens its target below
    "@detail",                      # predicted pose, detected interactions, metrics
    "Ligand preparation",
    "Ligand structures",
    "Ranked predicted pIC50",
    "Ranked confidence",
    "Interaction counts by type",
    "pIC50 vs binder probability",
    "Family x ligand selectivity",
    "Family coverage",
    "Overall shift statistics",
    "SSE motif shifts (apo vs holo)",
    "Per-motif Ca RMSD",
    "Motif x target RMSD",
)


def ordered_slots(panels: list) -> list:
    """Interleave this page's own panels with the report's, in PANEL_ORDER.

    Returns a list of slots, each either {"kind": "own", "which": ...} or
    {"kind": "report", "panel": ...}. Reordering the page is then a matter of
    moving a line in PANEL_ORDER rather than editing the template.
    """
    by_title = {}
    for panel in panels:
        by_title.setdefault(panel["title"] if isinstance(panel, dict) else panel.title, panel)

    slots, placed = [], set()
    for entry in PANEL_ORDER:
        if entry.startswith("@"):
            slots.append({"kind": "own", "which": entry[1:]})
        elif entry in by_title:
            slots.append({"kind": "report", "panel": by_title[entry]})
            placed.add(entry)

    for panel in panels:
        title = panel["title"] if isinstance(panel, dict) else panel.title
        if title not in placed:
            slots.append({"kind": "report", "panel": panel})
            placed.add(title)
    return slots

_VOID_TAGS = {"br", "hr", "img"}
# Dropped along with everything inside them. foreignObject is the way arbitrary
# HTML re-enters an SVG, and use/image can pull in an external document, so both
# are refused even though the drawing subset above is allowed.
_DANGEROUS_CONTENT_TAGS = {
    "script", "style", "iframe", "object", "embed", "math",
    "foreignobject", "use", "image", "animate", "animatetransform", "set", "script",
}


@dataclass
class Panel:
    title: str
    html: str
    wide: bool = False
    #: What the panel contains, so the stylesheet can target it without matching
    #: on the title. The reports carry their own <style>, which is stripped along
    #: with every other script and style, so their class names arrive unstyled and
    #: this page has to dress them.
    kind: str = "plain"


# Dimensions the report chose for its own full-width page. Kept, they win over
# whatever this page decides: a chart plotted at 420px sat inside a container the
# report had pinned to 260px and spilled over the card below it -- and because the
# element measured correctly at every level except the one wrapper, the cause was
# invisible until the whole chain was measured.
_DIMENSION_PROPERTIES = ("height", "width", "min-height", "max-height",
                         "min-width", "max-width")


def _strip_dimensions(style: str) -> str:
    kept = []
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        prop = declaration.split(":", 1)[0].strip().lower()
        if prop in _DIMENSION_PROPERTIES:
            continue
        kept.append(declaration.strip())
    return "; ".join(kept)


class _Sanitiser(HTMLParser):
    """Rewrite a fragment down to the allowlist, by tokenising rather than by
    pattern-matching tags.

    The first version of this used a regex for tags, and a crafted attribute
    closed it: `<a href="data:text/html,<script>">` contains a `<` inside its
    quoted value, which no `[^<>]*` tag pattern can span. The regex simply failed
    to match, the text passed through untouched, and the browser -- which does not
    share the regex's opinion about where the tag ended -- parsed it as a tag
    after all. A tokeniser cannot have that disagreement: anything it does not
    recognise as an allowed tag is emitted as escaped text, so it can never
    become markup downstream.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._suppress_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DANGEROUS_CONTENT_TAGS:
            self._suppress_depth += 1
            return
        if self._suppress_depth or tag not in _ALLOWED_TAGS:
            return
        rendered = []
        for name, value in attrs:
            name = (name or "").lower()
            if name not in _ALLOWED_ATTRS or value is None:
                continue      # drops every on* handler, and anything exotic
            if name in ("src", "href"):
                probe = re.sub(r"\s", "", value).lower()
                if probe.startswith(("javascript:", "vbscript:", "data:text/html")):
                    continue
            if name == "style":
                value = _strip_dimensions(value)
                if not value:
                    continue
            rendered.append(f'{name}="{escape(value, quote=True)}"')
        joined = (" " + " ".join(rendered)) if rendered else ""
        self.out.append(f"<{tag}{joined}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS and not self._suppress_depth and tag in _ALLOWED_TAGS:
            self.out.append(f"</{tag}>")

    def handle_endtag(self, tag):
        if tag in _DANGEROUS_CONTENT_TAGS:
            self._suppress_depth = max(0, self._suppress_depth - 1)
            return
        if self._suppress_depth or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._suppress_depth:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        return "".join(self.out)


def _sanitise(fragment: str) -> str:
    parser = _Sanitiser()
    parser.feed(fragment)
    parser.close()
    return parser.result()


def _cards(main_html: str):
    """Yield each md-card block, by walking div nesting rather than matching
    greedily: the cards contain divs of their own, so a regex for the closing tag
    would end the first card at the first inner </div>."""
    for opening in re.finditer(r"<div\s+class=['\"]md-card[^'\"]*['\"]\s*>", main_html):
        start = opening.start()
        depth = 0
        for tag in re.finditer(r"<(/?)div\b[^>]*>", main_html[start:]):
            depth += -1 if tag.group(1) else 1
            if depth == 0:
                yield main_html[start:start + tag.end()]
                break


def _plotly_specs(html: str) -> list:
    """Every Plotly.newPlot call, as data rather than as code.

    The three arguments are JSON. Parsing and re-serialising them is what makes
    this safe: whatever a hostile file put there arrives at the page as inert
    values, not as a script the browser runs.
    """
    specs = []
    for match in re.finditer(r"Plotly\.newPlot\(", html):
        cursor = match.end()
        args, depth, start, in_string, escape, quote = [], 0, cursor, False, False, ""
        for index in range(cursor, min(len(html), cursor + 8_000_000)):
            char = html[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    in_string = False
                continue
            if char in "\"'":
                in_string, quote = True, char
            elif char in "[{(":
                depth += 1
            elif char in "]})":
                if depth == 0:            # the closing paren of newPlot itself
                    args.append(html[start:index].strip())
                    break
                depth -= 1
            elif char == "," and depth == 0:
                args.append(html[start:index].strip())
                start = index + 1
        if len(args) < 3:
            continue
        try:
            div_id = json.loads(args[0])
            data = json.loads(args[1])
            layout = json.loads(args[2])
            config = json.loads(args[3]) if len(args) > 3 else {}
        except (json.JSONDecodeError, ValueError):
            continue                      # not a shape we understand; skip it
        if isinstance(div_id, str) and isinstance(data, list):
            specs.append({"id": div_id, "data": data, "layout": layout, "config": config})
    return specs


def extract(html: str) -> tuple:
    """Return (panels, plotly_specs) from one generated report."""
    lowered = html.lower()
    if "<main" in lowered:
        main_html = html[lowered.index("<main"):lowered.rindex("</main>")]
    else:
        main_html = html

    specs = _plotly_specs(main_html)

    panels = []
    for card in _cards(main_html):
        title_match = re.search(r"<h2[^>]*>(.*?)</h2>", card, re.S)
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
        if any(pattern.search(title) for pattern in _DROP_TITLE_PATTERNS):
            continue
        body = card[title_match.end():] if title_match else card
        body = body.rsplit("</div>", 1)[0]
        html = _sanitise(body)
        if "lig-grid" in html:
            kind = "ligands"
        elif "<img" in html and "<table" not in html:
            # A rendered plot rather than a chart: matplotlib heatmaps arrive as
            # images, at whatever aspect their data implies.
            kind = "plot"
        elif re.search(r"<table", html) and len(re.findall(r"<th\b", html)) >= 12:
            # A wide table: the secondary-structure one runs to eighteen columns.
            kind = "wide-table"
        elif "<table" in html:
            kind = "table"
        else:
            kind = "plain"
        panels.append(Panel(title=title, html=html, kind=kind,
                            wide="md-card-span2" in card))

    kept_ids = {match for panel in panels
                for match in re.findall(r'id="([^"]+)"', panel.html)}
    specs = [spec for spec in specs if spec["id"] in kept_ids]
    return panels, specs
