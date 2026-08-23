"""Getting a narrator onto the machine, or deciding there will not be one.

The plan assumed the Swift binary would have to be built in CI and shipped as a
signed, notarised artefact, because building it needed Xcode. It does not: the
narrator avoids the `@Generable` macro -- the one part of FoundationModels that needs
the `FoundationModelsMacros` compiler plugin -- and builds against the CommandLineTools
SDK alone, in a couple of seconds.

That changes the packaging story completely. A binary built on the user's own machine
needs no Developer ID, no notarisation and no stapling, because Gatekeeper does not
police what you compiled yourself. The remaining reason to ship a prebuilt one is
convenience for machines with no toolchain at all, and those machines get the template.

Everything here fails soft. Not arm64 macOS, no Swift, no Apple Intelligence, a build
error -- each ends at `template`, and a campaign notices none of them.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO / "swift/Landlord"
BUILT = PACKAGE_DIR / ".build/release/boltzmaker-landlord"
#: Where a prebuilt binary would be dropped, for machines with no toolchain.
SHIPPED = REPO / "bin/boltzmaker-landlord"

#: macOS 26 is the floor: FoundationModels does not exist before it.
MIN_MACOS = 26


@dataclass
class Readiness:
    ok: bool
    binary: Path | None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def platform_supported() -> tuple[bool, str]:
    """arm64 macOS 26 or later. Everything else narrates from the template."""
    if platform.system() != "Darwin":
        return False, f"{platform.system()} has no on-device Apple model; using templates"
    if platform.machine() != "arm64":
        return False, "FoundationModels has no Intel path; using templates"
    try:
        major = int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return False, "could not read the macOS version; using templates"
    if major < MIN_MACOS:
        return False, (f"macOS {major} predates FoundationModels "
                       f"(needs {MIN_MACOS} or later); using templates")
    return True, ""


def ensure(build: bool = True, quiet: bool = True) -> Readiness:
    """Find a usable narrator, building one if that is cheap and possible."""
    supported, why = platform_supported()
    if not supported:
        return Readiness(False, None, why)

    for candidate in (SHIPPED, BUILT):
        if candidate.is_file():
            return Readiness(True, candidate)

    if not build:
        return Readiness(False, None, "no narrator binary and building was not requested")
    if not PACKAGE_DIR.is_dir():
        return Readiness(False, None, "the Swift package is not present in this checkout")
    if shutil.which("swift") is None:
        return Readiness(
            False, None,
            "no Swift toolchain; install the Command Line Tools with "
            "`xcode-select --install` to build the narrator, or carry on with templates")

    try:
        done = subprocess.run(["swift", "build", "-c", "release"],
                              cwd=PACKAGE_DIR, capture_output=True, text=True,
                              timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        return Readiness(False, None, f"could not run swift build: {exc}")
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no output"]
        return Readiness(False, None, f"swift build failed: {tail[0]}")
    if not BUILT.is_file():
        return Readiness(False, None, "swift build reported success but produced no binary")
    if not quiet:
        print(f"built {BUILT}")
    return Readiness(True, BUILT)


def status() -> str:
    """One line for `preflight` and the report, saying which path will be taken."""
    from .bridge import available

    ready = ensure(build=False)
    if not ready:
        return f"Landlord: template narration ({ready.reason})"
    usable, why = available(ready.binary)
    if not usable:
        return f"Landlord: template narration ({why})"
    return f"Landlord: on-device narration via {ready.binary.name}"
