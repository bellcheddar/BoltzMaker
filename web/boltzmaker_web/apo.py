"""Fetching an experimental apo structure from the PDB, for compare-sse.

Only used when someone names a PDB id on the Prepare form. The file is fetched
here, at prepare time, and shipped inside the bundle rather than downloaded on
the user's machine during the run: a campaign that has already started should
never stop to ask the network for something that could have been checked while
the user was still looking at the form.

**mmCIF first, legacy PDB second.** The legacy format cannot represent a large
modern entry -- it has hard limits on chain naming and atom count -- so the RCSB
simply does not publish a .pdb file for many recent depositions. Asking only for
.pdb produced a 404 and, from that, the flatly untrue message "the PDB has no
entry 9LL9": 9LL9 is a real cryo-EM structure of a 5-HT2A-Gq complex, published
as mmCIF only. compare-sse reads both through gemmi, and mmCIF is the canonical
form that always exists, so it is tried first and "no entry" is now only said
when neither format is there.

Failure is reported, never silent. If the id does not exist, or the PDB is
unreachable, the person who typed it is still sitting in front of the form and
can fix it or leave it blank -- whereas a bundle that quietly lost its apo
reference would simply produce no comparison, hours later, for no visible reason.
"""

from __future__ import annotations

import urllib.error
import urllib.request

RCSB_URL = "https://files.rcsb.org/download/{pdb_id}.{extension}"
# In preference order. mmCIF is canonical and complete; legacy PDB is a fallback
# for the rare entry served only in that form.
FORMATS = ("cif", "pdb")
TIMEOUT_SECONDS = 20
# An mmCIF entry is a few hundred KB; the largest run to some tens of MB. Well
# above anything real, well below anything that would bloat a bundle.
MAX_BYTES = 40 * 1024 * 1024

# What the first bytes of a real structure file look like. An mmCIF opens with a
# data block; a legacy PDB with one of its record types. A 200 carrying an error
# page matches neither, and would otherwise be shipped as a structure and fail
# much later, inside the run.
_CIF_PREFIXES = (b"data_", b"#")
_PDB_PREFIXES = (b"HEADER", b"ATOM", b"CRYST", b"REMARK", b"TITLE", b"EXPDTA", b"MODEL")


class ApoFetchError(RuntimeError):
    """The structure could not be fetched. The message is safe to show the user."""


def reference_path(pdb_id: str, extension: str = "cif") -> str:
    """Where the structure lives inside the campaign, as the spec refers to it.

    The extension is whichever format was actually retrieved: `Apo structure:` is
    read by gemmi, which infers the format from the name, so a .cif named .pdb
    would be a needless trap.
    """
    return f"reference/{pdb_id.lower()}.{extension}"


def _looks_like_structure(data: bytes, extension: str) -> bool:
    head = data.lstrip()[:8].upper()
    prefixes = _CIF_PREFIXES if extension == "cif" else _PDB_PREFIXES
    return head.startswith(tuple(prefix.upper() for prefix in prefixes))


def fetch(pdb_id: str, opener=urllib.request.urlopen) -> tuple[bytes, str]:
    """Download one PDB entry, preferring mmCIF.

    Returns (contents, extension). `opener` is injectable so tests never touch
    the network.
    """
    pdb_id = pdb_id.upper()
    last_transport_error = None

    for extension in FORMATS:
        url = RCSB_URL.format(pdb_id=pdb_id, extension=extension)
        try:
            with opener(url, timeout=TIMEOUT_SECONDS) as response:
                data = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue          # not published in this format; try the next one
            raise ApoFetchError(
                f"the PDB returned {exc.code} for {pdb_id}. Try again, or leave it blank "
                "to have an apo structure predicted instead."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Keep going: a transport failure on one format should not stop the
            # other from being tried, but if both fail it must still be reported.
            last_transport_error = exc
            continue

        if len(data) > MAX_BYTES:
            raise ApoFetchError(
                f"{pdb_id} is larger than {MAX_BYTES // 1024 // 1024}MB."
            )
        if not _looks_like_structure(data, extension):
            raise ApoFetchError(
                f"what the PDB returned for {pdb_id} does not look like a structure file."
            )
        return data, extension

    if last_transport_error is not None:
        raise ApoFetchError(
            f"could not reach the PDB to fetch {pdb_id} ({last_transport_error}). Try again, "
            "or leave it blank to have an apo structure predicted instead."
        )
    raise ApoFetchError(
        f"the PDB has no entry {pdb_id}, in either mmCIF or legacy PDB format -- check the "
        "id, or leave it blank to have an apo structure predicted instead."
    )
