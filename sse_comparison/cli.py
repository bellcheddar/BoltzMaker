"""compare-sse orchestration: resolves which families/targets to compare, runs the
annotate -> superpose -> metrics -> report pipeline once per target, and writes the
campaign-level CSV/HTML/.pml outputs, plus a small family-coverage JSON sidecar.
Called both from BoltzMaker.py's `compare-sse` CLI dispatch and, since compare-sse is
now a core part of the pipeline, automatically from `analyze`/`all` (non-strict).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from BoltzMaker import _expand_targets, _family_display_name, _target_display_name  # noqa: E402

from .alignment import InsufficientReferenceRegionError, build_comparison_frame
from .annotators.gpcrdb import GPCRdbAnnotator
from .annotators.klifs import KLIFSAnnotator
from .annotators.pfam import PfamFallbackAnnotator
from .metrics import classify_state, compute_motif_row
from .report import (build_metrics_dataframe, write_csv, write_family_status,
                      write_pymol_script, write_sse_html)
from .structures import load_structure_for_comparison

_KINASE_DFG_ASP = "DFG"
_KINASE_CATALYTIC_LYS = "catalytic_Lys"
_KINASE_ALPHAC_GLU = "alphaC_Glu"


def _resolve_annotator_chain(family_type: str, sequence: str) -> list:
    """Ordered list of MotifAnnotator instances to try, most specific first. Explicit
    Family type: gpcr/kinase skips the cheap applies_to() pre-filter (the user already
    told us what this is); "auto" uses it to pick a sensible order. Pfam fallback is
    always last -- the universal, never-empty-by-design last resort.
    """
    gpcrdb, klifs, pfam = GPCRdbAnnotator(), KLIFSAnnotator(), PfamFallbackAnnotator()
    if family_type == "gpcr":
        return [gpcrdb, pfam]
    if family_type == "kinase":
        return [klifs, pfam]
    chain = []
    if gpcrdb.applies_to(sequence):
        chain.append(gpcrdb)
    if klifs.applies_to(sequence):
        chain.append(klifs)
    chain.append(pfam)
    return chain


def _motif_residue(motifs: list, name: str) -> object:
    for m in motifs:
        if m.name == name and m.residues:
            return m.residues[0]
    return None


def run_compare_sse(campaign: object, campaign_dir: Path, family_id: object = None,
                     target_stem: object = None, out_dir: object = None,
                     phi_psi_threshold: float = 30.0, dfg_distance_threshold: float = 8.0,
                     alphac_distance_threshold: float = 10.0, render_pymol: bool = True,
                     refresh_cache: bool = False, strict: bool = True) -> dict:
    """Returns {"df": DataFrame, "family_status": dict}.

    strict=True (the standalone `compare-sse` command's default): an explicit --family/
    --target that matches nothing, or a campaign where literally no family has anything
    comparable, raises SystemExit. strict=False (used when analyze/all auto-run this):
    never raises -- every family always gets a status entry, always written to
    boltz_sse_family_status.json, and the dashboard reports it instead of the whole
    pipeline aborting over an optional, additive feature.
    """
    out_dir = Path(out_dir) if out_dir else campaign_dir

    all_families = campaign.families if family_id is None else [f for f in campaign.families if f.id == family_id]
    if family_id is not None and not all_families:
        msg = f"no protein family '{family_id}' found"
        if strict:
            raise SystemExit(f"BoltzMaker: {msg}")
        print(f"BoltzMaker: WARNING: compare-sse: {msg}")
        return {"df": build_metrics_dataframe([]), "family_status": {}}

    all_targets = _expand_targets(campaign)
    rows, session_specs, family_status = [], [], {}

    for fam in all_families:
        if not fam.apo_structure:
            family_status[fam.id] = {"status": "no_apo_structure", "display": _family_display_name(fam),
                                      "message": "No 'Apo structure:' configured for this family"}
            continue
        apo_path = (campaign_dir / fam.apo_structure).resolve()
        if not apo_path.exists():
            family_status[fam.id] = {"status": "apo_not_found", "display": _family_display_name(fam),
                                      "message": f"Apo structure file not found: {apo_path}"}
            print(f"BoltzMaker: WARNING: apo structure '{apo_path}' not found for family "
                  f"'{fam.id}' -- skipped")
            continue

        annotator_chain = _resolve_annotator_chain(fam.family_type, fam.sequence)
        motifs, annotator_source = [], None
        for annotator in annotator_chain:
            try:
                found = annotator.annotate(fam.sequence, structure_path=str(apo_path), name_hint=fam.id)
            except Exception as exc:
                print(f"BoltzMaker: WARNING: {type(annotator).__name__} failed for '{fam.id}' ({exc})")
                found = []
            if found:
                motifs, annotator_source = found, annotator.family_type
                break
        if not motifs:
            family_status[fam.id] = {"status": "annotation_failed", "display": _family_display_name(fam),
                                      "message": "No motif annotation available (GPCRdb/KLIFS/PDBe all "
                                                 "failed or don't apply to this sequence)"}
            print(f"BoltzMaker: WARNING: no motif annotation available for family '{fam.id}' -- "
                  f"superposition/metrics need at least a stable reference region, skipped")
            continue

        fam_targets = [(f, lig) for f, lig in all_targets if f.id == fam.id]
        if target_stem:
            fam_targets = [(f, lig) for f, lig in fam_targets if f"{f.id}_{lig.id}" == target_stem]
            if not fam_targets:
                msg = f"target '{target_stem}' not found for family '{fam.id}'"
                if strict:
                    raise SystemExit(f"BoltzMaker: {msg}")
                family_status[fam.id] = {"status": "no_targets", "display": _family_display_name(fam),
                                          "message": msg}
                print(f"BoltzMaker: WARNING: {msg}")
                continue

        fam_row_count, fam_target_count, missing_holo = 0, 0, 0
        for fam2, lig in fam_targets:
            stem = f"{fam2.id}_{lig.id}"
            holo_path = campaign_dir / "boltz_cif" / f"{stem}_model_0.cif"
            if not holo_path.exists():
                missing_holo += 1
                continue

            try:
                apo = load_structure_for_comparison(apo_path, fam.apo_chain, fam.sequence)
                holo = load_structure_for_comparison(holo_path, fam.id, fam.sequence)
                frame = build_comparison_frame(apo, holo, fam.sequence, motifs, fam.family_type)
            except InsufficientReferenceRegionError as exc:
                print(f"BoltzMaker: WARNING: {stem}: {exc} -- skipped")
                continue
            except Exception as exc:
                print(f"BoltzMaker: WARNING: {stem}: failed to load/superpose ({exc}) -- skipped")
                continue

            dfg_apo = dfg_holo = dfg_changed = None
            alphac_apo = alphac_holo = alphac_changed = None
            if annotator_source == "kinase":
                dfg_pos = _motif_residue(motifs, _KINASE_DFG_ASP)
                lys_pos = _motif_residue(motifs, _KINASE_CATALYTIC_LYS)
                glu_pos = _motif_residue(motifs, _KINASE_ALPHAC_GLU)
                if dfg_pos is not None and lys_pos is not None:
                    dfg_apo, dfg_holo, dfg_changed = classify_state(frame, dfg_pos, lys_pos, dfg_distance_threshold)
                if glu_pos is not None and lys_pos is not None:
                    alphac_apo, alphac_holo, alphac_changed = classify_state(frame, glu_pos, lys_pos,
                                                                              alphac_distance_threshold)

            target_rows = []
            for motif in motifs:
                row = compute_motif_row(frame, motif, phi_psi_threshold)
                if not row:
                    continue
                row.update(family_id=fam.id, family_display=_family_display_name(fam),
                           target_stem=stem, target_display=_target_display_name(fam, lig.id),
                           ligand_id=lig.id,
                           annotator_source=annotator_source, dfg_state_apo=dfg_apo,
                           dfg_state_holo=dfg_holo, dfg_state_changed=dfg_changed,
                           alphac_state_apo=alphac_apo, alphac_state_holo=alphac_holo,
                           alphac_state_changed=alphac_changed, notes=None)
                target_rows.append(row)
            rows.extend(target_rows)
            fam_row_count += len(target_rows)
            fam_target_count += 1
            session_specs.append((stem, apo_path, holo_path, apo.chain.name, holo.chain.name,
                                   motifs, target_rows))
            print(f"BoltzMaker: compare-sse {stem}: {len(target_rows)} motif(s), "
                  f"annotator={annotator_source}")

        if fam_target_count:
            family_status[fam.id] = {"status": "ok", "display": _family_display_name(fam),
                                      "message": f"{fam_row_count} motif row(s) across {fam_target_count} "
                                                 f"target(s), annotator={annotator_source}"}
        elif missing_holo:
            family_status[fam.id] = {"status": "no_predicted_structures", "display": _family_display_name(fam),
                                      "message": "No predicted (holo) structures yet for this family's "
                                                 "targets -- run `analyze`/`run` first"}
        else:
            family_status[fam.id] = {"status": "no_targets", "display": _family_display_name(fam),
                                      "message": "No targets defined for this family"}

    df = build_metrics_dataframe(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(df, out_dir / "boltz_sse_comparison.csv")
    write_family_status(family_status, out_dir / "boltz_sse_family_status.json")

    if render_pymol and session_specs:
        sessions_dir = out_dir / "boltz_sse_comparison_sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        for stem, apo_path, holo_path, apo_chain, holo_chain, motifs, target_rows in session_specs:
            write_pymol_script(stem, apo_path, holo_path.resolve(), apo_chain, holo_chain,
                                motifs, target_rows, sessions_dir / f"{stem}.pml")
        print(f"BoltzMaker: wrote {len(session_specs)} PyMOL session script(s) to {sessions_dir}")

    write_sse_html(df, out_dir / "boltz_sse_comparison.html", family_status)
    print(f"BoltzMaker: compare-sse wrote {out_dir / 'boltz_sse_comparison.csv'} and "
          f"{out_dir / 'boltz_sse_comparison.html'}")

    if not rows:
        msg = "compare-sse produced no comparable targets"
        status_path = out_dir / "boltz_sse_family_status.json"
        if strict and family_id is None and target_stem is None:
            raise SystemExit(f"BoltzMaker: {msg} -- see {status_path} for why.")
        print(f"BoltzMaker: WARNING: {msg} -- see {status_path} for why.")

    return {"df": df, "family_status": family_status}
