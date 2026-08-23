"""Turn a finished campaign's analysis output into FactBlocks.

This is where every judgement gets made, so that none of them has to be made later
by a language model: which ligand ranks where, whether 0.83 counts as well
determined, whether a 24 Angstrom pose "reproduces" anything, which flags apply.

Reads what `analyze` already wrote -- `boltz_summary.csv`, `boltz_sse_comparison.csv`
and `boltz_pose_pairs/index.json`. Nothing here recomputes science; it selects,
rounds and words.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .factblock import (
    MAX_LIGANDS_PER_BLOCK, Confidence, FactBlock, LigandFact, PoseFact, SseFact,
    fmt, fmt_count,
)

#: Where "well determined" stops. Matches the dashboard's own shield tiers, so a
#: narrated summary and the report it describes cannot disagree about the same run.
WELL_DETERMINED = 0.80
POORLY_DETERMINED = 0.60

#: The long-standing convention for "this reproduces the crystal structure", and the
#: figure the README quotes. Beyond the second bound the pose is simply elsewhere.
POSE_REPRODUCES_A = 2.0
POSE_CLOSE_A = 5.0


def _f(row: dict, key: str):
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _interpret(score: float | None) -> str:
    if score is None:
        return "not applicable"
    if score >= WELL_DETERMINED:
        return "well determined"
    if score >= POORLY_DETERMINED:
        return "moderately determined"
    return "poorly determined"


def _contacts_summary(row: dict) -> str:
    """PLIP's counts as one readable clause, with the zero cases handled.

    Written out rather than left as a dict because the model would otherwise have to
    decide how to phrase "pi_stacks: 0", and the interesting answer is to not
    mention it at all.
    """
    parts = []
    for key, singular in (
        ("plip_hydrophobic_count", "hydrophobic contact"),
        ("plip_hydrogen_bonds_count", "hydrogen bond"),
        ("plip_pi_stacks_count", "pi-stack"),
        ("plip_salt_bridges_count", "salt bridge"),
        ("plip_pi_cation_count", "pi-cation interaction"),
        ("plip_halogen_bonds_count", "halogen bond"),
    ):
        count = _f(row, key)
        if count:
            parts.append(fmt_count(count, singular))
    total = _f(row, "plip_total_count")
    if total is None:
        return "interaction analysis not run"
    if not parts:
        return "no interactions detected"
    return f"{int(total)} in total: " + ", ".join(parts)


def _pose_verdict(rmsd: float) -> str:
    if rmsd <= POSE_REPRODUCES_A:
        return "reproduces the experimental pose"
    if rmsd <= POSE_CLOSE_A:
        return "close to the experimental pose"
    return "does not reproduce the experimental pose"


def _flags(row: dict, pose: PoseFact | None) -> list[str]:
    """Phrases, not codes. The model is told to mention them, so they must read."""
    out: list[str] = []
    confidence = _f(row, "confidence_score")
    ligand_iptm = _f(row, "ligand_iptm")
    spread = _f(row, "pIC50_ensemble_std")

    if confidence is not None and confidence < WELL_DETERMINED:
        out.append("overall confidence is below the well-determined threshold")
    if ligand_iptm is not None and ligand_iptm < 0.7:
        out.append("the ligand is poorly placed relative to the receptor")
    if spread is not None and spread >= 0.8:
        out.append("the predicted potency varies widely across the ensemble")
    if pose is not None and pose.verdict == "does not reproduce the experimental pose":
        out.append("the predicted pose disagrees with the experimental structure")
    if (row.get("plip_status") or "").strip().lower() not in ("", "ok", "done"):
        out.append("interaction analysis did not complete for this target")
    return out


def build_blocks(campaign_dir: Path, max_ligands: int = MAX_LIGANDS_PER_BLOCK
                 ) -> list[FactBlock]:
    """One FactBlock per predicted target, ligands ranked and capped."""
    campaign_dir = Path(campaign_dir)
    rows = list(csv.DictReader((campaign_dir / "boltz_summary.csv").open()))

    poses: dict[str, dict] = {}
    index = campaign_dir / "boltz_pose_pairs" / "index.json"
    if index.is_file():
        for pair in json.loads(index.read_text()).get("pairs", []):
            poses[pair["stem"]] = pair

    sse_rows: dict[str, list[dict]] = {}
    sse_csv = campaign_dir / "boltz_sse_comparison.csv"
    if sse_csv.is_file():
        for row in csv.DictReader(sse_csv.open()):
            sse_rows.setdefault(row["target_stem"], []).append(row)

    # Ranking is done here, once, over the whole campaign. Each ligand then carries
    # its own position as a phrase and the model never sees a list to sort.
    scored = [(r, _f(r, "pIC50_ensemble_mean")) for r in rows if r.get("ligand_id")]
    ordered = sorted((r for r, v in scored if v is not None),
                     key=lambda r: _f(r, "pIC50_ensemble_mean"), reverse=True)
    rank_of = {r["target_id"]: i + 1 for i, r in enumerate(ordered)}
    ranked_total = len(ordered)

    blocks: list[FactBlock] = []
    for row in rows:
        stem = row["target_id"]
        pose = None
        if stem in poses:
            pair = poses[stem]
            pose = PoseFact(
                reference=str(pair.get("reference", "an experimental structure")),
                pose_rmsd=fmt(pair.get("pose"), 2, "Å"),
                site_rmsd=fmt(pair.get("site"), 2, "Å"),
                verdict=_pose_verdict(float(pair.get("pose", 99))),
            )

        sse = None
        motifs = sse_rows.get(stem) or []
        if motifs:
            worst = max(motifs, key=lambda m: _f(m, "ca_rmsd_A") or 0.0)
            sse = SseFact(
                reference=(row.get("family_group") or "the apo reference"),
                reference_state="compared against this family's apo or inactive reference",
                motif_count=fmt_count(len(motifs), "motif"),
                largest_shift=(f"{worst.get('motif_name', 'a motif')} moved "
                               f"{fmt(_f(worst, 'ca_rmsd_A'), 2, 'Å')}"),
            )

        ligands: list[LigandFact] = []
        if row.get("ligand_id"):
            ligands.append(LigandFact(
                name=row["ligand_id"],
                ligand_class=(row.get("ligand_class") or "unspecified").strip() or "unspecified",
                role=(row.get("ligand_role") or "not specified").strip() or "not specified",
                rank=(f"{rank_of[stem]} of {ranked_total} by predicted potency"
                      if stem in rank_of else "not ranked"),
                predicted_pic50=fmt(_f(row, "pIC50_ensemble_mean"), 2),
                pic50_spread=fmt(_f(row, "pIC50_ensemble_std"), 2),
                binder_probability=fmt(_f(row, "affinity_probability_binary"), 3),
                contacts_summary=_contacts_summary(row),
                pocket=(row.get("pocket") or "unconstrained").strip() or "unconstrained",
            ))

        confidence_score = _f(row, "confidence_score")
        flags = _flags(row, pose)
        if pose is not None and pose.verdict == "does not reproduce the experimental pose":
            recommendation = "discard"
        elif flags or _interpret(confidence_score) != "well determined":
            recommendation = "caution"
        else:
            recommendation = "proceed"
        blocks.append(FactBlock(
            target_id=stem,
            display_name=row.get("display_name") or stem,
            receptor=row.get("family_group") or row.get("family_id") or "unnamed",
            partners=(row.get("partner_ids") or "none").strip() or "none",
            sequence_length="not recorded",
            confidence=Confidence(
                confidence_score=fmt(confidence_score),
                ptm=fmt(_f(row, "ptm")),
                iptm=fmt(_f(row, "iptm")),
                ligand_iptm=fmt(_f(row, "ligand_iptm")),
                complex_plddt=fmt(_f(row, "complex_plddt")),
                interpretation=_interpret(confidence_score),
            ),
            ligands=ligands[:max_ligands],
            ligands_omitted=max(0, len(ligands) - max_ligands),
            pose=pose,
            sse=sse,
            flags=flags,
            recommendation=recommendation,
        ))
    return blocks
