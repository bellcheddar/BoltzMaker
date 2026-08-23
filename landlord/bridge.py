"""Talking to the Swift narrator, and never letting it break a campaign.

The contract with the rest of BoltzMaker is one-way: narration can fail in any manner
it likes -- binary missing, Apple Intelligence off, model still downloading, timeout,
crash, garbage on stdout, output that fails the numeric gate -- and the campaign
neither stops nor notices. Every one of those paths ends at the template.

That is why nothing here raises except in `model` mode, which exists precisely to make
failures loud when you are testing the model path.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import fallback, validate
from .config import NarrationConfig
from .factblock import FactBlock

log = logging.getLogger("landlord")

#: Exit codes the Swift side uses for the three availability states, so the reason can
#: be logged without parsing prose. See Availability.check() in Narrator.swift.
AVAILABILITY_CODES = {
    10: "this Mac cannot run Apple Intelligence",
    11: "Apple Intelligence is switched off in System Settings",
    12: "the on-device model is still downloading",
    13: "the model is unavailable for an unrecognised reason",
}


class NarrationUnavailable(RuntimeError):
    """Raised only in `model` mode. `auto` degrades instead."""


@dataclass
class Narration:
    target_id: str
    summary: dict
    generated_by: str          # "foundation-models" | "template"
    elapsed_s: float = 0.0
    note: str = ""             # why it fell back, when it did


def find_binary(explicit: str | Path | None = None) -> Path | None:
    """The built narrator, or None if this machine has no business running one."""
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    here = Path(__file__).resolve().parent.parent
    for candidate in (
        here / "swift/Landlord/.build/release/boltzmaker-landlord",
        here / "bin/boltzmaker-landlord",
    ):
        if candidate.is_file():
            return candidate
    return None


def available(binary: Path | None = None, timeout_s: int = 20) -> tuple[bool, str]:
    """Probe once. Returns (usable, why not)."""
    binary = binary or find_binary()
    if binary is None:
        return False, "the boltzmaker-landlord binary is not built for this machine"
    try:
        done = subprocess.run([str(binary), "check"], capture_output=True,
                              text=True, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run the narrator: {exc}"
    if done.returncode == 0:
        return True, ""
    return False, AVAILABILITY_CODES.get(done.returncode,
                                         (done.stderr or "").strip() or "unavailable")


def narrate(block: FactBlock, config: NarrationConfig | None = None,
            binary: Path | None = None) -> Narration:
    """One target. Always returns something; never raises in `auto`."""
    config = config or NarrationConfig()

    def template(note: str) -> Narration:
        return Narration(block.target_id, fallback.render_summary(block),
                         "template", note=note)

    if not config.enabled or config.mode == "off":
        return template("narration disabled")
    if config.mode == "template":
        return template("template mode")

    binary = binary or find_binary()
    usable, why = available(binary, timeout_s=min(config.timeout_s, 30))
    if not usable:
        if config.requires_model():
            raise NarrationUnavailable(why)
        log.info("landlord: falling back to the template -- %s", why)
        return template(why)

    with tempfile.TemporaryDirectory(prefix="landlord-") as tmp:
        block_path = Path(tmp) / f"{block.target_id}.json"
        block_path.write_text(block.to_prompt_json())
        try:
            done = subprocess.run(
                [str(binary), "narrate", "--in", str(block_path)],
                capture_output=True, text=True, timeout=config.timeout_s)
        except subprocess.TimeoutExpired:
            if config.requires_model():
                raise NarrationUnavailable(f"timed out after {config.timeout_s}s")
            log.info("landlord: narration timed out after %ss", config.timeout_s)
            return template(f"timed out after {config.timeout_s}s")
        except (OSError, subprocess.SubprocessError) as exc:
            if config.requires_model():
                raise NarrationUnavailable(str(exc))
            return template(f"narrator could not be run: {exc}")

    if done.returncode != 0:
        why = (done.stderr or "").strip().splitlines()[-1:] or ["no reason given"]
        if config.requires_model():
            raise NarrationUnavailable(why[0])
        log.info("landlord: narrator exited %s -- %s", done.returncode, why[0])
        return template(why[0])

    try:
        envelope = json.loads(done.stdout)
        summary = envelope["summary"]
    except (ValueError, KeyError, TypeError) as exc:
        if config.requires_model():
            raise NarrationUnavailable(f"unreadable output: {exc}")
        return template(f"narrator returned unreadable output: {exc}")

    # The gate. Model output that states a number nobody supplied does not ship, in
    # any mode -- `model` mode makes failures loud, it does not make them acceptable.
    verdict = validate.check_summary(summary, block)
    if not verdict:
        log.info("landlord: rejected generated summary for %s -- %s",
                 block.target_id, verdict.reason)
        return template(verdict.reason)

    return Narration(block.target_id, summary, "foundation-models",
                     elapsed_s=float(envelope.get("elapsedSeconds") or 0.0))


def _reduce_once(payload: str, config: NarrationConfig,
                 binary: Path | None) -> tuple[dict | None, str]:
    """One reduce call. Returns (summary, note); summary is None on any failure."""
    with tempfile.TemporaryDirectory(prefix="landlord-reduce-") as tmp:
        path = Path(tmp) / "reduce.json"
        path.write_text(payload)
        try:
            done = subprocess.run([str(binary), "reduce", "--in", str(path)],
                                  capture_output=True, text=True,
                                  timeout=config.timeout_s)
        except (OSError, subprocess.SubprocessError) as exc:
            return None, f"reduce could not run: {exc}"
    if done.returncode != 0:
        why = (done.stderr or "").strip().splitlines()[-1:] or ["no reason given"]
        return None, why[0]
    try:
        return json.loads(done.stdout)["summary"], ""
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"reduce returned unreadable output: {exc}"


def narrate_campaign(blocks, campaign_name: str,
                     config: NarrationConfig | None = None,
                     binary: Path | None = None) -> dict:
    """Map every target, then reduce the summaries into one campaign overview.

    Hierarchical when it has to be: chunks are sized to fit the window, and if there
    is more than one chunk their summaries are themselves reduced. Truncating instead
    would drop targets from the overview without saying so, which is the one thing a
    campaign summary must not do.

    Degrades the same way everything else here does. If any reduce call fails or its
    output fails the gate, the campaign overview comes from the template and the
    per-target summaries are unaffected.
    """
    from . import campaign as campaign_mod       # local: avoids a circular import

    config = config or NarrationConfig()
    stats = campaign_mod.summarise_stats(blocks, campaign_name)

    per_target = [narrate(b, config, binary) for b in blocks]
    summaries = [dict(n.summary, target_id=n.target_id) for n in per_target]

    def template_overview(note: str) -> dict:
        return {
            "campaign": campaign_name,
            "overview": fallback.render_campaign(stats),
            "keyFindings": stats.key_findings,
            "caveats": stats.flagged + ".",
            "generatedBy": "template",
            "note": note,
            "targets": [n.__dict__ for n in per_target],
        }

    if not config.wants_model():
        return template_overview("narration disabled or template mode")
    binary = binary or find_binary()
    usable, why = available(binary, timeout_s=min(config.timeout_s, 30))
    if not usable:
        if config.requires_model():
            raise NarrationUnavailable(why)
        return template_overview(why)

    level = summaries
    rounds = 0
    while True:
        rounds += 1
        chunks = campaign_mod.plan_chunks(level, stats)
        results, notes = [], []
        for chunk in chunks:
            summary, note = _reduce_once(chunk.to_prompt_json(), config, binary)
            if summary is None:
                notes.append(note); continue
            # The gate again. The reduce stage can invent a number exactly as the map
            # stage can, and its input is the union of the statistics and the summaries
            # it was shown -- each of which already passed against its own block.
            verdict = validate.check(
                "\n".join([summary.get("overview", ""), summary.get("caveats", "")]),
                _AllowedNumbers(chunk))
            if not verdict:
                notes.append(verdict.reason); continue
            results.append(summary)

        if not results:
            if config.requires_model():
                raise NarrationUnavailable("; ".join(notes) or "every reduce failed")
            return template_overview("; ".join(notes[:2]) or "every reduce failed")

        if len(results) == 1:
            final = results[0]
            return {
                "campaign": campaign_name,
                "overview": final.get("overview", ""),
                # Python's, always. See CampaignStats.key_findings.
                "keyFindings": stats.key_findings,
                "caveats": final.get("caveats", ""),
                "generatedBy": "foundation-models",
                "note": ("; ".join(notes) if notes else ""),
                "reduceRounds": rounds,
                "targets": [n.__dict__ for n in per_target],
            }

        # More than one chunk survived: summarise the summaries. Each becomes a
        # pseudo-target so the next round sees the same shape.
        level = [{"target_id": f"batch {i + 1}",
                  "confidence": r.get("overview", ""),
                  "ligandNotes": [],
                  "recommendation": "",
                  "caveat": r.get("caveats", "")}
                 for i, r in enumerate(results)]


class _AllowedNumbers:
    """Adapts a ReduceInput to the interface `validate.check` expects."""

    def __init__(self, chunk):
        self._tokens = chunk.numeric_tokens()

    def numeric_tokens(self):
        return self._tokens
