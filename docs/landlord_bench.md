# Landlord — benchmarks

Apple M1 Max, 64 GB, macOS 26.6.2. Machine in normal desktop use, not quiesced, so
treat single figures as indicative and the orders of magnitude as solid.

Workload: the 20 real FactBlocks of the `GLP1R_GIPR_pocket_matrix` campaign, 113 to
293 tokens each, through `boltzmaker-landlord batch`.

## Concurrency: fewer is faster

| Concurrency | Total wall | Per target | Completed |
|---|---|---|---|
| **1** | **174.6 s** | **8.7 s** | 19 of 20 |
| 2 | 254.0 s | 12.7 s | 20 of 20 |
| 4 | 286.7 s | 14.3 s | 20 of 20 |

**The plan expected the opposite**, on the reasonable grounds that "single-stream
decode leaves most ANE capacity idle, so aggregate throughput across a campaign is what
matters". On this hardware it does not hold: sessions contend rather than pipeline, and
the degradation is monotonic. Four concurrent sessions took 64% longer overall than one.

The per-target view shows the mechanism. At concurrency 4 each individual target took
46 to 58 s against 8.7 s sequentially -- roughly six times slower each -- and running
four at once did not recover it.

`NarrationConfig.concurrency` therefore defaults to **1**, not the plan's 2.

One caveat against reading too much into the completion column: the single failure at
concurrency 1 was a context-window overrun, which is stochastic and appears at any
setting. The bridge falls back to the template for that target, which is the designed
behaviour rather than a lost summary.

## What dominates a single target

| Condition | Per target |
|---|---|
| Cold start, first call after boot | 15.4 s |
| One process per target, warm | 4.8 - 9.0 s |
| In-process batch, warm | 8.7 s |

About **4 to 5 seconds of every subprocess invocation is process and session startup**
rather than inference, which is why `batch` is the primary interface and `narrate` the
convenience. Cold start is paid once per campaign, not per target.

## Prompt shape matters more than prompt content

| Serialisation | Per target | Characters |
|---|---|---|
| `json.dumps(indent=1)` | 22.9 s | 1,090 |
| `json.dumps(separators=(",",":"))` | 11.8 s | 937 |

Removing pretty-printing cut 13% of the characters and **49% of the time**. Newlines and
runs of spaces cost tokens out of all proportion to what they carry. `to_prompt_json()`
is compact for this reason; `to_pretty_json()` exists for fixtures and never reaches a
model.

Latency tracks block size steeply: the 113-token apo control narrates in about 5 s, the
293-token fullest block in about 19 s.

## The window is mostly not your data

A target that failed with `Content contains 4090 tokens, which exceeds the maximum
allowed context size of 4096` was carrying a 293-token fact block. Instructions add
about 209 tokens and the schema descriptions about 400, which leaves roughly **3,200
tokens of serialised schema** injected by `includeSchemaInPrompt`.

Two consequences, both already applied:

- Output is capped at 600 tokens (`GenerationOptions(maximumResponseTokens:)`). The
  failure was prompt plus unbounded generation crossing the limit, which is why the
  same input succeeded on retry.
- Reduce chunks hold 4 target summaries, not the plan's "~30 targets". `plan_chunks`
  measures each batch and shrinks it further rather than assuming.

## Whole campaign, end to end

20 targets, map plus 3 hierarchical reduce rounds, through the Python bridge:
**4 m 55 s**, 19 of 20 targets model-written, 1 template fallback.

## Compute placement

Covered in `landlord_spike.md`. In short: GPU power does not rise (15.0 -> 8.2 mW,
INV-1 holds), the inference path uses about 6% of one core (INV-3 holds), and INV-2 is
established by attribution rather than by a power rail this SoC does not expose.
