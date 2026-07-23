"""Subprocess wrapper around BoltzMaker.py.

BoltzMaker.py can never be imported (it runs `_bootstrap_or_relaunch(sys.argv)`
at module level -- see its own comments) -- every call here is a real
subprocess, invoking the trimmed venv's python interpreter directly so
BoltzMaker's own venv-detection logic (`_bootstrap_or_relaunch`) sees a
matching `sys.executable` and never tries to execv/relaunch itself.

Path resolution is deliberately anchored to this file's own location, resolved
upward to the real repo root -- never a hardcoded absolute path -- so this
works identically in local dev (a git worktree) and on the droplet (an rsync'd
checkout at /opt/boltzmaker), and so a deploy script that accidentally
flattens `web/` up a directory (the exact bug chatPDB's own deploy docs warn
about, see PACKAGING_PLAN-adjacent notes) fails loudly here rather than
silently resolving to the wrong interpreter.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# web/boltzmaker_web/runner.py -> web/boltzmaker_web -> web -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOLTZMAKER_SCRIPT = REPO_ROOT / "BoltzMaker.py"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"

# Per-command timeouts (seconds) -- analyze's cost scales with target count
# (CIF copies + dashboard/plotly rendering across potentially dozens of
# targets), the others are cheap/fast by comparison.
_TIMEOUTS = {
    "format": 30,
    "generate": 60,
    "preflight": 90,
    "analyze": 300,
}


class RunnerConfigError(RuntimeError):
    """Raised when BOLTZMAKER_SCRIPT/VENV_PYTHON aren't where expected -- a
    deploy/path problem, not a user-input problem, so it's kept distinct from
    BoltzMakerError (which wraps a real subprocess failure)."""


class BoltzMakerError(RuntimeError):
    """A BoltzMaker.py subprocess exited non-zero. `.stderr` holds its stderr
    text for the caller to extract a user-facing message from (see
    `extract_error_message` below)."""

    def __init__(self, message: str, returncode: int, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class BoltzMakerTimeout(RuntimeError):
    """A BoltzMaker.py subprocess ran past its allotted timeout."""


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str


def _check_paths() -> None:
    if not BOLTZMAKER_SCRIPT.is_file():
        raise RunnerConfigError(
            f"BoltzMaker.py not found at {BOLTZMAKER_SCRIPT} -- web/ is nested wrong "
            "relative to the repo root (see runner.py's module docstring)."
        )
    if not VENV_PYTHON.is_file():
        raise RunnerConfigError(
            f"Trimmed venv not found at {VENV_PYTHON} -- build it first: "
            f"python3 -m venv {REPO_ROOT}/.venv && {REPO_ROOT}/.venv/bin/pip install "
            "rich pandas openpyxl pyyaml rdkit matplotlib psutil scipy gemmi biopython "
            "plotly reportlab requests (deliberately NOT `boltz` -- see the plan)."
        )


def run_boltzmaker(command: str, md_path: Path, *extra_args: str, cwd: Path = None) -> RunResult:
    """Invoke `<trimmed venv>/bin/python3 BoltzMaker.py <command> <md_path> <extra_args...>`.

    Raises BoltzMakerConfigError if the venv/script aren't where expected,
    BoltzMakerTimeout if the process outlives its command's timeout budget,
    or returns a RunResult (including non-zero returncode -- callers that
    want an exception on failure should check `.returncode` themselves or use
    `run_boltzmaker_or_raise`).
    """
    _check_paths()
    timeout = _TIMEOUTS.get(command, 60)
    argv = [str(VENV_PYTHON), str(BOLTZMAKER_SCRIPT), command, str(md_path), *extra_args]

    # Explicit, minimal environment -- never os.environ.copy(). In particular,
    # CONDA_PREFIX/PIXI_PROJECT_ROOT must never leak in: BoltzMaker.py's
    # _in_pixi_env() checks CONDA_PREFIX *before* its own .venv logic, and if
    # either var were somehow present in gunicorn's own environment, every
    # subprocess call here would silently assume a full pixi env (torch/boltz
    # included) exists and break in a confusing way.
    env = {
        "PATH": f"{VENV_PYTHON.parent}:/usr/bin:/bin",
        "HOME": "/tmp",  # BoltzMaker/rdkit/matplotlib may want a writable HOME; never the real one
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }

    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise BoltzMakerTimeout(
            f"`{command}` took longer than {timeout}s -- is the campaign unusually large?"
        ) from exc

    return RunResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def run_boltzmaker_or_raise(command: str, md_path: Path, *extra_args: str, cwd: Path = None) -> RunResult:
    """Same as run_boltzmaker, but raises BoltzMakerError on a non-zero exit
    instead of returning it for the caller to check."""
    result = run_boltzmaker(command, md_path, *extra_args, cwd=cwd)
    if result.returncode != 0:
        raise BoltzMakerError(
            f"`{command}` exited with code {result.returncode}",
            returncode=result.returncode,
            stderr=result.stderr,
        )
    return result


def extract_error_message(stderr: str) -> str:
    """BoltzMaker.py's MDParseError is uncaught -- a real invocation's stderr
    on a bad boltz_input.md is a full Python traceback ending in
    `MDParseError: <message>`. Pull just that message out for display;
    fall back to the last non-empty stderr line for any other kind of
    failure (still far more readable than a raw traceback in the browser)."""
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    if not lines:
        return "BoltzMaker exited with no error output."
    last = lines[-1]
    prefix = "MDParseError: "
    if prefix in last:
        return last.split(prefix, 1)[1]
    # Generic "SomeException: message" tracebacks -- still more useful than the
    # raw multi-line traceback text.
    if ": " in last and last[: last.index(":")].replace("_", "").isalnum():
        return last
    return last
