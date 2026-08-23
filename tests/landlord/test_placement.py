"""INV-1 and INV-2, measured rather than asserted in prose.

Opt-in, and never in CI. `powermetrics` needs root, so these are marked `hardware`
and skipped unless you ask for them:

    sudo -E .venv/bin/pytest tests/landlord/test_placement.py -m hardware

Keep the machine otherwise idle. A Boltz campaign in the background makes the GPU
baseline meaningless, which is the one number these tests exist to protect.

A note on what can and cannot be measured here, because it shaped the tests. The plan
asks for "ANE power delta > 0". On this M1 Max that is not obtainable: `powermetrics`
describes `ane_power` as the "dedicated rail ane power" sampler and this SoC exposes no
such rail, so no ANE row is emitted at all. The absence is not a zero, and asserting
against it would be asserting against a missing measurement. INV-2 is therefore tested
by attribution instead -- where the CPU time goes -- which is available without root
and is arguably the more direct question anyway.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BINARY = REPO / "swift/Landlord/.build/release/boltzmaker-landlord"
FIXTURES = REPO / "tests/fixtures/landlord"

pytestmark = pytest.mark.hardware


def _facts(tmp_path: Path) -> Path:
    """The golden fixtures as compact prompt JSON, which is what ships to the model."""
    sys.path.insert(0, str(REPO))
    from landlord.factblock import FactBlock

    out = tmp_path / "facts"
    out.mkdir()
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text())
        payload.pop("_why_this_fixture", None)
        out.joinpath(path.name).write_text(
            FactBlock.model_validate(payload).to_prompt_json())
    return out


def _sample_power(seconds: int) -> dict[str, float]:
    """Mean mW per rail over `seconds`, from powermetrics. Needs root."""
    done = subprocess.run(
        ["powermetrics", "--samplers", "gpu_power,ane_power", "-i", "500",
         "-n", str(seconds * 2)],
        capture_output=True, text=True, timeout=seconds * 4 + 30)
    totals: dict[str, list[float]] = {}
    for line in done.stdout.splitlines():
        match = re.match(r"^(GPU|ANE) Power:\s+([0-9.]+)\s*mW", line.strip())
        if match:
            totals.setdefault(match.group(1), []).append(float(match.group(2)))
    return {rail: sum(v) / len(v) for rail, v in totals.items() if v}


@pytest.fixture(scope="module")
def binary_available():
    if not BINARY.is_file():
        pytest.skip("boltzmaker-landlord is not built")
    if subprocess.run([str(BINARY), "check"], capture_output=True).returncode != 0:
        pytest.skip("the on-device model is not available on this machine")


def test_inv1_narration_does_not_touch_the_gpu(binary_available, tmp_path):
    """INV-1: no Metal device is created, so nothing contends with a campaign.

    The invariant the whole design rests on. If it fails, narration cannot run
    alongside folding and Landlord becomes a post-campaign step.
    """
    if os.geteuid() != 0:
        pytest.skip("powermetrics needs root; run this file under sudo")
    if not shutil.which("powermetrics"):
        pytest.skip("powermetrics not present")

    idle = _sample_power(5)
    assert "GPU" in idle, "powermetrics reported no GPU rail; cannot judge INV-1"

    facts = _facts(tmp_path)
    worker = subprocess.Popen(
        ["sudo", "-u", os.environ.get("SUDO_USER", ""), str(BINARY), "batch",
         "--in-dir", str(facts), "--out-dir", str(tmp_path / "out"),
         "--concurrency", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    time.sleep(1)
    busy = _sample_power(8)
    _, stderr = worker.communicate(timeout=600)

    assert "model unavailable" not in stderr, (
        "the workload never ran, so these samples are idle against idle. "
        "Apple Intelligence availability is per-user and this must not run as root.")
    assert stderr.count("OK") >= 1, f"no target narrated: {stderr[-300:]}"

    # Generous: the machine is not quiesced and GPU power moves on its own. The
    # failure this guards against is narration lighting up the GPU, which would be a
    # large rise, not a few mW of desktop noise.
    assert busy["GPU"] <= idle["GPU"] + 50, (
        f"GPU power rose during narration ({idle['GPU']:.1f} -> {busy['GPU']:.1f} mW); "
        "INV-1 violated, narration would contend with a running campaign")


def test_inv2_inference_is_not_on_the_cpu(binary_available, tmp_path):
    """INV-2/INV-3, by attribution rather than by a rail this SoC does not expose.

    If the model were running on the CPU, generating several hundred words would cost
    tens of core-seconds. Measured here it costs a few, spread across the Apple
    inference daemons, with `aned` -- the Neural Engine driver -- among them. Combined
    with INV-1 ruling out the GPU, that places the work on the ANE.
    """
    def cpu_times() -> dict[str, float]:
        out = {}
        listing = subprocess.run(["ps", "-Ao", "pid,time,comm"],
                                 capture_output=True, text=True).stdout
        for line in listing.splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            pid, clock, comm = parts
            bits = clock.split(":")
            try:
                secs = float(bits[-1]) + 60 * float(bits[-2])
                if len(bits) > 2:
                    secs += 3600 * float(bits[-3])
            except ValueError:
                continue
            out[pid] = (secs, comm.rsplit("/", 1)[-1])
        return out

    facts = _facts(tmp_path)
    before = cpu_times()
    started = time.time()
    done = subprocess.run(
        [str(BINARY), "batch", "--in-dir", str(facts),
         "--out-dir", str(tmp_path / "out"), "--concurrency", "1"],
        capture_output=True, text=True, timeout=900)
    wall = time.time() - started
    after = cpu_times()
    assert done.stderr.count("OK") >= 1, "no target narrated"

    gained = {}
    for pid, (secs, comm) in after.items():
        delta = secs - before.get(pid, (0.0, comm))[0]
        if delta > 0.01:
            gained[comm] = gained.get(comm, 0.0) + delta

    inference = {c: d for c, d in gained.items() if any(
        k in c.lower() for k in
        ("ane", "neural", "espresso", "coreml", "model", "generative",
         "intelligence", "inference"))}
    total = sum(inference.values())

    assert inference, "no Apple inference daemon used any CPU; did narration happen?"
    assert "aned" in inference, (
        f"the ANE daemon did no work: {sorted(inference)}. "
        "Inference may not be landing on the Neural Engine.")
    # Inference on the CPU would be a large multiple of wall time across cores, not a
    # small fraction of one.
    assert total < wall * 0.5, (
        f"the inference path used {total:.1f}s CPU over {wall:.1f}s wall, too much for "
        "orchestration alone; the model may be running on the CPU")
