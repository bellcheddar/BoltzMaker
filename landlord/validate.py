"""The numeric-integrity gate.

Every number appearing in generated prose must appear verbatim in the FactBlock it
was generated from. Anything else is an orphan: a figure the model produced that it
was never given, which means it rounded one, combined two, or invented it.

This is the check that makes the whole approach defensible. Phase 0 established that
the model restates numbers despite being instructed not to -- so the instruction
reduces the habit and this gate is what actually enforces correctness. A report that
misstates a binding affinity is worse than no report, and rejected output falls
through to the template, which cannot be wrong because it does no writing.

Deliberately strict in one direction only. A summary that omits a number is fine;
a summary that contains one nobody supplied is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .factblock import NUMERIC_TOKEN, FactBlock

#: Numbers a summary may use without them appearing in the block. These are the
#: small counting words a sentence needs to hold itself together -- "one sentence
#: per ligand", "the two receptors" -- not measurements. Kept tiny on purpose: every
#: entry here is a hole in the gate.
ALLOWED_BARE = {"0", "1", "2", "3"}


@dataclass
class Verdict:
    ok: bool
    orphans: list[str] = field(default_factory=list)
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def _numbers(text: str) -> list[str]:
    return NUMERIC_TOKEN.findall(text or "")


def _normalise(token: str) -> set[str]:
    """The forms a number may legitimately take between block and prose.

    `0.907` in the block and `0.907` in the text is the easy case. The awkward one is
    trailing-zero drift: a block saying `8.80` and prose saying `8.8` is the same
    measurement, and failing it would send correct output to the fallback for no
    reason. Rounding to fewer significant figures is *not* accepted -- `0.91` for
    `0.907` is a different number, and quietly allowing it is how a report comes to
    misstate a result.
    """
    forms = {token}
    if "." in token:
        trimmed = token.rstrip("0").rstrip(".")
        forms.add(trimmed or "0")
    return forms


def check(text: str, block: FactBlock) -> Verdict:
    """Every number in `text` must be one the block supplied."""
    supplied: set[str] = set()
    for token in block.numeric_tokens():
        supplied |= _normalise(token)

    orphans = []
    for token in _numbers(text):
        if token in ALLOWED_BARE:
            continue
        if not (_normalise(token) & supplied):
            orphans.append(token)

    if orphans:
        unique = sorted(set(orphans), key=orphans.index)
        return Verdict(
            ok=False, orphans=unique,
            reason=("generated text contains "
                    + ", ".join(unique[:6])
                    + ", which the fact block does not"))
    return Verdict(ok=True)


def check_summary(summary: dict, block: FactBlock) -> Verdict:
    """The same gate over every prose field of a generated summary.

    `recommendation` is skipped: it is copied from the block rather than generated,
    so checking it would only ever confirm that a copy is a copy.
    """
    parts: list[str] = []
    for key in ("confidence", "caveat"):
        parts.append(str(summary.get(key) or ""))
    parts.extend(str(note) for note in (summary.get("ligandNotes") or []))
    return check("\n".join(parts), block)
