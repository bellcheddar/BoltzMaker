# BoltzMaker "Landlord" — On-Device Narration Sidecar

**Implementation plan for Claude Code**
Target repo: `github.com/bellcheddar/BoltzMaker`
Author: Marc C. Deller, D.Phil.

> Naming note: BoltzMaker is named after Timothy Taylor's Boltmaker. The narration
> sidecar is **Landlord**, after the same brewery's flagship. Rename freely if you
> prefer something else, but keep it consistent across binary, module and config keys.

---

## 1. Objective

Generate per-target and per-campaign natural-language summaries of completed Boltz-2
runs, using Apple's on-device foundation model via the `FoundationModels` framework,
**without contending for the Metal GPU** — so narration can run concurrently with an
in-flight folding campaign.

---

## 2. Compute placement: what is and is not enforceable

This is the single most important constraint to get right, and the naive reading of it
is wrong. Read this section before writing any code.

### Not achievable

- **Pinning execution to the ANE.** `FoundationModels` exposes no compute-unit
  selector. There is no `MLComputeUnits` equivalent on `SystemLanguageModel` or
  `LanguageModelSession`. Placement is decided by the OS.
- **Zero CPU usage.** Tokenisation, constrained-decoding schema masking, JSON
  serialisation, the Swift runtime and the Python driver are all CPU by necessity.
  Several graph ops (LayerNorm, TopK sampling, scatter/gather, comparison ops) have no
  ANE implementation and always fall back.

Do not write code that attempts either of these. Do not add config flags implying
they are possible.

### Achievable, and therefore the actual requirement

| Invariant | Enforcement |
|---|---|
| **INV-1** No Metal device is created by the narration path | Measured: GPU power delta during narration must stay within noise of idle baseline |
| **INV-2** ANE is demonstrably active during narration | Measured: ANE power must rise above idle baseline |
| **INV-3** CPU is used for orchestration only, never for model inference | Structural: no local model weights, no PyTorch/MLX/llama.cpp in the narration path |
| **INV-4** Narration never blocks or delays a running campaign | Runs as a separate process at low QoS; failure is non-fatal |

INV-1 and INV-2 are verified by the harness in Phase 5, not asserted in prose.

---

## 3. Architecture

```
BoltzMaker (Python)
│
├─ analysis layer  ─────────────►  FactBlock (JSON, one per target)
│                                    │  all numbers pre-computed here
│                                    ▼
├─ landlord/bridge.py  ──subprocess──►  boltzmaker-landlord (Swift, universal binary)
│                                    │      FoundationModels
│                                    │      LanguageModelSession + @Generable
│                                    ◄──── TargetSummary (JSON)
│                                    │
├─ landlord/validate.py  ────────►  numeric-integrity gate
│                                    │
└─ landlord/fallback.py  ────────►  Jinja2 template renderer (always available)
```

Single Swift binary, invoked per target or in batch mode. Python owns all
orchestration, all computation, and the fallback path.

---

## 4. Phase 0 — Feasibility spike (do this first, do not skip)

**Purpose:** establish that the framework will actually narrate structural-biology and
pharmacology content before any integration work is done.

The content-safety guardrails are opaque and non-overridable. Vocabulary around
toxicity, dosing, IC50/Ki, named compounds and therapeutic indications is exactly the
class of text that can trigger a spurious refusal. Find out now.

**Tasks**

1. Minimal Swift CLI: read a prompt from stdin, print the response.
2. Assemble 20 realistic fact blocks drawn from existing BoltzMaker output. Deliberately
   include the awkward cases: cytotoxic compounds, controlled-substance scaffolds,
   anything with a clinical indication attached.
3. Record refusal rate, and for each refusal capture the exact input.
4. Measure: cold-start latency, tokens/sec, and time for a 200-token summary.
5. Confirm `SystemLanguageModel.default.availability` reporting on the target machine.

**Kill criteria — stop and report back to Marc if any are true**

- Refusal rate on scientific content exceeds ~5%
- Refusals cannot be worked around by neutralising the fact-block vocabulary
- Per-target latency exceeds ~15 s on an otherwise idle machine
- GPU power rises measurably during generation (INV-1 already violated)

**Deliverable:** a short findings note in `docs/landlord_spike.md`. No integration code
until Marc has read it.

---

## 5. Phase 1 — The FactBlock contract

The FactBlock is the boundary between "BoltzMaker computes" and "the model narrates".
Define it before writing the Swift side.

**Module:** `boltzmaker/landlord/factblock.py`, Pydantic v2.

Required design properties:

- **Every numeric value arrives pre-formatted as a string**, with units and significant
  figures already applied by Python (`"ipTM 0.84"`, not `0.8417...`). The model must
  never see a raw float it might reformat, round or arithmetically combine.
- **Every ranking, threshold judgement and comparison is pre-computed.** If a ligand is
  "top-ranked", Python says so. The model does not sort.
- **Token-budgeted.** Include a `token_estimate()` method. The on-device context window
  shipped at 4,096 tokens covering instructions + prompt + output combined. Apple has
  not published a revised on-device figure; assume 4,096 and verify against current
  docs at implementation time. Budget: ≤ 2,400 prompt tokens, ≤ 600 output, remainder
  reserved for instructions.
- **Truncation is explicit.** If a target has 40 ligands, Python selects the top N and
  sets `ligands_omitted: 35`, which the instructions tell the model to mention. Never
  silently drop content.

Suggested fields, adapt to what the analysis layer already produces:

```
target_id, sequence_length, apo_reference
confidence:  iptm, ptm, mean_pae, pae_interface, plddt_summary   (all strings)
ligands:     [ {name, affinity_pred, rank, plip_contacts_summary} ]
sse:         {matched, gained, lost, note}                        (from SSE comparison)
flags:       [ "low_confidence_interface", "apo_sse_divergence", ... ]
ligands_omitted: int
```

Write golden fixtures for at least 6 representative targets. These drive every
downstream test.

---

## 6. Phase 2 — The Swift narrator

**Location:** `swift/Landlord/`, SwiftPM package producing `boltzmaker-landlord`.
Universal binary (arm64 only is acceptable; there is no Intel path for this framework).

**Interface**

```
boltzmaker-landlord narrate  --in factblock.json  --out summary.json
boltzmaker-landlord batch    --in-dir facts/  --out-dir summaries/  --concurrency 2
boltzmaker-landlord check                       # availability probe, exit 0/1
```

JSON in, JSON out. Never write to stdout except the payload; diagnostics to stderr.

**Guided generation is the core mechanism.** Use `@Generable` structs so decoding is
constrained to the schema — this is what replaces fine-tuning. Prefer `@Generable`
enums over free strings wherever the value space is closed, because an enum makes an
invalid value physically unemittable rather than merely discouraged.

```swift
@Generable
struct TargetSummary {
    @Guide(description: "Two sentences on structural confidence. Do not restate numbers.")
    var confidence: String

    @Guide(description: "One sentence per ligand, in the order supplied.")
    var ligandNotes: [String]

    @Generable enum Verdict { case proceed, caution, discard }
    var recommendation: Verdict

    @Guide(description: "One sentence naming the single largest caveat.")
    var caveat: String
}
```

**Session instructions** must state, at minimum: narrate only supplied facts; never
compute, infer or restate a numeric value; never introduce a protein, ligand or
interaction not present in the input; British English.

**Availability handling.** `check` must distinguish and report the distinct
`SystemLanguageModel.Availability` cases — device ineligible, Apple Intelligence
disabled, model still downloading — because the remediation differs and users will hit
all three. Exit non-zero with a machine-readable reason on stderr.

**Concurrency.** Batch mode should run 2–4 concurrent sessions. Single-stream decode
leaves most ANE capacity idle, so aggregate throughput across a campaign is what
matters. Make concurrency a flag, default 2, and let Phase 5 tune it.

**Process QoS:** `.utility` or lower, so narration yields to the campaign.

---

## 7. Phase 3 — Python bridge, validation gate and fallback

**Module:** `boltzmaker/landlord/`

- `bridge.py` — subprocess invocation, timeout, structured error surfacing. A narration
  failure must **never** raise into the campaign path. Log and degrade.
- `validate.py` — the numeric-integrity gate. **Every numeric token appearing in
  generated text must exist verbatim in the source FactBlock.** Regex-extract numerics
  from the output, set-difference against the input, and reject on any orphan. A report
  that silently misstates a ΔG is worse than no report. Rejected output falls through
  to the template.
- `fallback.py` — Jinja2 renderer producing a plain, correct, unglamorous summary from
  the same FactBlock. This is not a stub. It must be good enough to ship on its own,
  because it is what most users on non-eligible machines will actually get.
- `config.py` — `narration: {enabled, mode: auto|model|template|off, concurrency, timeout_s}`.
  Default `auto`: probe once at startup, fall back silently.

---

## 8. Phase 4 — Campaign roll-up (map-reduce)

The context window forbids narrating a whole campaign in one pass.

1. **Map:** per-target `TargetSummary` (Phase 2).
2. **Reduce:** a second `@Generable` type, `CampaignSummary`, whose input is the
   *generated* per-target summaries plus a Python-computed statistics block
   (hit counts, confidence distribution, flag tallies).
3. The reduce prompt is also token-budgeted. For campaigns beyond ~30 targets, reduce
   hierarchically in batches rather than truncating.

The same numeric-integrity gate applies to the reduce stage.

---

## 9. Phase 5 — Compute-placement verification harness

**Location:** `tests/landlord/test_placement.py`, marked `@pytest.mark.hardware`.

This is the test that makes INV-1 and INV-2 real rather than aspirational.

```
1. Sample idle baseline:  powermetrics --samplers gpu_power,ane_power -i 500 -n 10
2. Run narration over the 6 golden fixtures.
3. Sample again throughout.
4. Assert:  ANE power delta  >  0   (INV-2: work landed on the ANE)
            GPU power delta  ≈  0   (INV-1: no Metal contention)
```

`powermetrics` requires root, so gate the test behind an explicit opt-in marker and
document the `sudo` requirement. Do not attempt to run it in CI.

Also record, into `docs/landlord_bench.md`: tokens/sec, per-target wall time, and
aggregate throughput at concurrency 1/2/4. That table is what tells Marc whether to
narrate during a campaign or after it.

---

## 10. Phase 6 — Packaging

- Swift binary built in CI, checked in or fetched as a release artefact — **not** built
  on the user's machine, since that would require Xcode.
- Codesign and notarise for distribution outside the App Store. This is the main
  non-obvious packaging cost; budget for it explicitly.
- Slot into the existing pixi-based macOS installer as a platform-specific optional
  component. On any platform other than arm64 macOS, `narration` resolves to `template`
  and nothing else changes.
- No model weights are shipped. That is the entire point of this approach.

---

## 11. Explicitly out of scope

Do not implement, and do not propose:

- **LoRA adapter fine-tuning.** Adapters are version-locked to a specific base-model
  signature and break on OS updates with an opaque `compatibleAdapterNotFound`. They
  are 160 MB+, must be hosted and downloaded rather than bundled, and require the
  Foundation Models Framework Adapter Entitlement. Apple's own documentation
  discourages them by default. Guided generation plus session instructions covers this
  use case.
- **Core ML conversion of Boltz-2 itself.** Rank-5 triangle-attention tensors, dynamic
  shapes and fp16-only ANE execution make this a dead end.
- Any local LLM runtime (llama.cpp, MLX, ANEMLL) in the narration path. That would
  reintroduce weights, GPU usage, or both.

---

## 12. Acceptance criteria

- [ ] Phase 0 findings note reviewed by Marc before integration begins
- [ ] Narration produces a summary for all 6 golden fixtures
- [ ] Numeric-integrity gate rejects a deliberately corrupted model output (test case)
- [ ] Template fallback produces usable output with narration disabled
- [ ] A campaign completes normally with the framework unavailable, and with the binary
      missing entirely
- [ ] Placement harness confirms INV-1 and INV-2 on Marc's hardware
- [ ] Benchmark table recorded in `docs/landlord_bench.md`
- [ ] `README.md` updated to Marc's house standard

---

## 13. Notes for the implementer

- **British English** in all user-facing strings, documentation and comments.
- Verify the `FoundationModels` API surface against current Apple documentation before
  writing Phase 2. The framework has moved since macOS 26 and the code sketch above is
  illustrative, not copied from current docs.
- Land phases as separate PRs. Phase 0 is a spike and may be thrown away.
- If Phase 0 trips a kill criterion, stop. Do not work around it. The template fallback
  is a perfectly respectable product on its own, and shipping that alone is a better
  outcome than shipping a narrator that occasionally refuses to describe a cytotoxin.
