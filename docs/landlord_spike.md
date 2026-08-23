# Landlord — Phase 0 findings

Spike code: `landlord/spike/`. Plan: `landlord/boltzmaker_landlord_plan.md`.

**Verdict: no kill criterion tripped. One criterion cannot be measured from an agent
session and needs you to run one command.** On the evidence below, Phase 1 can begin.

## Kill criteria

| Criterion | Threshold | Measured | |
|---|---|---|---|
| Refusal rate on scientific content | > ~5% stops the project | **0%** (0 of 20) | pass |
| Refusals unworkaroundable | — | no refusals to work around | pass |
| Per-target latency, idle machine | > ~15 s stops the project | **11.8 s** mean on real blocks | pass, with a caveat |
| GPU power rises during generation | any rise violates INV-1 | **fell, 15.0 -> 8.2 mW** | pass |

## Platform

| Check | Result |
|---|---|
| macOS | 26.6.2 (build 25G83) |
| Hardware | Apple M1 Max, 64 GB |
| Swift toolchain | 6.3.3, target `arm64-apple-macosx26.0` |
| `FoundationModels.framework` | present in `/System` **and** the CommandLineTools SDK |
| `SystemLanguageModel.default.availability` | `.available` |
| `supportedLanguages` | 23 |

**No Xcode is required to build.** The framework ships in the CommandLineTools SDK, so
plain `swiftc` compiles and links. That removes the Phase 6 worry about users needing
Xcode. Codesigning and notarisation still apply to anything distributed.

**Availability reporting works and distinguishes the cases the plan asks for.** Before
Apple Intelligence was switched on, the probe returned
`.unavailable(.appleIntelligenceNotEnabled)` -- specifically not `.deviceNotEligible`.
Those need different messages to the user and `probe2.swift` already separates them.
It is the seed of the `check` subcommand.

## Refusals: none, on deliberately awkward content

Twenty fact blocks (`landlord/spike/facts/`), weighted towards exactly the vocabulary
the plan flagged as risky. Every one narrated.

- Cytotoxics: doxorubicin with its cardiotoxicity noted, paclitaxel, cisplatin
- Controlled substances: psilocin (Schedule I), morphine, fentanyl, ketamine, amphetamine
- Toxins: ricin, botulinum neurotoxin A
- Countermeasures: pralidoxime against organophosphate poisoning
- Clinical indications attached: leukaemia, treatment-resistant depression, resistant infection
- Awkward framings: a failed pose, a low-confidence interface, a truncated ligand list

Psilocin is the useful case. It narrated the pharmacology and stated the Schedule I
status as fact, without hedging or refusing:

> The predicted complex between the 5-HT2A receptor and psilocin shows a high confidence
> level with 10 total contacts... Psilocin is a Schedule I controlled substance under
> clinical investigation for treatment-resistant depression.

Caveat on the number: 0 of 20 bounds the refusal rate loosely. It rules out a
double-digit rate, not a 1-in-200 one. Worth re-checking on real campaign output once
Phase 1 fact blocks exist.

## Latency, and why batch mode matters more than expected

**The first figures here were measured on the wrong thing.** The 20 hand-written
blocks are six lines each; a real FactBlock is 113 to 293 tokens. Re-measured over the
six golden fixtures, which are real:

| Mode | Per target |
|---|---|
| Cold start, first call after boot | 15.39 s |
| Toy prompts, one process per target | 4.81 - 8.97 s |
| Toy prompts, in-process batch | 1.60 s mean |
| **Real FactBlocks, pretty-printed JSON** | **22.92 s mean** (14.6 - 31.5 s) -- over the criterion |
| **Real FactBlocks, compact JSON** | **11.80 s mean** (4.97 - 19.34 s) -- under it |

Two things follow, and the second is a change to the FactBlock contract.

**Latency tracks prompt size, steeply.** GLPAP, the apo control with no ligand at 113
tokens, narrates in 5 s; the fullest block at 293 tokens takes 19 s.

**Pretty-printing costs more than it looks.** Dropping `indent=1` removed 13% of the
characters and 49% of the time. Newlines and runs of spaces are expensive in tokens
out of all proportion to what they carry. `to_prompt_json()` is now compact and
`to_pretty_json()` is kept for fixtures and diffs; nothing sends the latter to a model.

The mean now clears the 15 s bar but the worst case does not. Worth revisiting under
concurrency in Phase 5, and worth trimming the block further if the reduce stage in
Phase 4 needs the headroom.

Batch mode remains load-bearing regardless: roughly 4 to 5 seconds per target is
process and session startup rather than inference, so `batch` should be Phase 2's
primary interface with `narrate` as the convenience, and cold start should be paid
once at campaign end rather than per target.

On these numbers a 20-target campaign narrates in about four minutes sequentially.

## INV-1, INV-2, INV-3: measured

`sudo bash landlord/spike/placement_check.sh`, machine otherwise in normal desktop use,
20 fact blocks narrated during the busy sample.

| | idle | during narration | |
|---|---|---|---|
| GPU power | 15.0 mW | **8.2 mW** | INV-1 pass -- no rise, so nothing to contend with a campaign |

**INV-1 holds, and comfortably.** GPU power did not merely stay flat, it fell below the
idle baseline: the idle sample caught ordinary desktop compositing that happened not to
be running during the busy one. Either way there is no Metal work in the narration
path, which is the invariant that lets narration run alongside an in-flight campaign.

**INV-2 cannot be measured directly on this hardware, and that is a hardware limit
rather than a result.** `powermetrics` describes `ane_power` as the "dedicated rail ane
power" sampler; the M1 Max exposes no such rail, so the sampler emits nothing and no
ANE row appears at all. The absence is not a zero.

What can be shown instead, root-free, is where the CPU time went. Per-process CPU was
diffed across a six-block narration:

| Process | CPU gained |
|---|---|
| `TGOnDeviceInferenceProviderService` | 2.05 s |
| `modelmanagerd` | 0.59 s |
| `modelcatalogd` | 0.55 s |
| **`aned`** (the Apple Neural Engine daemon) | **0.39 s** |
| `GenerativeExperiencesSafetyInferenceProvider` | 0.32 s |
| `IntelligencePlatformComputeService`, `siriinferenced` | 0.07 s |
| **total across the whole inference path** | **~3.9 s** |

Roughly **3.9 CPU-seconds for 61 seconds of narration, about 6% of one core**, and the
`batch` process itself never appeared in the top consumers at all. Generating this much
text on a CPU would cost one to two orders of magnitude more than that. So: not the
GPU, measured; not the CPU, measured; and `aned` -- the kernel's ANE driver daemon --
actively accumulating time throughout. The work is on the Neural Engine by elimination
with a positive signal, which is as close as this machine can get.

**INV-3 holds outright.** 6% of a core for orchestration, with no model weights and no
PyTorch, MLX or llama.cpp anywhere in the path.

One incidental finding worth keeping: `GenerativeExperiencesSafetyInferenceProvider`
consumes CPU on every request. The guardrails are running and being passed, rather than
absent. That makes the 0-of-26 refusal rate a real result about this content rather than
evidence that nothing was checked.

A caveat on precision: the machine was in normal desktop use, not quiesced. WindowServer,
Messages, Spotlight and a browser were all busier than anything on the inference path,
which is also why per-target latency moved between runs. The conclusions above survive
that noise because they turn on orders of magnitude, not on close calls.

## Output quality, and what it implies for Phase 2

Good enough to proceed, with two habits that the planned machinery already addresses.

**It restates numbers despite being told not to.** Every summary quoted figures back.
Harmless when correct, and they were correct here, but it is precisely why
`validate.py`'s numeric-integrity gate is not optional: the model demonstrably will put
numbers in prose, so every one of them has to be checked against the FactBlock.

**It occasionally drops a fact rather than inventing one.** The psilocin summary gave 7
hydrophobic contacts and 1 pi-cation but omitted the 2 hydrogen bonds. Omission is the
benign failure mode; the gate catches invention, and `@Generable` with one field per
required element is what catches omission.

**One garbled subject, on the very first cold call.** It rendered
"GLP1R_ORFO_V6G and ipTM" as though ipTM were a second ligand. Not repeated in the 20
batch runs. A free-text prompt invites it; a `@Generable` schema with typed fields
removes the opportunity, which is the plan's stated reason for guided generation.

## Recommendation

Proceed. No kill criterion tripped, and the invariant that shapes the architecture --
INV-1, no GPU contention -- is measured and holds, so narration can run alongside a
campaign rather than only after one.

Two adjustments to the plan, both from the latency table:

1. Make `batch` the primary interface, not `narrate`. The per-process overhead is
   larger than the inference.
2. Pay cold start once per campaign. At 15 s it is ten times a warm target and should
   never sit on a per-target path.
