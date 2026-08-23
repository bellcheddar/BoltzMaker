"""Landlord's settings, and what each mode promises.

`auto` is the default and the only one most people should need: probe once, use the
model if it is there, fall back silently if it is not. The explicit modes exist for
the two cases where silence is wrong -- proving the model path works (`model`, which
fails loudly), and pinning a machine to the template so output is byte-reproducible
(`template`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["auto", "model", "template", "off"]


@dataclass
class NarrationConfig:
    enabled: bool = True

    #: auto     -- model if available, template otherwise. Never fails a campaign.
    #: model    -- model only. Raises if unavailable, for testing the model path.
    #: template -- template only. Deterministic, no ANE, no Swift binary needed.
    #: off      -- no narration at all.
    mode: Mode = "auto"

    #: Measured on an M1 Max: concurrency 2 was *slower* per target than 1 (30.7s
    #: against 6.6-13.5s), so the default is 1 until Phase 5 says otherwise. The plan
    #: assumed 2 would help; on this hardware it contends instead.
    concurrency: int = 1

    #: Generous. A cold start alone was 15.4s, and the machine may be running a
    #: campaign at the same time -- which is the whole point of the utility QoS.
    timeout_s: int = 120

    def wants_model(self) -> bool:
        return self.enabled and self.mode in ("auto", "model")

    def requires_model(self) -> bool:
        return self.enabled and self.mode == "model"
