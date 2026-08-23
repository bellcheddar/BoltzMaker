"""Rolling a campaign's per-target summaries up into one.

Map-reduce, because the context window forbids narrating twenty targets in one pass.
The map stage is Phase 2: one summary per target, already gated. This is the reduce.

The statistics are computed here, in Python, for the same reason every number in a
FactBlock is: counting how many targets were flagged is arithmetic, and arithmetic is
not what a language model is for. What the model gets is a tally it must narrate and a
set of sentences it must condense -- never a list to count.

Chunk sizes are small, and measured rather than guessed. Phase 2 found the serialised
schema alone costs roughly 3,200 of the 4,096-token window, which leaves far less for
content than the plan's "~30 targets" assumed. Beyond one chunk the reduce is
hierarchical: summarise batches, then summarise the batch summaries.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field

from .factblock import NUMERIC_TOKEN, FactBlock

#: How many per-target summaries go into one reduce call. Deliberately conservative:
#: the window has to hold the instructions, the serialised schema, the statistics and
#: this many summaries, and overflowing it fails the whole roll-up rather than
#: degrading. `plan_chunks` checks the real size and shrinks further if needed.
SUMMARIES_PER_CHUNK = 4

#: The reduce prompt's share of the window, after schema and instructions.
REDUCE_PROMPT_BUDGET = 700


@dataclass
class CampaignStats:
    """Everything countable about a campaign, counted here.

    Strings throughout, as in a FactBlock, so the model has nothing to recompute.
    """

    campaign_name: str
    targets: str
    receptors: str
    ligands: str
    verdicts: str
    confidence_spread: str
    flagged: str
    pose_validated: str
    top_by_potency: list[str] = field(default_factory=list)

    #: Written here, not narrated. Every campaign-level finding is a tally, and a
    #: tally is arithmetic. Measured: asked to compose these, the model wrote "6
    #: targets were marked discard" when 6 was the *caution* count and 4 was discard,
    #: and "confidence below threshold for 10 targets" when 10 was the flagged count
    #: and 6 was the confidence one. Both numbers were present in its input, so the
    #: numeric gate -- which checks that a number was supplied, not that it was
    #: attached to the right noun -- passed them both. Composing them here removes the
    #: whole class of error rather than trying to detect it.
    key_findings: list[str] = field(default_factory=list)

    #: (label, value) pairs for tabular display. The fields above are written to be
    #: narrated -- whole sentences -- which makes them poor table cells. These are the
    #: same facts as short values, so the report can lay them out as a table without
    #: the card having to unpick prose it was handed.
    rows: list[tuple[str, str]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, separators=(",", ":"), sort_keys=True)

    def numeric_tokens(self) -> set[str]:
        return set(NUMERIC_TOKEN.findall(self.to_json()))


def summarise_stats(blocks: list[FactBlock], campaign_name: str) -> CampaignStats:
    """Count the campaign. No judgement here that a block has not already made."""
    with_ligand = [b for b in blocks if b.ligands]
    receptors = sorted({b.receptor for b in blocks})
    ligands = sorted({l.name for b in blocks for l in b.ligands})
    verdicts = Counter(b.recommendation for b in blocks)
    bands = Counter(b.confidence.interpretation for b in blocks)
    flagged = [b for b in blocks if b.flags]
    posed = [b for b in blocks if b.pose]
    reproduced = [b for b in posed
                  if b.pose and b.pose.verdict == "reproduces the experimental pose"]

    ranked = sorted(
        ((l.name, b.display_name, l.predicted_pic50)
         for b in with_ligand for l in b.ligands
         if l.predicted_pic50 not in ("", "not measured")),
        key=lambda row: float(row[2]), reverse=True)[:3]

    return CampaignStats(
        campaign_name=campaign_name,
        targets=f"{len(blocks)} predicted targets, {len(with_ligand)} with a ligand",
        receptors=f"{len(receptors)}: " + ", ".join(receptors),
        ligands=(f"{len(ligands)}: " + ", ".join(ligands)) if ligands else "none",
        verdicts=", ".join(f"{n} {v}" for v, n in verdicts.most_common()),
        confidence_spread=", ".join(f"{n} {band}" for band, n in bands.most_common()),
        flagged=(f"{len(flagged)} of {len(blocks)} targets carry at least one flag"
                 if flagged else "no target was flagged"),
        pose_validated=(
            f"{len(posed)} targets had an experimental structure to compare against; "
            f"{len(reproduced)} reproduced the experimental pose"
            if posed else "no target had an experimental structure to compare against"),
        top_by_potency=[f"{name} on {target}, predicted pIC50 {value}"
                        for name, target, value in ranked],
        key_findings=_findings(blocks, verdicts, bands, flagged, posed, reproduced),
        rows=[
            ("Targets", f"{len(blocks)} predicted, {len(with_ligand)} with a ligand"),
            ("Receptors", ", ".join(receptors) or "none"),
            ("Ligands", ", ".join(ligands) or "none"),
            ("Verdicts", ", ".join(f"{n} {v}" for v, n in verdicts.most_common())),
            ("Confidence", ", ".join(f"{n} {b}" for b, n in bands.most_common())),
            ("Flagged", f"{len(flagged)} of {len(blocks)}"),
            ("Pose validated",
             (f"{len(reproduced)} of {len(posed)} reproduced the experimental pose"
              if posed else "no experimental structure to compare against")),
        ],
    )


def _findings(blocks, verdicts, bands, flagged, posed, reproduced) -> list[str]:
    """The campaign-level facts, as finished sentences."""
    total = len(blocks)
    out = [
        f"Of {total} targets, {verdicts.get('proceed', 0)} are marked proceed, "
        f"{verdicts.get('caution', 0)} caution and {verdicts.get('discard', 0)} discard.",
        f"{bands.get('well determined', 0)} of {total} targets are well determined; "
        f"{total - bands.get('well determined', 0)} are not.",
    ]
    if flagged:
        out.append(f"{len(flagged)} of {total} targets carry at least one flag.")
    if posed:
        out.append(
            f"{len(posed)} targets could be checked against an experimental structure, "
            f"and {len(reproduced)} reproduced the experimental pose.")
    return out


@dataclass
class ReduceInput:
    """One reduce call's worth: the statistics plus some per-target sentences."""

    stats: CampaignStats
    summaries: list[dict]

    def to_prompt_json(self) -> str:
        return json.dumps(
            {"campaign": json.loads(self.stats.to_json()),
             "target_summaries": [
                 {"target": s.get("target_id", ""),
                  "confidence": s.get("confidence", ""),
                  "ligands": s.get("ligandNotes", []),
                  "verdict": s.get("recommendation", ""),
                  "caveat": s.get("caveat", "")}
                 for s in self.summaries]},
            separators=(",", ":"), sort_keys=True)

    def token_estimate(self) -> int:
        return math.ceil(len(self.to_prompt_json()) / 4)

    def numeric_tokens(self) -> set[str]:
        """What the reduce stage is allowed to say.

        The union of the statistics and the per-target summaries it was shown -- and
        those summaries already passed the gate against their own blocks, so nothing
        laundered in through the map stage.
        """
        return set(NUMERIC_TOKEN.findall(self.to_prompt_json()))


def plan_chunks(summaries: list[dict], stats: CampaignStats,
                per_chunk: int = SUMMARIES_PER_CHUNK) -> list[ReduceInput]:
    """Split into reduce calls that actually fit, rather than assuming they do.

    Shrinks the chunk when a batch turns out too large -- a campaign of verbose
    summaries would otherwise overflow silently and fail the whole roll-up.
    """
    chunks: list[ReduceInput] = []
    index = 0
    while index < len(summaries):
        size = per_chunk
        while size > 1:
            candidate = ReduceInput(stats, summaries[index:index + size])
            if candidate.token_estimate() <= REDUCE_PROMPT_BUDGET:
                break
            size -= 1
        chunk = ReduceInput(stats, summaries[index:index + size])
        chunks.append(chunk)
        index += size
    return chunks
