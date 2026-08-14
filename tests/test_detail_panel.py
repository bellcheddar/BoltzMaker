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
    """The interaction pane was a PLIP PNG. Both are structures now, with the same
    three controls, so the second is a view of the pocket rather than a picture."""
    html = _explorer_html()
    assert 'id="viewer"' in html and 'id="viewer-contacts"' in html
    assert html.count('data-style="spin"') == 2
    assert html.count('data-style="surface"') == 2


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
