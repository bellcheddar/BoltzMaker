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
    """The explorer's markup, wherever it lives.

    It is two templates: the page, and the panels partial the downloadable
    package shares with it. Which half a given element sits in is an arrangement
    detail, and tests that pinned it to one file all failed the day the panels
    moved -- on markup that had not changed."""
    templates = WEB / "templates"
    return "\n".join((templates / name).read_text()
                     for name in ("auto_explorer.html", "_explorer_panels.html"))


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
    """Asserts what the classifier DOES, not how it is written.

    The previous version of this test pinned the implementation string
    `indexOf("TM") === 0`, which is precisely the bug: a Pfam-annotated campaign
    names its whole transmembrane bundle `7tm_2`, that test passed, and the
    Transmembrane panel rendered empty on real data with nothing logged anywhere.
    """
    import re as _re
    js = _explorer_js()
    fn = js[js.index("var TM_MOTIF"):js.index("/* The per-motif chart")]
    pattern = _re.search(r"var TM_MOTIF = /(.+)/;", fn).group(1)
    matcher = _re.compile(pattern)

    def classify(name):
        return "tm" if matcher.search(str(name).upper()) else "loop"

    # 7tm_2 is Pfam's class B GPCR seven-transmembrane bundle -- the case that was wrong.
    for name in ("7tm_2", "7TM_1", "TM6", "tm1", "Transmembrane_region"):
        assert classify(name) == "tm", name
    for name in ("ICL2", "ECL3", "H8", "Phage_lysozyme", "Rhodopsin"):
        assert classify(name) == "loop", name


def test_the_split_also_narrows_the_pinned_category_list():
    """The report pins the category order so every chart shares one x axis. Left
    alone, both halves draw all fifteen motifs and only half of each has any bars
    -- the split was in the data and invisible on screen."""
    js = _explorer_js()
    split = js[js.index("function splitMotifChart"):js.index("//: Plotly's typed-array spec")]
    assert "categoryarray" in split


def test_the_two_motif_panels_share_one_legend():
    """One legend under the pair, not a Plotly legend inside the left chart.

    The halves are separate plots, so a Plotly legend belongs to one of them and
    cannot span both -- it took a third of the left chart's width and left the right
    chart with no key at all. The shared one is built as HTML and inserted after the
    grid, so it spans them.
    """
    js = _explorer_js()
    split = js[js.index("function splitMotifChart"):js.index("function buildMotifLegend")]
    assert "showlegend = false" in split, "neither half draws its own"
    assert 'showlegend = kind === "loop"' not in split
    assert "buildMotifLegend(grid, spec)" in split

    builder = js[js.index("function buildMotifLegend"):js.index("//: Plotly's typed-array spec")]
    assert "md-motif-legend-item" in builder
    assert "insertBefore(legend, grid.nextSibling)" in builder, "after the grid, spanning it"


def test_typed_arrays_are_decoded_before_a_trace_is_split():
    """Numbers that came from numpy arrive as base64, not as a JSON array, so
    trace.y[i] is undefined and every bar would vanish."""
    js = _explorer_js()
    assert "TYPED_ARRAYS" in js and "atob(" in js


def test_the_fingerprints_share_one_scale():
    """Left to itself each heatmap scales to its own maximum, and a family with
    one weak contact then looks exactly like one with many."""
    js = _explorer_js()
    fn = js[js.index("function shareFingerprintScale"):js.index("function computeFingerprintMax")]
    assert "trace.zmin = 0;" in fn
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


def test_every_trace_is_the_same_region_of_the_protein():
    """Drawing whole chains put a correctly superposed core inside a haze of the
    parts that were never fitted -- a 5-HT2A N-terminus and ICL3 are long,
    disordered and differ between predictions, taking the picture from 0.8A of
    agreement to 9.8A of spray. Drawing each target's OWN core instead would have
    every trace covering a different stretch, which is a different way of not
    being comparable."""
    src = (WEB / "boltzmaker_web" / "views_auto.py").read_text()
    fn = src[src.index("def _overlay_payload"):src.index('@bp.route("/analysis/<token>/overlay.json")')]
    # A residue is in the shared region when at least half the fits kept it: an
    # intersection is at the mercy of the single worst target, a union puts the
    # disordered parts back.
    assert "votes[ref_number]" in fn
    assert "count >= threshold" in fn


def test_the_reported_rmsd_is_over_the_region_drawn():
    """The panel draws one region for everybody, so the number beside each row has
    to be the one the picture shows -- and only then are the fifteen numbers
    measurements of the same thing."""
    src = (WEB / "boltzmaker_web" / "views_auto.py").read_text()
    assert "def _rmsd_over(" in src
    assert "shared_rmsd = _rmsd_over(" in src


def test_hiding_a_structure_is_idempotent():
    """toggleVisibility flips whatever the current state is, so calling it for a
    checkbox that is already unchecked would put the structure back."""
    js = _viewer_js()
    fn = js[js.index("Wrapper.prototype.setExtraVisible"):js.index("Wrapper.prototype.frameAll")]
    assert "isHidden" in fn and "if (hidden === !visible) return;" in fn


def test_the_accession_box_stays_hidden_until_it_is_needed():
    """`display: flex` and the browser's own `[hidden] { display: none }` have the
    same specificity, so the later one wins -- the box sat open on every page
    asking for something nobody needed."""
    css = (WEB / "static" / "css" / "brand.css").read_text()
    assert ".md-af-ask[hidden] { display: none; }" in css


def test_the_contacts_are_drawn_and_measured():
    """Mol* has an `interactions` representation that computes its own, but it
    only sees the component it is given and this build has no query language to
    build a "ligand plus surroundings" component with -- on the ligand alone it
    finds nothing and draws nothing. Measurements need no component, and drawing
    the contacts PLIP reported keeps the picture and the list beside it the same
    set of facts rather than two opinions."""
    js = _viewer_js()
    assert "Wrapper.prototype.showInteractions" in js
    assert "measurement.addDistance(" in js


def test_a_contact_is_measured_between_atoms_not_centroids():
    """A dashed line between two whole residues is drawn between their centroids,
    which for a tryptophan against a ligand is several angstrom from where the
    contact actually is."""
    js = _viewer_js()
    assert "function closestAtomLoci" in js
    fn = js[js.index("Wrapper.prototype.showInteractions"):]
    assert "closestAtomLoci(data, residue, ligandCentre)" in fn
    assert "closestAtomLoci(data, ligand, residueAtom.point)" in fn


def test_the_pocket_is_served_as_its_own_structure():
    """Sticks need a representation, a representation needs a component, and this
    Mol* build cannot build one from a selection: modifyByCurrentSelection takes
    union/subtract/intersect and silently does nothing for anything else, which is
    why the first attempt drew no sticks and reported success."""
    src = (WEB / "boltzmaker_web" / "views_auto.py").read_text()
    assert "def pocket(" in src
    js = _explorer_js()
    assert 'loadExtra("pocket"' in js
    assert 'type: "ball-and-stick"' in js


def test_the_pocket_is_loaded_before_the_camera_is_framed():
    """Loading a structure resets the camera to fit everything, so loading it last
    threw the framing away and left the pane showing the whole complex."""
    js = _explorer_js()
    block = js[js.index('loadExtra("pocket"'):]
    assert block.index("focusContacts") < block.index("setSpin")


# --- the Prepare form's UniProt autofill ---------------------------------------

def test_both_proteins_and_partners_can_name_an_accession():
    html = (WEB / "templates" / "_wizard_fields.html").read_text()
    assert 'name="protein_uniprot[]"' in html
    assert 'name="partner_uniprot[]"' in html
    assert html.count('data-uniprot-for') == 2


def test_the_accession_box_comes_before_what_it_fills():
    """It fills the short name and the sequence, so it reads wrong sitting under
    them."""
    html = (WEB / "templates" / "_wizard_fields.html").read_text()
    block = html[html.index("<template id=\"tpl-protein\">"):]
    assert block.index('protein_uniprot[]') < block.index('protein_name[]')


def test_autofill_is_delegated_not_bound_per_row():
    """Rows are cloned from a <template> at any time, and a handler bound at load
    would never reach them."""
    js = (WEB / "static" / "js" / "wizard.js").read_text()
    assert 'document.addEventListener("change"' in js
    assert "[data-uniprot-for]" in js


def test_autofill_never_overwrites_what_was_typed():
    """Someone who has pasted their own construct and then names the accession for
    the AlphaFold overlay must not have that construct silently replaced by the
    canonical sequence -- the two are often different on purpose, which is the
    whole reason the accession is asked for separately."""
    js = (WEB / "static" / "js" / "wizard.js").read_text()
    assert "!fields.name.value.trim()" in js
    assert "!fields.sequence.value.trim()" in js


def test_the_gene_name_is_trimmed_to_a_legal_chain_id():
    """Boltz allows five characters, and a chain id has to survive the wizard's own
    validator."""
    src = (WEB / "boltzmaker_web" / "alphafold.py").read_text()
    fn = src[src.index("def entry("):src.index("def model_url(")]
    assert "c.isalnum()" in fn and "[:5]" in fn


def test_the_mobile_rules_come_last_in_the_stylesheet():
    """A media query carries no extra specificity, so a plain rule written LATER
    beats it at every width. The fingerprint and per-motif grids were defined
    below the mobile block and stayed two columns on a phone, which put two 180px
    heatmaps side by side with their titles overlapping."""
    css = (WEB / "static" / "css" / "brand.css").read_text()
    media = css.index("@media (max-width: 768px)")
    for rule in (".md-fingerprint-grid {", ".md-motif-grid {"):
        assert css.index(rule) < media, rule + " is defined after the mobile block"


def test_margins_follow_the_charts_width_not_the_windows():
    """A chart in a two-column grid is half a page wide even on a desktop, and the
    wide margins are most of it: a fingerprint in a 530px cell came out 157px
    square, having reserved 120 for row names and 250 for a legend of two words."""
    js = _explorer_js()
    assert "NARROW_CHART" in js
    assert "width <= NARROW_CHART" in js


def test_charts_are_grouped_by_panel_as_well_as_width():
    """Width alone conflated two different two-column grids with the same cell
    width -- the per-motif pair, whose legend is twelve full target names, and the
    fingerprints, whose legend is two words."""
    js = _explorer_js()
    fn = js[js.index("function equaliseMargins"):js.index("function settleMargins")]
    assert "host.closest(" in fn
    # Top and bottom are equalised within a panel, so a pair of cards line up.
    assert "wide.t = Math.max" in fn and "wide.b = Math.max" in fn


def test_the_fingerprints_have_no_colourbar():
    """The values are 0 and 1 -- touched or not -- and a bar running 0, 0.5, 1
    under the word "contacts" invited a reading of how many, which the plot does
    not say."""
    js = _explorer_js()
    fn = js[js.index("function shareFingerprintScale"):js.index("function computeFingerprintMax")]
    assert "trace.showscale = false;" in fn
    assert "spec.layout.showlegend = first" in fn


# --- the Prepare form ----------------------------------------------------------

def _wizard_js() -> str:
    return (WEB / "static" / "js" / "wizard.js").read_text()


def test_enter_does_not_submit_the_form():
    """A form with a submit button submits on Enter from any text input, which on
    a page this long means: type a protein name, press Enter out of habit, and the
    server answers "At least one ligand is required" -- an error about the bottom
    of the page while you are still filling in the top. The UniProt boxes made it
    likelier, because Enter is exactly what anyone types after an accession."""
    js = _wizard_js()
    block = js[js.index("Enter must not submit the form"):]
    assert 'event.key !== "Enter"' in block
    assert "event.preventDefault();" in block


def test_a_textarea_keeps_enter():
    """A sequence is pasted into one and newlines belong there."""
    js = _wizard_js()
    block = js[js.index("Enter must not submit the form"):]
    assert 'tag === "textarea"' in block


def test_the_submit_button_keeps_enter():
    """So the form can still be sent from the keyboard by someone who has tabbed
    to it deliberately."""
    js = _wizard_js()
    block = js[js.index("Enter must not submit the form"):]
    assert 'el.type === "submit"' in block


def test_a_validation_error_names_the_section_it_is_about():
    """The message says what is missing but not where it lives, and "at least one
    ligand is required" can be two screens below the protein someone was filling
    in when they triggered it."""
    html = (WEB / "templates" / "auto_prepare.html").read_text()
    assert 'id="form-error"' in html and 'data-field=' in html
    src = (WEB / "boltzmaker_web" / "views_auto.py").read_text()
    assert "error_field=getattr(exc, 'field', '')" in src
    js = _wizard_js()
    assert "SECTIONS" in js and 'ligands: "ligand-rows"' in js


def test_the_viewer_orients_with_the_cameras_own_state_not_the_manager():
    """`managers.camera.setSnapshot` applies position and target and drops `up`.

    Measured: against a computed receptor axis of [0.759, 0.538, 0.367] the camera
    came back with up [0, 1, 0], so the molecule moved and the view stayed level --
    which looks exactly like the orientation code never ran. `camera.setState` keeps
    it, and the same probe then returned dot(axis, up) = 1.0000.
    """
    js = (WEB / "static" / "js" / "viewer.js").read_text()
    fn = js[js.index("Wrapper.prototype.orientNTerminusUp"):js.index("Wrapper.prototype.hideAxes")]
    import re as _re
    # Comments stripped first: the one explaining this fix names the broken call, and
    # a bare substring check would fail on the explanation rather than on the code.
    code = _re.sub(r"//[^\n]*", "", fn)
    assert "camera.setState(" in code
    assert "managers.camera.setSnapshot" not in code
    assert "Float32Array" in fn, "gl-matrix Vec3 is a Float32Array, not a plain array"


def test_the_overall_structure_viewer_orients_on_the_receptor_chain():
    """`t.family_id` is undefined in the payload -- the field is `t.family`.

    The undefined lookup passed null, which orients on the whole complex (receptor
    plus three G-protein chains) rather than the receptor, so the axis was not the
    receptor's and the ECD landed wherever it fell.
    """
    js = (WEB / "static" / "js" / "explorer.js").read_text()
    assert "orientNTerminusUp(t.family || null)" in js
    assert "orientNTerminusUp(t.family_id" not in js
