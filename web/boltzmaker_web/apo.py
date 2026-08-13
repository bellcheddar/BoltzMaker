"""Fetching an experimental apo structure from the PDB, for compare-sse.

Only used when someone names a PDB id on the Prepare form. The file is fetched
here, at prepare time, and shipped inside the bundle rather than downloaded on
the user's machine during the run: a campaign that has already started should
never stop to ask the network for something that could have been checked while
the user was still looking at the form.

Failure is reported, never silent. If the id does not exist, or the PDB is
unreachable, the person who typed it is still sitting in front of the form and
can fix it or leave it blank -- whereas a bundle that quietly lost its apo
reference would simply produce no comparison, hours later, for no visible reason.
"""

from __future__ import annotations

import urllib.error
import urllib.request

RCSB_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"
TIMEOUT_SECONDS = 20
# A PDB entry is a few hundred KB; the largest are a handful of MB. Well above
# anything real, well below anything that would bloat a bundle.
MAX_BYTES = 40 * 1024 * 1024


class ApoFetchError(RuntimeError):
    """The structure could not be fetched. The message is safe to show the user."""


def reference_path(pdb_id: str) -> str:
    """Where the structure lives inside the campaign, as the spec refers to it."""
    return f"reference/{pdb_id.lower()}.pdb"


def fetch(pdb_id: str, opener=urllib.request.urlopen) -> bytes:
    """Download one PDB entry. `opener` is injectable so tests never touch the network."""
    url = RCSB_URL.format(pdb_id=pdb_id.upper())
    try:
        with opener(url, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ApoFetchError(
                f"the PDB has no entry {pdb_id.upper()} -- check the id, or leave it blank "
                "to have an apo structure predicted instead."
            ) from exc
        raise ApoFetchError(
            f"the PDB returned {exc.code} for {pdb_id.upper()}. Try again, or leave it "
            "blank to have an apo structure predicted instead."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApoFetchError(
            f"could not reach the PDB to fetch {pdb_id.upper()} ({exc}). Try again, or "
            "leave it blank to have an apo structure predicted instead."
        ) from exc

    if len(data) > MAX_BYTES:
        raise ApoFetchError(f"{pdb_id.upper()} is larger than {MAX_BYTES // 1024 // 1024}MB.")
    # A 200 carrying an error page would otherwise be shipped as a structure and
    # fail much later, inside the run.
    if not data.lstrip()[:6].upper().startswith((b"HEADER", b"ATOM", b"CRYST", b"REMARK",
                                                 b"TITLE", b"EXPDTA", b"MODEL")):
        raise ApoFetchError(
            f"what the PDB returned for {pdb_id.upper()} does not look like a PDB file."
        )
    return data
