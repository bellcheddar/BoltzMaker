# Landlord — packaging

The plan budgeted for the main non-obvious cost being **codesigning and notarisation**,
because distributing a binary outside the App Store needs both, and because building it
was assumed to require Xcode.

Neither turned out to be necessary, for one reason: the narrator does not use the
`@Generable` macro.

## Why there is nothing to notarise

`@Generable` needs the `FoundationModelsMacros` compiler plugin, which ships with Xcode
and not with the CommandLineTools. Using it would have made a ~15 GB Xcode install a
build dependency for a binary whose entire selling point is that it ships no weights.

`DynamicGenerationSchema` is the framework's own alternative: the schema is assembled at
run time and passed to `respond(to:schema:)`, and decoding is constrained by it exactly
as the macro would. Same guided generation, no plugin.

With the macro gone, `swift build -c release` works against the CommandLineTools SDK
alone. Measured from a clean tree: **30.6 s**. A binary compiled on the user's own
machine needs no Developer ID, no notarisation and no stapling, because Gatekeeper does
not police what you built yourself.

## How it is obtained

`landlord.install.ensure()`, in order:

1. A prebuilt `bin/boltzmaker-landlord`, if one was shipped.
2. An already-built `swift/Landlord/.build/release/boltzmaker-landlord`.
3. Otherwise `swift build -c release`, once, and cache it.

Every step fails soft. There is no path from a packaging problem to a failed campaign.

## What happens where

| Machine | Result |
|---|---|
| arm64 macOS 26+, Apple Intelligence on, toolchain present | on-device narration |
| arm64 macOS 26+, no Swift toolchain | template, with `xcode-select --install` suggested |
| arm64 macOS 26+, Apple Intelligence off or model downloading | template, naming which |
| Intel macOS | template -- FoundationModels has no Intel path |
| macOS 25 or earlier | template -- the framework does not exist |
| Linux, Windows | template |

All six are covered by tests in `tests/landlord/test_landlord.py`, which run anywhere:
the paths that must work on every machine are tested on every machine.

## Shipping a prebuilt binary anyway

Worth doing only for machines with no toolchain at all, and it reintroduces the cost the
rest of this avoids:

- Build in CI on an arm64 macOS 26 runner.
- Sign with a Developer ID Application certificate, notarise, staple.
- Drop it at `bin/boltzmaker-landlord`; `ensure()` prefers it over building.

Not done. The template is a respectable product on machines without a toolchain, and
that is the trade the plan already accepted for machines without Apple Intelligence.

## No weights, still

Nothing here downloads or bundles a model. The binary is about 100 KB of Swift against a
system framework, which is the whole point of the approach.
