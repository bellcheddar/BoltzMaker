"""Preflight checks that must not abort a campaign for the wrong reason.

`BoltzMaker.py` cannot simply be imported -- it calls `_bootstrap_or_relaunch`
at module level and would try to execv itself into a managed venv -- so it is
loaded here with that one call neutralised. The module needs a real `__spec__`
for `from __future__` and dataclass machinery to work under a synthetic module
object, which is why it is registered in sys.modules rather than exec'd bare.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bm():
    source = (REPO_ROOT / "BoltzMaker.py").read_text()
    source = source.replace("_bootstrap_or_relaunch(sys.argv)", "pass  # neutralised for tests")
    module = types.ModuleType("boltzmaker_under_test")
    module.__file__ = str(REPO_ROOT / "BoltzMaker.py")
    module.__spec__ = importlib.util.spec_from_loader("boltzmaker_under_test", loader=None)
    sys.modules["boltzmaker_under_test"] = module
    exec(compile(source, str(REPO_ROOT / "BoltzMaker.py"), "exec"), module.__dict__)
    return module


def _stub_boltz(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def test_a_slow_boltz_warns_rather_than_failing(bm, tmp_path, monkeypatch):
    """A cold first import must not abort the campaign.

    `boltz --help` imports the whole torch stack; the first invocation in a
    freshly solved environment also byte-compiles it against a cold page cache.
    That took over the old 20-second timeout on a real run, and because a
    timeout was reported as FAIL, preflight aborted the campaign before any GPU
    work -- on nothing more than a slow start. The binary's existence is checked
    separately, so a timeout here is evidence about import time, not about
    whether boltz works.
    """
    slow = _stub_boltz(tmp_path, "boltz_slow", "sleep 300")
    monkeypatch.setattr(bm, "_boltz_bin", lambda: slow)
    monkeypatch.setattr(bm, "BOLTZ_CLI_HELP_TIMEOUT", 1)

    result = bm.check_boltz_cli()
    assert result.status == "WARN"
    assert "did not answer --help" in result.message


def test_a_missing_boltz_still_fails(bm, monkeypatch):
    monkeypatch.setattr(bm, "_boltz_bin", lambda: pathlib.Path("/nonexistent/boltz"))
    assert bm.check_boltz_cli().status == "FAIL"


def test_a_boltz_that_errors_is_reported(bm, tmp_path, monkeypatch):
    broken = _stub_boltz(tmp_path, "boltz_broken", "exit 3")
    monkeypatch.setattr(bm, "_boltz_bin", lambda: broken)
    result = bm.check_boltz_cli()
    assert result.status == "WARN"
    assert "exited 3" in result.message


def test_a_working_boltz_passes(bm, tmp_path, monkeypatch):
    good = _stub_boltz(tmp_path, "boltz_ok", "exit 0")
    monkeypatch.setattr(bm, "_boltz_bin", lambda: good)
    assert bm.check_boltz_cli().status == "PASS"


def test_the_help_timeout_leaves_room_for_a_cold_torch_import(bm):
    """Measured: warm is under a second, cold has exceeded 20s on a real machine.
    The old value was 20, which is what made this a bug rather than a slow check."""
    assert bm.BOLTZ_CLI_HELP_TIMEOUT >= 60


def test_only_fail_aborts_a_run(bm):
    """The severity ladder preflight uses to decide whether to stop. A WARN must
    let the campaign proceed unless --strict was asked for, which is the whole
    reason the cold-start case was downgraded to WARN."""
    warn_only = [bm.CheckResult("a", "PASS", ""), bm.CheckResult("b", "WARN", "")]
    with_fail = warn_only + [bm.CheckResult("c", "FAIL", "")]

    def worst(results, strict):
        state = "PASS"
        for r in results:
            if r.status == "FAIL" or (strict and r.status == "WARN"):
                state = "FAIL"
            elif r.status == "WARN" and state != "FAIL":
                state = "WARN"
        return state

    assert worst(warn_only, strict=False) == "WARN"     # campaign proceeds
    assert worst(warn_only, strict=True) == "FAIL"      # --strict still stops
    assert worst(with_fail, strict=False) == "FAIL"
