"""Which pocket a finished target was run against, and how the pane paints it.

The campaign file is the only record: the manifest keeps the contacts a target
used but never the code naming them, so the grouping is recovered from the
target's own stem. The tests that matter are the ones about not recovering it
wrongly.
"""

from __future__ import annotations

import pytest

from boltzmaker_web import pocket, reports

MATRIX_MD = """Settings:
Pocket distance: 8

Protein: GLP1R
Sequence: MKTAYIAK
Pocket contact: GLP1R residue 154 as 41Y
Pocket contact: GLP1R residue 187 as 41Y
Pocket contact: GLP1R residue 321 as V6G

Ligand: ORFO
SMILES: CCO
"""

UNNAMED_MD = """Protein: RECP
Sequence: MKTAYIAK
Pocket contact: RECP residue 40

Ligand: LIG
SMILES: CCO
"""


def test_codes_come_out_in_file_order():
    assert pocket.campaign_pocket_codes(MATRIX_MD) == ["41Y", "V6G"]


def test_a_code_is_listed_once_however_many_contacts_it_has():
    assert pocket.campaign_pocket_codes(MATRIX_MD).count("41Y") == 1


def test_an_unnamed_pocket_is_detected():
    assert pocket.has_unnamed_pocket(UNNAMED_MD)


def test_a_matrix_campaign_has_no_unnamed_pocket():
    assert not pocket.has_unnamed_pocket(MATRIX_MD)


def test_a_campaign_with_no_pockets_at_all():
    assert pocket.campaign_pocket_codes("Protein: X\nSequence: MK\n") == []
    assert not pocket.has_unnamed_pocket("Protein: X\nSequence: MK\n")


@pytest.mark.parametrize("stem,expected", [
    ("GLP1R_ORFO_V6G", "V6G"),
    ("GLP1R_ORFO_41Y", "41Y"),
    ("GLP1R_ORFO", "Unconstrained"),
])
def test_the_stem_says_which_pocket(stem, expected):
    codes = pocket.campaign_pocket_codes(MATRIX_MD)
    assert pocket.group_for(stem, "GLP1R", "ORFO", codes, False) == expected


def test_a_ligand_named_like_a_pocket_is_not_read_as_one():
    """The whole stem is matched, not its suffix.

    A campaign whose ligand is called V6G produces the target GLP1R_V6G, which
    ends in a pocket code while being an unconstrained run of that ligand.
    """
    codes = pocket.campaign_pocket_codes(MATRIX_MD)
    assert pocket.group_for("GLP1R_V6G", "GLP1R", "V6G", codes, False) == "Unconstrained"


def test_an_apo_target_is_not_given_a_pocket():
    codes = pocket.campaign_pocket_codes(MATRIX_MD)
    assert pocket.group_for("GLP1R", "GLP1R", None, codes, False) == "Unconstrained"


def test_a_constrained_target_is_not_called_unconstrained():
    assert pocket.group_for("RECP_LIG", "RECP", "LIG", [], True) == "Unnamed pocket"


def test_the_viewer_markup_is_appended_not_substituted():
    """The table is data the report computed and this page cannot recompute."""
    panels = [{"title": "Pockets", "html": "<table>real data</table>", "kind": "plain"}]
    reports.rebuild_panels(panels)
    assert "real data" in panels[0]["html"]
    assert 'id="viewer-pockets"' in panels[0]["html"]


def test_the_viewer_carries_the_same_controls_as_the_other_panes():
    assert 'data-viewer="pockets"' in reports.POCKETS_VIEWER_HTML
    assert 'data-style="spin"' in reports.POCKETS_VIEWER_HTML
    assert 'data-style="reset"' in reports.POCKETS_VIEWER_HTML
    assert 'id="pockets-list"' in reports.POCKETS_VIEWER_HTML


def test_pockets_is_ordered_above_ligand_preparation():
    order = list(reports.PANEL_ORDER)
    assert order.index("Pockets") < order.index("Ligand preparation")


# ---------------------------------------------------------------------------
#  Uniform colour has to outlive the representation rebuild
# ---------------------------------------------------------------------------

def _viewer_js():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent
            / "web" / "static" / "js" / "viewer.js").read_text()


def test_type_is_applied_before_colour():
    """Changing a representation's type rebuilds it with that type's default theme.

    Applied the other way round -- or concurrently, which is what Promise.all did --
    the rebuild overwrites the uniform colour with element colours on a ligand and
    chain colours on a receptor, and the pockets pane comes out rainbow when it asked
    for grey backbones and one colour per pocket.
    """
    js = _viewer_js()
    body = js[js.index("Wrapper.prototype.loadExtra"):js.index("Wrapper.prototype.setExtraVisible")]
    assert body.index("updateRepresentations(") < body.index("updateRepresentationsTheme("), \
        "type must be set before the uniform colour"


def test_they_are_not_raced_against_each_other():
    js = _viewer_js()
    body = js[js.index("Wrapper.prototype.loadExtra"):js.index("Wrapper.prototype.setExtraVisible")]
    # Comments stripped: the fix explains itself by naming Promise.all, and matching
    # the prose instead of the code would make this test pass on the broken version.
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("//"))
    assert "Promise.all" not in code, "these two updates are order-dependent, not parallel"
