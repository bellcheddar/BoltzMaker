"""Output layer for compare-sse: CSV/DataFrame, a PyMOL .pml script per target, Plotly
charts, and a standalone self-contained HTML report. As of compare-sse becoming a core
part of `analyze`/`all`, write_html() in BoltzMaker.py also embeds this same data
(family coverage + summary stats + table + charts) into the main boltz_dashboard.html,
reusing the functions in this module rather than duplicating the HTML-building logic.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from BoltzMaker import (  # noqa: E402
    PLOTLY_JS_PATH, _BRAND_CSS, _BRAND_FOOTER, _BRAND_HEADER, _AXIS_LABEL_FONTSIZE,
    _TICK_FONTSIZE, _plotly_to_div,
)

CSV_COLUMNS = [
    "family_id", "family_display", "target_stem", "target_display", "ligand_id", "motif_name",
    "motif_kind", "annotator_source",
    "n_residues", "ca_rmsd_A", "centroid_shift_A", "axis_rotation_deg", "kink_angle_apo_deg",
    "kink_angle_holo_deg", "kink_angle_delta_deg", "boundary_start_delta", "boundary_end_delta",
    "n_flagged_phipsi_residues", "flagged_residues", "dfg_state_apo", "dfg_state_holo",
    "dfg_state_changed", "alphac_state_apo", "alphac_state_holo", "alphac_state_changed", "notes",
]

_SIGNIFICANT_RMSD_A = 2.0  # motifs above this get labeled in the .pml script
_NA = "N/A"  # explicit marker for a metric that genuinely wasn't computed for a motif

_FAMILY_STATUS_LABELS = {
    "ok": "OK",
    "no_apo_structure": "No apo structure configured",
    "apo_not_found": "Apo structure file not found",
    "annotation_failed": "No motif annotation available",
    "no_predicted_structures": "No predicted (holo) structures yet",
    "no_targets": "No targets for this family",
}

# Grouped-header table, matching the exact pattern (and reusing the exact CSS classes:
# full-table / ft-group / ft-num / ft-group-start) already established for the main
# dashboard's Summary table (see BoltzMaker.py's _full_table_label/_full_table_group).
# Short labels + colspan group bands keep 22 raw columns readable instead of a wall of
# snake_case headers; a group that's entirely N/A for this campaign (e.g. Kinase state
# on a GPCR family, Boundary with no DSSP available) is dropped rather than shown empty.
_SSE_TABLE_RENAME = {
    "family_id": "Family", "family_display": "Family", "target_stem": "Target",
    "target_display": "Target", "ligand_id": "Ligand",
    "motif_name": "Motif", "motif_kind": "Kind", "annotator_source": "Source",
    "n_residues": "N res", "ca_rmsd_A": "RMSD (A)", "centroid_shift_A": "Centroid delta (A)",
    "axis_rotation_deg": "Axis rot (deg)", "kink_angle_apo_deg": "Kink apo (deg)",
    "kink_angle_holo_deg": "Kink holo (deg)", "kink_angle_delta_deg": "Kink delta (deg)",
    "boundary_start_delta": "Start delta", "boundary_end_delta": "End delta",
    "n_flagged_phipsi_residues": "Flagged phi/psi",
    "dfg_state_apo": "DFG apo", "dfg_state_holo": "DFG holo", "dfg_state_changed": "DFG delta",
    "alphac_state_apo": "alphaC apo", "alphac_state_holo": "alphaC holo",
    "alphac_state_changed": "alphaC delta", "notes": "Notes",
}
_SSE_TABLE_GROUPS = {
    "family_id": "Identity", "family_display": "Identity", "target_stem": "Identity",
    "target_display": "Identity", "ligand_id": "Identity",
    "motif_name": "Identity", "motif_kind": "Identity", "annotator_source": "Identity",
    "n_residues": "Shift", "ca_rmsd_A": "Shift", "centroid_shift_A": "Shift",
    "axis_rotation_deg": "Helix geometry", "kink_angle_apo_deg": "Helix geometry",
    "kink_angle_holo_deg": "Helix geometry", "kink_angle_delta_deg": "Helix geometry",
    "boundary_start_delta": "Boundary", "boundary_end_delta": "Boundary",
    "n_flagged_phipsi_residues": "Backbone",
    "dfg_state_apo": "Kinase state", "dfg_state_holo": "Kinase state",
    "dfg_state_changed": "Kinase state", "alphac_state_apo": "Kinase state",
    "alphac_state_holo": "Kinase state", "alphac_state_changed": "Kinase state",
    "notes": "Notes",
}
_SSE_TABLE_GROUP_ORDER = ["Identity", "Shift", "Helix geometry", "Boundary", "Backbone",
                          "Kinase state", "Notes"]
_SSE_TABLE_TEXT_COLS = {"family_id", "family_display", "target_stem", "target_display", "ligand_id",
                         "motif_name", "motif_kind",
                         "annotator_source", "dfg_state_apo", "dfg_state_holo", "dfg_state_changed",
                         "alphac_state_apo", "alphac_state_holo", "alphac_state_changed", "notes"}
_SSE_TABLE_ALWAYS_KEEP = {"family_display", "target_display", "ligand_id", "motif_name", "motif_kind",
                          "annotator_source", "n_residues", "ca_rmsd_A", "centroid_shift_A"}
# Internal ids only needed for the raw CSV/cross-referencing, never shown as their own
# table column -- family_display/target_display substitute into their slots instead
# (same "readable label swaps in for the internal id" pattern as the main dashboard's
# Summary table; see BoltzMaker.py's _resolve_summary_table_columns).
_SSE_TABLE_HIDE = {"family_id", "target_stem"}


def _sse_table_label(col: str) -> str:
    return _SSE_TABLE_RENAME.get(col, col)


def _sse_table_group(col: str) -> str:
    return _SSE_TABLE_GROUPS.get(col, "Other")


def _resolve_sse_table_columns(df: pd.DataFrame) -> list:
    cols = [c for c in CSV_COLUMNS if c != "flagged_residues" and c not in _SSE_TABLE_HIDE
            and c in df.columns]
    kept = []
    for c in cols:
        if c not in _SSE_TABLE_ALWAYS_KEEP and df[c].isna().all():
            continue  # e.g. every Kinase-state column, dropped entirely for a GPCR family
        kept.append(c)
    kept.sort(key=lambda c: _SSE_TABLE_GROUP_ORDER.index(_sse_table_group(c)))
    return kept


def build_sse_table_html(df: pd.DataFrame) -> str:
    cols = _resolve_sse_table_columns(df)
    if not cols:
        return "<p>No columns to display.</p>"

    groups = [_sse_table_group(c) for c in cols]

    def group_header_row() -> str:
        cells, i = [], 0
        while i < len(groups):
            j = i
            while j < len(groups) and groups[j] == groups[i]:
                j += 1
            cells.append(f"<th colspan='{j - i}' class='ft-group'>{groups[i]}</th>")
            i = j
        return f"<tr>{''.join(cells)}</tr>"

    def column_header_row() -> str:
        cells, prev = [], None
        for c, g in zip(cols, groups):
            classes = ([] if g == prev else ["ft-group-start"]) + ([] if c in _SSE_TABLE_TEXT_COLS else ["ft-num"])
            cells.append(f"<th class='{' '.join(classes)}'>{_sse_table_label(c)}</th>")
            prev = g
        return f"<tr>{''.join(cells)}</tr>"

    def cell_html(row, c: str) -> str:
        v = row[c]
        if pd.isna(v):
            return _NA
        if c in _SSE_TABLE_TEXT_COLS:
            return str(v)
        return f"{v:.2f}" if isinstance(v, float) else str(v)

    def body_row(row) -> str:
        cells, prev = [], None
        for c, g in zip(cols, groups):
            classes = ([] if g == prev else ["ft-group-start"]) + ([] if c in _SSE_TABLE_TEXT_COLS else ["ft-num"])
            cells.append(f"<td class='{' '.join(classes)}'>{cell_html(row, c)}</td>")
            prev = g
        return f"<tr>{''.join(cells)}</tr>"

    sorted_df = df.sort_values(["ligand_id", "motif_kind", "motif_name"], kind="stable")
    body = "".join(body_row(row) for _, row in sorted_df.iterrows())
    return (f"<table class='full-table'><thead>{group_header_row()}{column_header_row()}</thead>"
            f"<tbody>{body}</tbody></table>")


def build_metrics_dataframe(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[CSV_COLUMNS]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, na_rep=_NA)


def write_family_status(family_status: dict, path: Path) -> None:
    path.write_text(json.dumps(family_status, indent=2))


def build_family_status_html(family_status: dict) -> str:
    """A small per-family coverage table -- every family in the campaign gets a row,
    including ones with no Apo structure: configured at all, so a missing family reads
    as "not configured" rather than silently vanishing from the dashboard.
    """
    if not family_status:
        return ""
    rows = []
    for fam_id, info in family_status.items():
        display = info.get("display", fam_id)
        label = _FAMILY_STATUS_LABELS.get(info.get("status"), info.get("status", _NA))
        message = info.get("message") or ""
        rows.append(f"<tr><td>{display}</td><td>{label}</td><td>{message}</td></tr>")
    return ("<table><thead><tr><th>Family</th><th>Status</th><th>Detail</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def compute_summary_stats(df: object) -> dict:
    """Campaign-wide roll-up over every computed motif row -- the "how much moved,
    overall" answer a per-motif table alone doesn't give at a glance.
    """
    if df is None or df.empty:
        return {}
    valid = df.dropna(subset=["ca_rmsd_A"])
    if valid.empty:
        return {}
    top = valid.loc[valid["ca_rmsd_A"].idxmax()]
    return {
        "n_targets": int(df["target_display"].nunique()),
        "n_motifs": int(len(valid)),
        "mean_rmsd": float(valid["ca_rmsd_A"].mean()),
        "median_rmsd": float(valid["ca_rmsd_A"].median()),
        "max_rmsd": float(top["ca_rmsd_A"]),
        "max_rmsd_label": f"{top['target_display']} / {top['motif_name']}",
        "mean_centroid_shift": float(valid["centroid_shift_A"].mean()),
        "n_flagged_phipsi": int(df["n_flagged_phipsi_residues"].fillna(0).sum()),
        "n_dfg_changed": int((df["dfg_state_changed"] == True).sum()),  # noqa: E712 -- explicit vs NaN/None
        "n_alphac_changed": int((df["alphac_state_changed"] == True).sum()),  # noqa: E712
    }


def build_summary_stats_html(stats: dict) -> str:
    if not stats:
        return "<p><em>No SSE metrics were computed for this campaign.</em></p>"
    return (
        "<ul>"
        f"<li><b>{stats['n_targets']}</b> target(s), <b>{stats['n_motifs']}</b> motif(s) compared</li>"
        f"<li>Mean Ca RMSD: <b>{stats['mean_rmsd']:.2f} A</b> (median {stats['median_rmsd']:.2f} A) "
        f"&mdash; largest shift: <b>{stats['max_rmsd']:.2f} A</b> at {stats['max_rmsd_label']}</li>"
        f"<li>Mean centroid shift: <b>{stats['mean_centroid_shift']:.2f} A</b></li>"
        f"<li>Flagged phi/psi outlier residues: <b>{stats['n_flagged_phipsi']}</b></li>"
        f"<li>Kinase state changes detected: <b>{stats['n_dfg_changed']}</b> DFG, "
        f"<b>{stats['n_alphac_changed']}</b> alphaC</li>"
        "</ul>"
    )


def write_pymol_script(target_stem: str, apo_path: Path, holo_path: Path, apo_chain: str,
                        holo_chain: str, motifs: list, rows: list, out_path: Path) -> None:
    """Plain-text .pml the user opens with their own PyMOL install -- no pymol import
    anywhere in the main venv. Loads both structures, colors/selects each motif, and
    labels motifs whose ca_rmsd_A exceeds _SIGNIFICANT_RMSD_A.
    """
    rmsd_by_motif = {r["motif_name"]: r.get("ca_rmsd_A") for r in rows}
    lines = [
        f"load {apo_path}, apo",
        f"load {holo_path}, holo",
        "hide everything",
        "show cartoon, apo or holo",
        "color grey80, apo",
        "color skyblue, holo",
        f"align apo and chain {apo_chain}, holo and chain {holo_chain}",
    ]
    palette = ["red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta",
               "salmon", "olive", "teal", "violet", "brown", "pink"]
    for i, motif in enumerate(motifs):
        color = palette[i % len(palette)]
        sel_name = f"motif_{motif.name}"
        resi_list = "+".join(str(r + 1) for r in motif.residues)  # back to 1-indexed for PyMOL
        lines.append(f"select {sel_name}, (apo or holo) and resi {resi_list}")
        lines.append(f"color {color}, {sel_name}")
        rmsd = rmsd_by_motif.get(motif.name)
        if rmsd is not None and rmsd >= _SIGNIFICANT_RMSD_A:
            mid_resi = motif.residues[len(motif.residues) // 2] + 1
            lines.append(f"label holo and resi {mid_resi} and name CA, "
                         f'"{motif.name} ({rmsd:.1f} A)"')
    lines += ["set label_size, 16", "set label_color, black", "zoom apo or holo"]
    out_path.write_text("\n".join(lines) + "\n")


def _motif_order(df: pd.DataFrame) -> list:
    # First-appearance order (not alphabetical) -- matches the order motifs were
    # originally annotated in, so the bar chart and heatmap agree with each other
    # (and with the per-motif table above them) instead of each picking their own.
    return list(dict.fromkeys(df["motif_name"]))


def _target_order(df: pd.DataFrame) -> list:
    return list(dict.fromkeys(df["target_display"]))


def _make_sse_shift_chart(df: pd.DataFrame, div_id: str) -> object:
    d = df.dropna(subset=["ca_rmsd_A"])
    if d.empty:
        return None
    fig = go.Figure()
    for target_display, group in d.groupby("target_display", sort=False):
        fig.add_trace(go.Bar(x=group["motif_name"], y=group["ca_rmsd_A"], name=target_display))
    fig.update_layout(barmode="group", legend=dict(font=dict(size=_TICK_FONTSIZE)))
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=_TICK_FONTSIZE),
                      categoryorder="array", categoryarray=_motif_order(d))
    fig.update_yaxes(title_text="Ca RMSD (A)", title_font=dict(size=_AXIS_LABEL_FONTSIZE),
                      tickfont=dict(size=_TICK_FONTSIZE))
    return _plotly_to_div(fig, div_id)


def _make_sse_heatmap(df: pd.DataFrame, div_id: str) -> object:
    # motif_name on x, target_display on y -- same axis convention as the shift chart
    # above (motif on the horizontal axis), and always rendered (not gated behind
    # having 2+ targets) so it covers the same full motif set the bar chart does,
    # even for a single-target campaign.
    d = df.dropna(subset=["ca_rmsd_A"])
    if d.empty:
        return None
    pivot = d.pivot_table(index="target_display", columns="motif_name", values="ca_rmsd_A", aggfunc="mean")
    pivot = pivot.reindex(index=_target_order(d), columns=_motif_order(d))
    fig = go.Figure(go.Heatmap(z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
                                colorscale="YlOrRd", colorbar=dict(title="Ca RMSD (A)")))
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=_TICK_FONTSIZE))
    fig.update_yaxes(tickfont=dict(size=_TICK_FONTSIZE))
    return _plotly_to_div(fig, div_id)


def write_sse_html(df: pd.DataFrame, path: Path, family_status: dict = None) -> None:
    parts = []

    status_html = build_family_status_html(family_status or {})
    if status_html:
        parts.append(f"<div class='md-card table-card'><h2>Family coverage</h2>{status_html}</div>")

    stats_html = build_summary_stats_html(compute_summary_stats(df))
    parts.append(f"<div class='md-card'><h2>Overall shift statistics</h2>{stats_html}</div>")

    if df is not None and not df.empty:
        table_html = build_sse_table_html(df)
        parts.append(f"<div class='md-card table-card'><h2>SSE motif shifts (apo vs holo)</h2>"
                     f"{table_html}<p><a href='boltz_sse_comparison.csv'>Download CSV</a></p></div>")

        chart_cards = []
        bar = _make_sse_shift_chart(df, "chart-sse-shift")
        if bar:
            chart_cards.append(f"<div class='md-card'><h2>Per-motif Ca RMSD</h2>{bar}</div>")
        heat = _make_sse_heatmap(df, "chart-sse-heatmap")
        if heat:
            chart_cards.append(f"<div class='md-card'><h2>Motif x target RMSD</h2>{heat}</div>")
        if chart_cards:
            parts.append(f"<div class='md-chart-grid'>{''.join(chart_cards)}</div>")

    if PLOTLY_JS_PATH.exists():
        plotly_script = f"<script>{PLOTLY_JS_PATH.read_text()}</script>"
    else:
        print("BoltzMaker: WARNING: vendor/plotly-2.35.2.min.js not found -- falling back to "
              "the plotly.js CDN, which is known not to render in some HTML-preview contexts")
        plotly_script = "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>"

    doc = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>BoltzMaker SSE Comparison | Marc C. Deller</title>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
        "&family=Roboto+Mono:wght@400;500&display=swap' rel='stylesheet'>"
        + plotly_script
        + f"<style>{_BRAND_CSS}</style></head><body>"
        + _BRAND_HEADER + "<main class='md-main'>" + "".join(parts) + "</main>" + _BRAND_FOOTER
        + "</body></html>"
    )
    path.write_text(doc)
