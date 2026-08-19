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


# ---------------------------------------------------------------------------
#  Clicking a row of the pockets table selects its structures
# ---------------------------------------------------------------------------

def _explorer_js():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent
            / "web" / "static" / "js" / "explorer.js").read_text()


def _brand_css():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent
            / "web" / "static" / "css" / "brand.css").read_text()


def test_the_payload_carries_what_a_row_is_matched_on():
    """The table's Pocket and Protein cells are matched against these two fields.

    The row itself carries no ids -- it is markup the report generated and this page
    only sanitised -- so without both of these there is nothing to match on.
    """
    src = (__import__("pathlib").Path(__file__).resolve().parent.parent
           / "web" / "boltzmaker_web" / "views_auto.py").read_text()
    assert '"family": target.family_id,' in src
    assert '"pocket": pocket_finder.group_for(' in src


def test_the_table_drives_the_checkboxes_rather_than_a_second_state():
    """Two sources of truth for "what is on screen" would drift the first time one
    is changed without the other."""
    js = _explorer_js()
    assert "pocketBoxes[row.id] = box;" in js
    assert "pocketBoxes[id].checked = wanted;" in js


def test_touching_a_checkbox_drops_the_row_highlight():
    """The highlight claims 'you are looking at exactly this row', which stops being
    true the moment a single structure is toggled by hand."""
    js = _explorer_js()
    # Scoped to pocketsPane: the ligand and trace panes have their own change
    # handler earlier in the file, and matching that one would prove nothing here.
    pane = js[js.index("function pocketsPane(payload) {"):js.index("// ---- the AlphaFold overlay")]
    handler = pane[pane.index('box.addEventListener("change"'):]
    assert "clearPocketTableSelection();" in handler[:400]


def test_clicking_the_selected_row_again_restores_everything():
    js = _explorer_js()
    assert "showOnlyPocketTargets(null);" in js


def test_a_row_whose_targets_produced_nothing_is_not_clickable():
    js = _explorer_js()
    assert "if (!ids.length) return;" in js


def test_the_row_affordance_is_styled():
    css = _brand_css()
    assert ".full-table tr.md-row-clickable { cursor: pointer; }" in css
    assert "md-row-selected" in css


# ---------------------------------------------------------------------------
#  One vocabulary, and the counts behind it
# ---------------------------------------------------------------------------

def _results_stub(targets, md_text=""):
    from boltzmaker_web import results as bmz

    class T:
        def __init__(self, family_group, family_id, ligand_id):
            self.family_group, self.family_id, self.ligand_id = family_group, family_id, ligand_id
    rows = [T(*t) for t in targets]
    return bmz.Results(manifest={}, targets=rows, families=[], campaign_name="c",
                       created_utc="2026-01-01", md_text=md_text)


FIVE_HT2_MD = """Protein: 5HT2A
Partners: GNAQ, GNB1, GNG2
Protein: H2ANG
Protein: H2AAP
"""


def test_the_5ht2_campaign_counts_the_way_a_reader_would():
    """Nine protein blocks, three receptors: a protein written with partners,
    without, and ligand-free is one protein to whoever reads the page."""
    from boltzmaker_web import results as bmz
    targets = []
    for fam in ("5HT2A", "5HT2B", "5HT2C"):
        for lig in ("L1", "L2"):
            targets.append((fam, fam, lig))                 # with partners
            targets.append((fam, fam + "NG", lig))           # without
        targets.append((fam, fam + "AP", None))              # ligand-free companion
    counts = bmz.campaign_counts(_results_stub(targets, FIVE_HT2_MD))
    assert counts["proteins"] == 3
    assert counts["partners"] == 3
    assert counts["ligands"] == 2
    assert counts["pockets"] == 0
    assert counts["companions"] == 3
    assert counts["predictions"] == 15


def test_a_partner_defined_but_never_co_folded_is_not_counted():
    from boltzmaker_web import results as bmz
    md = "Partner: GNAQ\nSequence: MK\nProtein: P\n"      # never on a Partners: line
    assert bmz.campaign_counts(_results_stub([("P", "P", "L")], md))["partners"] == 0


def test_pockets_are_counted_from_the_campaign():
    from boltzmaker_web import results as bmz
    md = "Pocket contact: P residue 1 as V6G\nPocket contact: P residue 2 as 41Y\n"
    assert bmz.campaign_counts(_results_stub([("P", "P", "L")], md))["pockets"] == 2


def test_every_kpi_has_a_label():
    from boltzmaker_web import results as bmz
    assert set(bmz.KPI_FIELDS) == set(bmz.KPI_LABELS)


def test_the_protein_column_is_not_called_target():
    """It was, while the list below it called a prediction a target -- one word for
    two things, on one page."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "BoltzMaker.py").read_text()
    assert '"family_group": "Protein"' in src
    assert '"family_id": "Protein"' in src


def test_the_offline_package_gets_the_same_context_as_the_page():
    """_explorer_panels.html is rendered from two places."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "web" / "boltzmaker_web" / "views_auto.py").read_text()
    assert src.count("kpi_fields=bmz.KPI_FIELDS") == 2
