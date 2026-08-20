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
    # The dashboard's combined coverage+statistics card. This page builds its own
    # from the compare-sse page's two granular panels (see _merge_coverage_panels),
    # so the report's version would be a third copy of the same two tables. Renaming
    # that card is what un-dropped it: the pattern above no longer matched it.
    re.compile(r"^Family coverage and SSE shifts$", re.I),
)

# The order panels appear in. Titles not listed keep their original order and fall
# in at the end, so a new panel in a future dashboard appears rather than vanishing.
# Two entries are not report panels at all but this page's own, placed by name so
# the whole sequence is legible in one list.
PANEL_ORDER = (
    "Campaign summary",
    "pIC50 vs confidence score",    # clickable: a point opens the target detail
    "pIC50 vs binder probability",  # the other view of the same points
    "Summary table",
    "@targets",                     # the sortable, filterable target table
    "@detail",                      # sits directly under the table it is driven by
    # What each pocket constraint was, and which ligands were run against it. Above
    # ligand preparation for the same reason it is there in the dashboard: it frames
    # every pose below it, and a matrix campaign is unreadable without it.
    "Pockets",
    "Ligand preparation",
    "Ligand structures",
    "Ranked predicted pIC50",
    "Ranked confidence",
    "Interaction counts by type",
    "SSE motif shifts (apo vs holo)",
    "Per-motif Ca RMSD",
    # Both of these summarise what the per-motif chart above shows in detail, so they
    # read after it rather than before. "Family coverage" is the merged card (see
    # _merge_coverage_panels); "Family x ligand selectivity" is folded into the
    # report's own "Selectivity and motif shifts" pair card and is named here only
    # for campaigns whose report predates it.
    "Selectivity and motif shifts",
    "Family x ligand selectivity",
    "Family coverage and SSE shifts",
    "Family coverage",
    "Overall shift statistics",
    "Motif x target RMSD",
)


#: The per-family fingerprint heatmaps. There is one per family and one per
#: family-with-partners, so a campaign of three receptors produces six -- six
#: full-width cards of the same plot is a long scroll for a set meant to be
#: compared, so they are grouped two to a row.
_FINGERPRINT_SUFFIX = "residue interaction fingerprint"

#: Titles for this page's own panels, for the navigation pulldown. The slot's
#: `which` is a code, and "detail" is not what the panel is called.
OWN_TITLES = {"targets": "Targets", "detail": "Target detail"}


def anchor_for(title: str) -> str:
    """A stable id for a panel, from its title.

    Used by the navigation and by nothing else, so it only has to be unique
    within a page and survive a reload -- which rules out an ordinal, since the
    panels a campaign produces depend on what it ran.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return "panel-" + (slug or "untitled")


def _panel_title(panel) -> str:
    return panel["title"] if isinstance(panel, dict) else panel.title


def ordered_slots(panels: list) -> list:
    """Interleave this page's own panels with the report's, in PANEL_ORDER.

    Returns a list of slots, each {"kind": "own", "which": ...},
    {"kind": "report", "panel": ...} or {"kind": "group", "panels": [...]} for a
    run of fingerprints that share a row. Reordering the page is a matter of
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
        title = _panel_title(panel)
        if title not in placed:
            slots.append({"kind": "report", "panel": panel})
            placed.add(title)

    # Consecutive fingerprints become one grouped slot. Grouping here rather than
    # in CSS because they are siblings in the page's flow: no selector can put
    # two of a run of cards side by side and leave the rest full width.
    grouped: list = []
    for slot in slots:
        is_fingerprint = (slot["kind"] == "report"
                          and _panel_title(slot["panel"]).endswith(_FINGERPRINT_SUFFIX))
        if is_fingerprint and grouped and grouped[-1]["kind"] == "group":
            grouped[-1]["panels"].append(slot["panel"])
        elif is_fingerprint:
            grouped.append({"kind": "group", "panels": [slot["panel"]]})
        else:
            grouped.append(slot)

    for slot in grouped:
        if slot["kind"] == "report":
            slot["anchor"] = anchor_for(_panel_title(slot["panel"]))
        elif slot["kind"] == "own":
            slot["anchor"] = anchor_for(OWN_TITLES.get(slot["which"], slot["which"]))
        else:
            slot["anchor"] = anchor_for("residue interaction fingerprints")
    return grouped


def navigation(slots: list) -> list:
    """Title and anchor for every panel on the page, in the order they appear."""
    entries = []
    for slot in slots:
        if slot["kind"] == "own":
            title = OWN_TITLES.get(slot["which"], slot["which"].title())
        elif slot["kind"] == "group":
            title = "Residue interaction fingerprints"
        else:
            title = _panel_title(slot["panel"])
        entries.append({"title": title, "anchor": slot["anchor"]})
    return entries

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


_LEGEND_RE = re.compile(r'<div class="summary-legend">(.*?)</div>', re.S)
_LEGEND_TITLE_RE = re.compile(r'<span class="legend-title">(.*?)</span>', re.S)


def _legend_items(body: str) -> list:
    """Each legend-item span, walked rather than pattern-matched.

    An item is `<span class="legend-item"><span style=..>icon</span> text</span>`,
    so a regex ending at "</span></span>" never matches: the two closers have the
    label between them. Nesting has to be counted, exactly as the cards are.
    """
    items = []
    for opening in re.finditer(r'<span class="legend-item">', body):
        start = opening.start()
        depth = 0
        for tag in re.finditer(r"<(/?)span\b[^>]*>", body[start:]):
            depth += -1 if tag.group(1) else 1
            if depth == 0:
                items.append(body[start:start + tag.end()])
                break
    return items


def _regroup_legend(html: str) -> str:
    """Split the summary table's legend into its two real groups.

    The report emits one flat row: a title reading "affinity . confidence:" and
    then six items -- three describing the affinity icon and three describing the
    confidence icon, with nothing to say which is which. Read left to right it is
    six unrelated phrases under a heading naming two things.

    They are separable without guessing: the affinity icon is a target drawn from
    concentric circles, the confidence icon is a shield drawn from a path. Items
    are grouped by which they contain, and the title's own two halves become the
    two group labels. If they do not split cleanly -- a future dashboard drawing
    both with the same primitive, say -- the legend is left exactly as it was.
    """
    match = _LEGEND_RE.search(html)
    if not match:
        return html
    body = match.group(1)

    title_match = _LEGEND_TITLE_RE.search(body)
    items = _legend_items(body)
    if not title_match or len(items) < 2:
        return html

    labels = [part.strip().rstrip(":") for part in title_match.group(1).split("\u00b7")]
    if len(labels) != 2:
        return html

    targets = [item for item in items if "<circle" in item and "<path" not in item]
    shields = [item for item in items if "<path" in item]
    if not targets or not shields or len(targets) + len(shields) != len(items):
        return html

    def group(label: str, members: list) -> str:
        return ('<div class="legend-group">'
                f'<span class="legend-title">{label}</span>'
                + "".join(members) + "</div>")

    rebuilt = ('<div class="summary-legend">'
               + group(labels[0], targets) + group(labels[1], shields)
               + "</div>")
    return html[:match.start()] + rebuilt + html[match.end():]


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
        html = _regroup_legend(_sanitise(body))
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


_LIG_CELL_RE = re.compile(r'<div class="lig-cell[^"]*">')
_LIG_NAME_RE = re.compile(r'<div class="lig-cell-header">\s*<span>([^<]+)</span>', re.S)


def ligand_cells(panels: list) -> dict:
    """This campaign's ligand depictions, by ligand id.

    The report draws them as a paginated grid; the detail panel wants one of them
    beside the target it belongs to. Same markup, already through the sanitiser,
    lifted out rather than re-rendered -- there is no chemistry toolkit in this
    venv to redraw a structure with.

    Walked rather than matched, for the third time in this file. A lig-cell holds
    a header div, an img and a badge div, so a regex ending at "</div>" stops at
    the header and returns a card with no structure in it.
    """
    cells = {}
    for panel in panels:
        if panel.get("title") != "Ligand structures":
            continue
        html = panel.get("html", "")
        for opening in _LIG_CELL_RE.finditer(html):
            start = opening.start()
            depth = 0
            for tag in re.finditer(r"<(/?)div\b[^>]*>", html[start:]):
                depth += -1 if tag.group(1) else 1
                if depth == 0:
                    cell = html[start:start + tag.end()]
                    name = _LIG_NAME_RE.search(cell)
                    if name:
                        cells.setdefault(name.group(1).strip(), cell)
                    break
    return cells

#: Panels this page rebuilds rather than replays, and the markup it puts in their
#: place. The report's own version is a flat image or one chart where the page
#: wants two, and neither can be fixed by styling what it sent.
_REBUILT_PANELS = {
    # Drawn as a PNG by the report, so a cell's value could only be read off its
    # colour. The same pivot is in the payload, and a heatmap can be hovered.
    "Family x ligand selectivity": '<div id="chart-selectivity"></div>',
    # One chart of every motif, where a loop moving 18A flattens a 2A change in a
    # helix. Two charts, so the helices have an axis of their own.
    "Per-motif Ca RMSD": (
        '<div class="md-motif-grid">'
        '<div><h3 class="md-sub">Loops</h3><div id="chart-sse-loops"></div></div>'
        '<div><h3 class="md-sub">Transmembrane</h3><div id="chart-sse-tm"></div></div>'
        "</div>"
    ),
}



#: Appended below the Pockets table, not substituted for it: the table is real data
#: the report computed and this page cannot recompute, while the viewer is this
#: page's own -- reports.py strips every script from an upload, so a viewer that
#: arrived in the dashboard could never run here. Same controls and list markup as
#: the Superposed targets pane, because it is the same question asked of the same
#: superposition: where does each ligand actually sit.
POCKETS_VIEWER_HTML = (
    '<div class="md-detail-pane md-pockets-pane">'
    '<h3 class="md-sub">Where the ligands landed</h3>'
    '<div class="md-detail-body"><div id="viewer-pockets" class="md-viewer"></div></div>'
    '<div class="md-viewer-controls md-button-row" data-viewer="pockets">'
    '<button type="button" class="md-btn md-btn-secondary" data-style="spin">Spin</button>'
    '<button type="button" class="md-btn md-btn-secondary" data-style="reset">Reset</button>'
    '</div>'
    '<p class="md-hint" id="pockets-note" style="margin-bottom:0"></p>'
    '<div class="md-overlay-list" id="pockets-list"></div>'
    '</div>'
)


#: Appended below the Ligand pose vs experiment table, for the same reason the
#: pockets viewer is appended below its own: the table is the measurement, which only
#: the machine that ran the prediction could make, and the viewer is this page's. One
#: small viewer per pair rather than one big one holding all of them, because the
#: question here is per pair -- "did THIS ligand land where the experiment puts it" --
#: and a dozen pairs superposed in one frame is the picture that question is not.
POSE_VIEWER_HTML = (
    '<div class="md-detail-pane md-pose-pane">'
    '<h3 class="md-sub">Predicted against experimental</h3>'
    '<p class="md-hint" id="pose-note" style="margin-top:0"></p>'
    '<div class="md-pose-grid" id="pose-grid"></div>'
    '</div>'
)


def _strip_pose_pane(html: str) -> str:
    """Remove the report's own `.pose-pane` block, brace-counting rather than regex.

    A regex for `<div class='pose-pane'>.*?</div>` stops at the FIRST closing tag,
    which is several levels inside, and leaves a tail of orphaned markup that the
    sanitiser then re-balances into visible fragments. Walking the div nesting is the
    same approach `_cards` already takes for the same reason.
    """
    # The class token exactly, not a substring: this page's own viewer is
    # `md-pose-pane`, which contains `pose-pane`, so a loose match would delete the
    # replacement along with the thing it replaces.
    marker = re.search(r"<div[^>]*\bclass=['\"](?:[^'\"]*\s)?pose-pane(?:\s[^'\"]*)?['\"][^>]*>",
                       html)
    if not marker:
        return html
    depth, i = 0, marker.start()
    for tag in re.finditer(r"<(/?)div\b[^>]*>", html[marker.start():]):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            i = marker.start() + tag.end()
            break
    else:
        return html[:marker.start()]
    return html[:marker.start()] + html[i:]


#: The two panels compare-sse emits separately, in the order they must appear.
_COVERAGE_TITLES = ("Family coverage", "Overall shift statistics")
COVERAGE_MERGED_TITLE = "Family coverage and SSE shifts"


def _merge_coverage_panels(panels: list) -> list:
    """Fold "Overall shift statistics" into "Family coverage" as one card.

    They are two short tables describing the same comparison -- which families could
    be compared, and by how much they moved -- and as separate cards they filled a
    screen between them while neither had enough in it to earn one.

    Merged here rather than in the report, because the report writes them into its
    own combined card while the compare-sse page (which this page prefers, for its
    granularity) keeps them apart.
    """
    by_title = {}
    for panel in panels:
        by_title.setdefault(_panel_title(panel), panel)
    first, second = (by_title.get(t) for t in _COVERAGE_TITLES)
    if not (isinstance(first, dict) and isinstance(second, dict)):
        return panels

    first["title"] = COVERAGE_MERGED_TITLE
    first["html"] = (f"{first['html']}"
                     f"<h3 class=\"md-sub\">{_COVERAGE_TITLES[1]}</h3>"
                     f"{second['html']}")
    return [panel for panel in panels if panel is not second]


def rebuild_panels(panels: list) -> list:
    """Swap in this page's own markup for the panels it redraws."""
    panels = _merge_coverage_panels(panels)
    for panel in panels:
        title = _panel_title(panel)
        if title in _REBUILT_PANELS and isinstance(panel, dict):
            panel["html"] = _REBUILT_PANELS[title]
            panel["kind"] = "plain"
        elif title == "Summary table" and isinstance(panel, dict):
            panel["html"] = shorten_headers(panel["html"])
        elif title == "Pockets" and isinstance(panel, dict):
            panel["html"] = panel["html"] + POCKETS_VIEWER_HTML
        elif title == "Ligand pose vs experiment" and isinstance(panel, dict):
            # The report now draws its own pair grid with 3Dmol, so the uploaded panel
            # carries a copy of it. Scripts are stripped from an upload, so that copy
            # arrives as inert text -- headings, RMSDs and Spin/Reset buttons that do
            # nothing -- immediately above this page's live Mol* version. Strip it
            # before appending, or the reader sees the same panel twice and only the
            # lower one works.
            panel["html"] = _strip_pose_pane(panel["html"]) + POSE_VIEWER_HTML
    return panels

#: Header text the summary table can spare. Every column of that table is a
#: number two or three characters wide under a header two or three times as long,
#: so it is the headers that set the column widths and the headers that wrap --
#: "5HT2A" came out as "5HT2 A" down two lines because "Interactions" above it
#: would not fit. The legend under the table already says what each one is.
_HEADER_SHORTENINGS = {
    "H-bond": "H",
    "\u03c0-stack": "\u03c0",
    "Halogen": "Hal",
    "Phobic": "Phob",
    "Binder p": "Binder",
    "Lig ipTM": "Lig",
    "PPI ipTM": "PPI",
}

_TH_RE = re.compile(r"(<th[^>]*>)(.*?)(</th>)", re.S)


def shorten_headers(html: str) -> str:
    """Trim the summary table's headers to what the columns under them need."""
    def swap(match):
        inner = match.group(2)
        text = re.sub("<[^>]+>", "", inner).strip()
        if text in _HEADER_SHORTENINGS:
            return match.group(1) + _HEADER_SHORTENINGS[text] + match.group(3)
        return match.group(0)
    return _TH_RE.sub(swap, html)

