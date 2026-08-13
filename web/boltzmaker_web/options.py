"""The run-settings registry for Fully Automated Mode.

One list, three consumers: the Prepare form renders from it, the POST handler
validates against it, and the generated bundle's run script and config.json are
written from it. Adding a knob means adding an entry here and nothing else.

Every option maps to a real BoltzMaker.py flag rather than to some web-only
abstraction. That is the point -- the bundle's run script is meant to be opened
and read by the person running it, and what they read has to be the same
vocabulary as `BoltzMaker.py --help`, or the generated script becomes a thing
they have to trust rather than a thing they can check.

`default=None` means "don't pass the flag at all", which is materially different
from passing the flag with Boltz's own default value: several of these
(recycling_steps, sampling_steps, the affinity pair) are passthroughs whose real
default lives inside Boltz and moves with Boltz's own version. Writing today's
value into the script would silently pin it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class OptionError(ValueError):
    """A submitted run setting was not usable. The message is safe to show the
    user; `.field` maps it back to the form input that caused it."""

    def __init__(self, message: str, field: str = None):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Option:
    name: str            # form field name / config.json key
    flag: str            # the BoltzMaker.py CLI flag it becomes
    kind: str            # "choice" | "int" | "float" | "bool"
    default: Any         # None => omit the flag entirely (use Boltz's own default)
    label: str
    hint: str
    choices: tuple = ()
    minimum: float = None
    maximum: float = None
    group: str = "run"   # which fieldset it renders under


RUN_OPTIONS: tuple[Option, ...] = (
    Option(
        name="accelerator", flag="--accelerator", kind="choice", default="auto",
        choices=("auto", "gpu", "cpu"),
        label="Accelerator",
        hint="auto picks your GPU (CUDA or Apple MPS) when there is one. cpu works but is "
             "slow enough that it is really only for checking a campaign runs at all.",
    ),
    Option(
        name="workers", flag="--workers", kind="int", default=2, minimum=0, maximum=16,
        label="Data-loading workers",
        hint="Matches Boltz's own default of 2. Lower it to 0 if you hit memory pressure on a Mac.",
    ),
    Option(
        name="max_parallel_samples", flag="--max-parallel-samples", kind="int", default=1,
        minimum=1, maximum=8,
        label="Parallel diffusion samples",
        hint="How many diffusion samples Boltz holds in memory at once. 1 is the safe default on "
             "unified-memory hardware; raising it multiplies peak memory.",
    ),
    Option(
        name="mps_watermark", flag="--mps-watermark", kind="float", default=1.0,
        minimum=0.1, maximum=2.0,
        label="MPS high-watermark ratio",
        hint="Apple Silicon only (PYTORCH_MPS_HIGH_WATERMARK_RATIO). Caps how much unified memory "
             "PyTorch will claim before it errors instead of swap-thrashing. Ignored elsewhere.",
    ),
    Option(
        name="recycling_steps", flag="--recycling-steps", kind="int", default=None,
        minimum=0, maximum=20,
        label="Recycling steps",
        hint="Leave blank for Boltz's own default. More steps is slower and usually only "
             "marginally better.",
    ),
    Option(
        name="sampling_steps", flag="--sampling-steps", kind="int", default=None,
        minimum=1, maximum=1000,
        label="Sampling steps",
        hint="Leave blank for Boltz's own default.",
    ),
    Option(
        name="diffusion_samples", flag="--diffusion-samples", kind="int", default=None,
        minimum=1, maximum=20,
        label="Structure samples per target",
        hint="Leave blank for one sample per target. Each extra sample costs roughly its own "
             "share of diffusion time, and analysis only ever reads the first one (model_0) -- "
             "so raise it to inspect pose variability yourself, not to improve the report.",
    ),
    Option(
        name="diffusion_samples_affinity", flag="--diffusion-samples-affinity", kind="int",
        default=None, minimum=1, maximum=20,
        label="Affinity diffusion samples",
        hint="Leave blank for Boltz's own default. Only matters for targets with affinity "
             "prediction switched on.",
    ),
    Option(
        name="sampling_steps_affinity", flag="--sampling-steps-affinity", kind="int",
        default=None, minimum=1, maximum=1000,
        label="Affinity sampling steps",
        hint="Leave blank for Boltz's own default.",
    ),
    Option(
        name="max_msa_seqs", flag="--max-msa-seqs", kind="int", default=None,
        minimum=1, maximum=100000,
        label="Max MSA sequences",
        hint="Leave blank for Boltz's own default. Lowering it is one of the few levers that "
             "meaningfully cuts memory on very large complexes.",
    ),
    Option(
        name="max_retries", flag="--max-retries", kind="int", default=2, minimum=0, maximum=10,
        label="Auto-retries per target",
        hint="A target that fails (typically an out-of-memory kill) is retried in isolation, one "
             "target at a time. 0 disables retrying.",
    ),
    Option(
        name="memory_warn_tokens", flag="--memory-warn-tokens", kind="int", default=1000,
        minimum=100, maximum=100000,
        label="Preflight size-warning threshold",
        hint="Preflight warns when a target's combined residue/atom count exceeds this. It is a "
             "warning, not a limit.",
    ),
    Option(
        name="limit", flag="--limit", kind="int", default=None, minimum=1, maximum=10000,
        label="Only run the first N targets",
        hint="Leave blank to run the whole campaign. Setting it to 1 or 2 is the cheapest way to "
             "prove the pipeline works before committing hours of GPU time.",
        group="scope",
    ),
    Option(
        name="strict", flag="--strict", kind="bool", default=False,
        label="Treat preflight warnings as failures",
        hint="Stops the run before any GPU time is spent if preflight raises any warning at all.",
        group="scope",
    ),
    Option(
        name="skip_interactions", flag="--skip-interactions", kind="bool", default=False,
        label="Skip PLIP interaction analysis",
        hint="Leave off. PLIP is what produces the per-target interaction fingerprints the "
             "Analysis step shows; skipping it saves minutes but empties that panel.",
        group="analysis",
    ),
    Option(
        name="skip_sse", flag="--skip-sse", kind="bool", default=False,
        label="Skip apo-vs-holo compare-sse",
        hint="Only does anything for families with an 'Apo structure:' set. Skipping it drops the "
             "secondary-structure comparison from the results.",
        group="analysis",
    ),
    # flag="" means this never reaches BoltzMaker.py. It is a property of how this
    # site handles your files, not of the campaign, and the generated run script
    # must not grow an argument the CLI would reject.
    Option(
        name="keep_private", flag="", kind="bool", default=False,
        label="Keep private",
        hint="Nothing about this run is kept on the server: the bundle is not archived, and the "
             "results file you upload later is recognised as private and not archived either. "
             "Leave it off and the run is listed under Runs, where you can download the bundle "
             "and results again later.",
        group="analysis",
    ),
)

OPTIONS_BY_NAME = {o.name: o for o in RUN_OPTIONS}

GROUP_TITLES = {
    "run": "Prediction settings",
    "scope": "Scope and safety",
    "analysis": "Analysis",
}


def _as_number(raw: str, opt: Option) -> Any:
    try:
        value = int(raw) if opt.kind == "int" else float(raw)
    except (TypeError, ValueError):
        raise OptionError(f"{opt.label}: {raw!r} is not a number.", field=opt.name) from None
    if opt.minimum is not None and value < opt.minimum:
        raise OptionError(f"{opt.label}: must be at least {opt.minimum}.", field=opt.name)
    if opt.maximum is not None and value > opt.maximum:
        raise OptionError(f"{opt.label}: must be at most {opt.maximum}.", field=opt.name)
    return value


def parse_form(form) -> dict[str, Any]:
    """Validate a submitted run-settings form into a config dict.

    A blank string for a numeric option means "use the default", which for the
    passthrough options is None (omit the flag). It never means zero -- a
    blanked field and a deliberate 0 are different intents, and several of
    these options accept 0 as a real value (workers, max_retries).
    """
    cfg: dict[str, Any] = {}
    for opt in RUN_OPTIONS:
        if opt.kind == "bool":
            cfg[opt.name] = form.get(opt.name) in ("1", "on", "true", "yes")
            continue

        raw = (form.get(opt.name) or "").strip()
        if raw == "":
            cfg[opt.name] = opt.default
            continue

        if opt.kind == "choice":
            if raw not in opt.choices:
                raise OptionError(
                    f"{opt.label}: {raw!r} is not one of {', '.join(opt.choices)}.", field=opt.name
                )
            cfg[opt.name] = raw
        else:
            cfg[opt.name] = _as_number(raw, opt)
    return cfg


def defaults() -> dict[str, Any]:
    return {o.name: o.default for o in RUN_OPTIONS}


def to_cli_args(cfg: dict[str, Any]) -> list[str]:
    """Render a validated config as the argv tail BoltzMaker.py receives.

    Options left at None are omitted rather than passed explicitly -- see the
    module docstring on why writing Boltz's current default into the script
    would silently pin it.
    """
    args: list[str] = []
    for opt in RUN_OPTIONS:
        if not opt.flag:      # web-only settings never reach the CLI
            continue
        value = cfg.get(opt.name, opt.default)
        if value is None:
            continue
        if opt.kind == "bool":
            if value:
                args.append(opt.flag)
        else:
            args.extend([opt.flag, str(value)])
    return args


def to_cli_lines(cfg: dict[str, Any]) -> list[str]:
    """The same arguments as to_cli_args, but with each flag and its value kept
    together on one line.

    Purely for the generated run script, and not cosmetic: that script exists to
    be read and checked before someone commits hours of GPU time to it, and a
    flat argv list rendered one token per line splits every flag from its value
    ("--workers \\" then "0 \\"), which is precisely the form in which a wrong
    value is hardest to spot.
    """
    lines: list[str] = []
    for opt in RUN_OPTIONS:
        if not opt.flag:      # web-only settings never reach the CLI
            continue
        value = cfg.get(opt.name, opt.default)
        if value is None:
            continue
        if opt.kind == "bool":
            if value:
                lines.append(opt.flag)
        else:
            lines.append(f"{opt.flag} {value}")
    return lines
