"""Output layer for compare-sse: CSV/DataFrame, a PyMOL .pml script per target, Plotly
charts, and a standalone self-contained HTML report -- deliberately separate from the
main boltz_dashboard.html (see PROJECT_PLAN notes: compare-sse is an explicitly opt-in
command most campaigns won't use, so it stays fully decoupled from the main dashboard
code path rather than complicating write_html for every campaign).
"""

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
    "family_id", "target_stem", "ligand_id", "motif_name", "motif_kind", "annotator_source",
    "n_residues", "ca_rmsd_A", "centroid_shift_A", "axis_rotation_deg", "kink_angle_apo_deg",
    "kink_angle_holo_deg", "kink_angle_delta_deg", "boundary_start_delta", "boundary_end_delta",
    "n_flagged_phipsi_residues", "flagged_residues", "dfg_state_apo", "dfg_state_holo",
    "dfg_state_changed", "alphac_state_apo", "alphac_state_holo", "alphac_state_changed", "notes",
]

_SIGNIFICANT_RMSD_A = 2.0  # motifs above this get labeled in the .pml script


def build_metrics_dataframe(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[CSV_COLUMNS]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


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


def _make_sse_shift_chart(df: pd.DataFrame, div_id: str) -> object:
    d = df.dropna(subset=["ca_rmsd_A"])
    if d.empty:
        return None
    fig = go.Figure()
    for target_stem, group in d.groupby("target_stem"):
        fig.add_trace(go.Bar(x=group["motif_name"], y=group["ca_rmsd_A"], name=target_stem))
    fig.update_layout(barmode="group", legend=dict(font=dict(size=_TICK_FONTSIZE)))
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=_TICK_FONTSIZE))
    fig.update_yaxes(title_text="Ca RMSD (A)", title_font=dict(size=_AXIS_LABEL_FONTSIZE),
                      tickfont=dict(size=_TICK_FONTSIZE))
    return _plotly_to_div(fig, div_id)


def _make_sse_heatmap(df: pd.DataFrame, div_id: str) -> object:
    d = df.dropna(subset=["ca_rmsd_A"])
    if d.empty or d["target_stem"].nunique() < 2:
        return None
    pivot = d.pivot_table(index="motif_name", columns="target_stem", values="ca_rmsd_A", aggfunc="mean")
    fig = go.Figure(go.Heatmap(z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
                                colorscale="YlOrRd", colorbar=dict(title="Ca RMSD (A)")))
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=_TICK_FONTSIZE))
    fig.update_yaxes(tickfont=dict(size=_TICK_FONTSIZE))
    return _plotly_to_div(fig, div_id)


def write_sse_html(df: pd.DataFrame, path: Path) -> None:
    parts = ["<div class='md-card table-card'><h2>SSE motif shifts (apo vs holo)</h2>",
             df.drop(columns=["flagged_residues"], errors="ignore").to_html(index=False, na_rep=""),
             "<p><a href='boltz_sse_comparison.csv'>Download CSV</a></p></div>"]

    chart_cards = []
    bar = _make_sse_shift_chart(df, "chart-sse-shift")
    if bar:
        chart_cards.append(f"<div class='md-card'><h2>Per-motif Ca RMSD</h2>{bar}</div>")
    heat = _make_sse_heatmap(df, "chart-sse-heatmap")
    if heat:
        chart_cards.append(f"<div class='md-card'><h2>Motif x target RMSD</h2>{heat}</div>")
    if chart_cards:
        parts.insert(0, f"<div class='md-chart-grid'>{''.join(chart_cards)}</div>")

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
