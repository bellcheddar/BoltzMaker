"""The target detail panel: two Mol* viewers, the contact list and the sequence.

These read the shipped JS and templates rather than running them. A browser test
would be better and is not what this suite is; what these catch is the class of
regression where a file is edited and the behaviour it encodes quietly goes --
most of all the Mol* extension list, which is the difference between a page that
talks only to this server and one that does not.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def _viewer_js() -> str:
    return (WEB / "static" / "js" / "viewer.js").read_text()


def _explorer_js() -> str:
    return (WEB / "static" / "js" / "explorer.js").read_text()


def _explorer_html() -> str:
    return (WEB / "templates" / "auto_explorer.html").read_text()


# --- the viewer ---------------------------------------------------------------

def test_molstar_runs_with_no_extensions():
    """Mol* enables every extension by default, and one of them -- Volumes &
    Segmentations -- fetches a listing from a server in Brno the moment a viewer
    is created. Two viewers on this page meant two calls to a third party, from a
    site that otherwise talks only to itself, for a feature nothing here uses. It
    fails silently when offline, which is how it went unnoticed until the console
    was read."""
    assert re.search(r"extensions:\s*\[\]", _viewer_js())


def test_the_viewer_is_vendored_not_fetched_from_a_cdn():
    """A CDN tag would be a second third-party dependency at page load, and the
    droplet is the only thing this page should need."""
    html = _explorer_html()
    assert "molstar-4.9.0.js" in html and "molstar-4.9.0.css" in html
    assert "cdn.jsdelivr" not in html and "unpkg.com" not in html
    for name in ("molstar-4.9.0.js", "molstar-4.9.0.css"):
        assert (WEB / "static" / "vendor" / name).is_file()


def test_molstar_is_not_in_the_bundle_vendor_directory():
    """The repo-root vendor/ is copied wholesale into every bundle a user
    downloads. Mol* is 5MB and is only ever used by this website, so it lives
    under web/static instead."""
    root = WEB.parent / "vendor"
    assert not list(root.glob("molstar*"))


def test_loading_resolves_with_the_wrapper():
    """It used to resolve with whatever setStyle returned, which was undefined --
    so the caller's `.then(wrapper => ...)` read as success and then failed on the
    first property it touched. The pose pane only set text and survived; the
    interaction pane called a method and did not."""
    js = _viewer_js()
    load = js[js.index("Wrapper.prototype.load"):js.index("Wrapper.prototype.components")]
    assert "return self;" in load


def test_a_residue_is_selected_by_author_numbering():
    """auth_seq_id and auth_asym_id, which is what PLIP reports and what the
    sequence track shows. label_seq_id renumbers from 1 per chain and would
    silently select the wrong residue."""
    js = _viewer_js()
    assert "auth_seq_id" in js and "auth_asym_id" in js
    assert "label_seq_id" not in js


def test_the_chain_test_does_not_assume_one_chain_per_unit():
    """Mol* does split units by chain today. A loop that breaks out on the first
    non-matching chain depends on that and returns nothing the day it changes."""
    js = _viewer_js()
    loci = js[js.index("function residueLoci"):js.index("function chainLoci")]
    assert "continue;" in loci and "break;" not in loci


def test_the_missing_viewer_reasons_are_distinguishable():
    """The library failing to load and the browser having no WebGL are different
    problems with different fixes."""
    js = _viewer_js()
    assert "WebGL" in js
    assert "did not load" in js


# --- the panel ----------------------------------------------------------------

def test_both_panes_are_viewers():
    """The interaction pane was a PLIP PNG. Both are structures now, so the second
    is a view of the pocket rather than a picture of one."""
    html = _explorer_html()
    assert 'id="viewer"' in html and 'id="viewer-contacts"' in html
    # Cartoon and surface belong to the two per-target panes only: the overlay
    # panes draw sticks and a trace, and a surface of fifteen superposed
    # structures is a solid block.
    assert html.count('data-style="surface"') == 2
    assert html.count('data-style="cartoon"') == 2
    # Spin and reset belong to all four.
    assert html.count('data-style="spin"') == 4


def test_each_control_row_names_its_viewer():
    """One handler bound to `.md-viewer-controls button` would drive whichever
    viewer the code happened to hold, from either row."""
    html = _explorer_html()
    assert 'data-viewer="pose"' in html and 'data-viewer="contacts"' in html


def test_the_heading_is_the_target_picker():
    html = _explorer_html()
    assert 'id="detail-target"' in html
    assert "<select" in html[html.index('id="detail-card"'):]


def test_the_interaction_pane_spins_on_load():
    assert "setSpin(true)" in _explorer_js()


def test_the_contacts_are_mapped_from_plip_chain_letters():
    """PLIP says "chain A" for a structure whose first chain is called 5HT2A. The
    sequence payload carries the mapping; without it the viewer is asked for a
    chain that does not exist and silently frames nothing."""
    js = _explorer_js()
    assert "byLetter" in js and "chainIdFor" in js


def test_the_sequence_track_is_drawn_at_device_resolution():
    """A canvas sized in CSS pixels is resampled on a retina screen, and 11px
    letters come out muddy."""
    js = _explorer_js()
    assert "devicePixelRatio" in js
    assert "setTransform(ratio" in js


def test_the_logo_scales_letters_by_information_not_by_frequency():
    """A residue at 100% of a column that only one sequence has is not conserved.
    The server scales bits by occupancy; the drawing has to use the bits."""
    js = _explorer_js()
    draw = js[js.index("function drawSequence"):js.index("function sequenceIndexAt")]
    assert "entry[1] * entry[2]" in draw          # fraction x bits


def test_only_the_shown_chains_contacts_are_marked():
    """A contact on a partner chain is real and has no place on a track that is
    one chain's sequence."""
    js = _explorer_js()
    contacts = js[js.index("function contactsByNumber"):js.index("function renderSequence")]
    assert "row.chain !== letter" in contacts


def test_the_sequence_canvas_escapes_the_responsive_image_cap():
    """brand.css caps every canvas at 100% of its column so images stay inside
    their card. The sequence track is 5652px wide by design and scrolls; capped,
    it was squashed into 910px and drew 471 residues two pixels apart."""
    css = (WEB / "static" / "css" / "brand.css").read_text()
    assert "canvas" in css and "max-width: 100%" in css        # the global cap
    seq = css[css.index(".md-seq-canvas"):]
    assert "max-width: none" in seq[:200]


# --- the controls and the panes added later -----------------------------------

def test_reset_is_on_every_viewer_and_alphafold_on_the_per_target_ones():
    """AlphaFold overlays the model of ONE protein, so it has no meaning on a pane
    showing fifteen targets at once."""
    html = _explorer_html()
    assert html.count('data-style="reset"') == 4
    assert html.count('data-style="alphafold"') == 2


def test_reset_returns_each_pane_to_its_own_framing():
    """The two panes did not open on the same thing -- the pose on the whole
    complex, the interaction pane on the pocket -- so one shared "show everything"
    would throw away the second pane's entire reason for being."""
    js = _explorer_js()
    reset = js[js.index('if (mode === "reset")'):js.index("wrapper.setStyle(mode);")]
    assert "focusContacts" in reset and "resetCamera" in reset


def test_the_overlay_is_removed_when_the_target_changes():
    """plugin.clear() takes the scene with it, so a wrapper still holding the old
    overlay would refuse to load the new one and report it as already shown."""
    js = _viewer_js()
    load = js[js.index("Wrapper.prototype.load"):js.index("Wrapper.prototype.components")]
    assert "self.overlay = null" in load


def test_the_ligand_card_comes_from_the_report():
    """There is no chemistry toolkit in this venv to redraw a structure with, so
    the depiction is lifted out of the grid the report already drew."""
    assert "ligand-cards" in _explorer_html()
    assert "ligandCards" in _explorer_js()


# --- the layout added later ---------------------------------------------------

def test_the_fingerprints_are_grouped_rather_than_styled():
    """They are siblings in the page's flow, and no selector can put two of a run
    of cards side by side and leave the rest full width."""
    from boltzmaker_web import reports
    panels = [{"title": "Campaign summary", "html": "", "wide": False, "kind": "table"},
              {"title": "A: residue interaction fingerprint", "html": "", "wide": True, "kind": "plain"},
              {"title": "B: residue interaction fingerprint", "html": "", "wide": True, "kind": "plain"}]
    slots = reports.ordered_slots(panels)
    groups = [s for s in slots if s["kind"] == "group"]
    assert len(groups) == 1 and len(groups[0]["panels"]) == 2


def test_every_panel_has_an_anchor_and_appears_in_the_navigation():
    from boltzmaker_web import reports
    panels = [{"title": "Campaign summary", "html": "", "wide": False, "kind": "table"},
              {"title": "Summary table", "html": "", "wide": False, "kind": "table"}]
    slots = reports.ordered_slots(panels)
    assert all(s.get("anchor") for s in slots)
    nav = reports.navigation(slots)
    assert len(nav) == len(slots)
    assert all(entry["title"] and entry["anchor"] for entry in nav)
    # The page's own panels are named, not left as their internal code.
    assert "Target detail" in [entry["title"] for entry in nav]


def test_the_anchor_is_derived_from_the_title_not_the_position():
    """A campaign produces different panels depending on what it ran, so an
    ordinal would point at a different panel in a different campaign."""
    from boltzmaker_web import reports
    assert reports.anchor_for("pIC50 vs confidence score") == "panel-pic50-vs-confidence-score"
    assert reports.anchor_for("Family x ligand selectivity") == "panel-family-x-ligand-selectivity"


def test_the_overall_structure_pane_is_named_that():
    assert "Overall structure" in _explorer_html()
    assert "Predicted pose" not in _explorer_html()


def test_the_ligand_is_not_coloured_off_the_chain_scale():
    """chain-id gave the ligand the fifth colour in a series on a five-chain
    complex, rather than making it the thing the campaign is about."""
    js = _viewer_js()
    assert "LIGAND_RED" in js
    colour = js[js.index("Wrapper.prototype.colourByChain"):js.index("Wrapper.prototype.setSpin")]
    assert 'color: "chain-id"' in colour and "LIGAND_RED" in colour


def test_framing_the_contacts_does_not_select_them():
    """Mol* paints a selection bright green over whatever theme is underneath, so
    a left-over selection made the ligand green in the pane meant to show it red."""
    js = _viewer_js()
    focus = js[js.index("Wrapper.prototype.focusContacts"):js.index("Wrapper.prototype.loadExtra")]
    assert "camera.focusLoci" in focus
    assert "selection.fromLoci" not in focus


def test_the_two_overlay_panes_exist_with_their_own_lists():
    html = _explorer_html()
    for name in ("viewer-ligands", "viewer-traces", "ligands-list", "traces-list"):
        assert name in html


def test_the_overlay_structures_load_one_at_a_time():
    """Fifteen concurrent loads race each other through Mol*'s state tree, and the
    structure a load returns is then not always the one it just added."""
    js = _explorer_js()
    pane = js[js.index("function overlayPane"):js.index("// ---- the AlphaFold overlay")]
    assert "reduce(" in pane and "Promise.resolve()" in pane


# --- the charts this page rebuilds --------------------------------------------

def test_the_motif_split_puts_only_helices_in_the_transmembrane_panel():
    js = _explorer_js()
    fn = js[js.index("function motifClass"):js.index("/* The per-motif chart")]
    assert 'indexOf("TM") === 0' in fn and '"tm"' in fn


def test_the_split_also_narrows_the_pinned_category_list():
    """The report pins the category order so every chart shares one x axis. Left
    alone, both halves draw all fifteen motifs and only half of each has any bars
    -- the split was in the data and invisible on screen."""
    js = _explorer_js()
    split = js[js.index("function splitMotifChart"):js.index("//: Plotly's typed-array spec")]
    assert "categoryarray" in split


def test_the_two_motif_panels_share_one_legend():
    js = _explorer_js()
    split = js[js.index("function splitMotifChart"):js.index("//: Plotly's typed-array spec")]
    assert 'showlegend = kind === "loop"' in split


def test_typed_arrays_are_decoded_before_a_trace_is_split():
    """Numbers that came from numpy arrive as base64, not as a JSON array, so
    trace.y[i] is undefined and every bar would vanish."""
    js = _explorer_js()
    assert "TYPED_ARRAYS" in js and "atob(" in js


def test_the_fingerprints_share_one_scale_and_one_bar():
    """Left to itself each heatmap scales to its own maximum, and a family with
    one weak contact then looks exactly like one with many."""
    js = _explorer_js()
    fn = js[js.index("function shareFingerprintScale"):js.index("function computeFingerprintMax")]
    assert "trace.showscale = first" in fn
    assert "trace.zmax = fingerprintMax" in fn


def test_the_fingerprint_plot_areas_are_square():
    """Both axes are lists -- residues and ligands -- and a wide thin box makes
    the cells unreadable."""
    js = _explorer_js()
    assert "isFingerprint(entry.spec)" in js
    assert "Math.max(120, width)" in js


def test_charts_are_equalised_within_a_column_width():
    """A chart in a two-column grid is half as wide as a full-width one, and
    forcing it to carry the same legend reserve left it 160px of plot."""
    js = _explorer_js()
    fn = js[js.index("function equaliseMargins"):js.index("function settleMargins")]
    assert "host.offsetWidth" in fn and "groups[key]" in fn


def test_the_ranked_charts_hover_to_two_decimals():
    js = _explorer_js()
    assert "%{y:.2f}" in js
    assert "HOVER_2DP" in js


def test_the_confidence_column_is_two_decimals():
    js = _explorer_js()
    assert "cell(fmt(t.confidence, 2)" in js


def test_campaign_names_are_upper_case_where_they_are_listed():
    """Transformed rather than upper-cased at the source, so the name the bundle
    and the results file carry is untouched."""
    css = (WEB / "static" / "css" / "brand.css").read_text()
    assert ".md-campaign-name { text-transform: uppercase; }" in css
    for name in ("runs.html", "index.html"):
        assert "md-campaign-name" in (WEB / "templates" / name).read_text()


def test_a_panel_scrolled_to_clears_the_sticky_header():
    """scrollIntoView parks a card's top at the top of the viewport, which is
    behind the sticky header -- the jump landed on a panel whose border and title
    were both under the blue bar. scroll-margin-top is the browser's own answer,
    and it applies to a #hash landing as well as to scrollIntoView."""
    css = (WEB / "static" / "css" / "brand.css").read_text()
    assert "scroll-margin-top: calc(var(--md-header-height" in css


def test_the_header_height_is_measured_not_assumed():
    """On a narrow screen the nav wraps to a second row and the bar goes from 76px
    to 108px. A constant would leave the panel behind it again."""
    js = _explorer_js()
    assert "--md-header-height" in js
    assert "header.offsetHeight" in js
    # Re-measured on resize, or crossing the breakpoint leaves the old value.
    fn = js[js.index("function trackHeaderHeight"):js.index("// ---- the two campaign-wide")]
    assert 'addEventListener("resize"' in fn
