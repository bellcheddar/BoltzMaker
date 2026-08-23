"""The boundary between "BoltzMaker computes" and "the model narrates".

Every number a summary can contain is computed, rounded, given its units and turned
into a **string** here. Every ranking, every threshold judgement, every comparison is
decided here. What crosses into the model is prose-ready facts, and the model's only
job is to join them into sentences.

That is not fastidiousness. A language model asked to narrate `0.8417` will sometimes
write "roughly 0.84", sometimes "0.842", and occasionally "0.84, which is high" when
0.84 is not high for that metric. It will also, given two numbers, cheerfully compute
a third. A report that misstates a binding affinity is worse than no report, so the
model is never given the opportunity: it sees `"ipTM 0.84"` and has nothing to round,
and it sees `rank: "1 of 4"` rather than a list to sort.

Sizes are checked rather than assumed. The on-device context window is small, and a
40-ligand target would silently blow it, so `token_estimate()` exists and truncation
is explicit -- `ligands_omitted` is a field the instructions require the model to
mention, not a quiet `[:5]`.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


#: Apple shipped the on-device model with a 4,096-token window covering instructions,
#: prompt and output together. The split below reserves the remainder for
#: instructions, which are fixed and known.
CONTEXT_WINDOW_TOKENS = 4096
PROMPT_TOKEN_BUDGET = 2400
OUTPUT_TOKEN_BUDGET = 600

#: How many ligands a single target's block may carry before the rest are counted
#: into `ligands_omitted`. Chosen to sit inside PROMPT_TOKEN_BUDGET with room for a
#: long SSE note; `fits_budget()` is the real check.
MAX_LIGANDS_PER_BLOCK = 8


# ---------------------------------------------------------------------------
#  Formatting: the only place a float becomes text
# ---------------------------------------------------------------------------

def fmt(value: Any, digits: int = 3, unit: str = "", missing: str = "not measured") -> str:
    """A number as the model will see it, or an honest word if there isn't one.

    `missing` is spelled out rather than left blank because an empty string in a
    fact block reads to the model as a value it should invent.
    """
    if value is None or value == "":
        return missing
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return missing
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    if text in ("", "-"):
        text = "0"
    return f"{text} {unit}".strip()


def fmt_count(value: Any, singular: str, plural: str | None = None) -> str:
    """`"1 hydrogen bond"` / `"3 hydrogen bonds"` / `"no hydrogen bonds"`."""
    try:
        count = int(float(value))
    except (TypeError, ValueError):
        return f"an unrecorded number of {plural or singular + 's'}"
    if count == 0:
        return f"no {plural or singular + 's'}"
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural or singular + 's'}"


#: Anything that looks like a number in generated prose. `validate.py` uses the same
#: expression, so the gate and the block agree on what counts as a numeric token.
NUMERIC_TOKEN = re.compile(r"-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
#  The block
# ---------------------------------------------------------------------------

class Confidence(BaseModel):
    """Boltz's own scores, pre-judged.

    `interpretation` is the important field. Boltz publishes the [0, 1] range for
    these metrics but no official bands, so what counts as "well determined" is a
    decision this project has already made elsewhere (the dashboard's shield tiers)
    and must not be re-decided by a language model reading a bare 0.83.
    """

    model_config = ConfigDict(extra="forbid")

    confidence_score: str = Field(description='e.g. "0.831"')
    ptm: str
    iptm: str
    ligand_iptm: str
    complex_plddt: str
    interpretation: Literal[
        "well determined", "moderately determined", "poorly determined", "not applicable"
    ]


class LigandFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ligand_class: Literal["control", "experimental", "unspecified"] = "unspecified"
    role: str = "not specified"
    #: Pre-ranked. "2 of 4 by predicted potency" -- never a list for the model to sort.
    rank: str
    predicted_pic50: str
    pic50_spread: str
    binder_probability: str
    contacts_summary: str
    pocket: str = "unconstrained"


class PoseFact(BaseModel):
    """Only present when an experimental structure exists to compare against.

    The one number on a BoltzMaker dashboard that is not the model grading its own
    work, so it is worth its own type rather than a line in a summary string.
    """

    model_config = ConfigDict(extra="forbid")

    reference: str
    pose_rmsd: str
    site_rmsd: str
    verdict: Literal[
        "reproduces the experimental pose",
        "close to the experimental pose",
        "does not reproduce the experimental pose",
    ]


class SseFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str
    reference_state: str
    motif_count: str
    largest_shift: str
    note: str = ""


class FactBlock(BaseModel):
    """One target, ready to narrate."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    display_name: str
    receptor: str
    partners: str = "none"
    sequence_length: str

    confidence: Confidence
    ligands: list[LigandFact] = Field(default_factory=list)
    pose: PoseFact | None = None
    sse: SseFact | None = None

    #: Pre-computed, never inferred by the model. Each is a phrase, not a code.
    flags: list[str] = Field(default_factory=list)

    #: Explicit truncation. The instructions require the model to say so.
    ligands_omitted: int = 0

    #: Computed here, never by the model. It is a function of the pose verdict, the
    #: flags and the confidence band -- all of which are already decided above -- so
    #: leaving it to a language model was asking it to re-derive an if/else from data
    #: it had been handed. Measured over the six golden fixtures, it disagreed with the
    #: stated rule in three of them, while getting every ligand fact right. The model
    #: narrates this; it does not choose it.
    recommendation: Literal["proceed", "caution", "discard"] = "proceed"

    @field_validator("ligands")
    @classmethod
    def _cap_ligands(cls, value: list[LigandFact]) -> list[LigandFact]:
        if len(value) > MAX_LIGANDS_PER_BLOCK:
            raise ValueError(
                f"{len(value)} ligands in one block exceeds MAX_LIGANDS_PER_BLOCK "
                f"({MAX_LIGANDS_PER_BLOCK}); select the top N and set ligands_omitted "
                "so the omission is stated rather than hidden")
        return value

    # -- budget ------------------------------------------------------------

    def token_estimate(self) -> int:
        """Roughly how much of the window this block will occupy.

        Four characters per token is the usual English approximation and is close
        enough for a budget check: the question is "will this fit", not "exactly how
        many". Deliberately pessimistic -- the JSON punctuation is counted, because
        the model sees the JSON.
        """
        return math.ceil(len(self.to_prompt_json()) / 4)

    def fits_budget(self) -> bool:
        return self.token_estimate() <= PROMPT_TOKEN_BUDGET

    def to_prompt_json(self) -> str:
        """What actually crosses the boundary. Compact, and sorted so it is diffable.

        Compact is not tidiness, it is latency. Measured over the six golden fixtures
        on an M1 Max, indent=1 averaged 22.9 s per target against 11.8 s for the same
        facts with the whitespace removed -- a 49% saving for a 13% reduction in
        characters, because newlines and runs of spaces cost tokens out of all
        proportion to what they carry. The 15 s target in the plan is unreachable
        pretty-printed and comfortable compact.

        `to_pretty_json` exists for humans; nothing sends it to a model.
        """
        return json.dumps(self.model_dump(exclude_none=True),
                          separators=(",", ":"), sort_keys=True)

    def to_pretty_json(self) -> str:
        """For fixtures, diffs and eyeballs. Never for a prompt."""
        return json.dumps(self.model_dump(exclude_none=True), indent=1, sort_keys=True)

    def numeric_tokens(self) -> set[str]:
        """Every number this block contains, for the integrity gate to check against.

        Drawn from the block rather than from the source data, because the block is
        what the model was shown: a number it could not have seen is a number it
        invented, whatever the campaign CSV happens to hold.
        """
        return set(NUMERIC_TOKEN.findall(self.to_prompt_json()))
