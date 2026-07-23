"""Safe zip upload handling: zip-slip and zip-bomb guards.

Every /generate, /preflight, /analyze upload passes through here before a
single byte touches disk. A zip-slip attempt (a member path escaping the
extraction root) rejects the WHOLE upload -- a strong hostile-intent signal,
not worth partial extraction of the "safe" remaining members.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500MB -- generous headroom over the
                                             # 200MB compressed upload cap (MAX_CONTENT_LENGTH),
                                             # catches pathological compression ratios
                                             # without penalizing a legitimately large
                                             # multi-target campaign's many CIFs.
MAX_ENTRY_COUNT = 5000  # catches a classic high-entry-count zip bomb independent of byte size


class UnsafeZipError(ValueError):
    """Raised for any zip-slip attempt, zip-bomb signal, or otherwise
    malformed/hostile upload. The message is safe to show the user directly
    (never includes raw exception internals)."""


def _reject_traversal_paths(names: list[str]) -> None:
    for name in names:
        if name.startswith("/") or name.startswith("\\"):
            raise UnsafeZipError(f"Rejected: absolute path in zip entry ({name!r}).")
        # Cheap pre-check before the resolve()-based one below -- catches the
        # common case without needing a real filesystem lookup.
        parts = Path(name).parts
        if ".." in parts:
            raise UnsafeZipError(f"Rejected: path traversal ('..') in zip entry ({name!r}).")


def safe_extract(zip_path: Path, extract_root: Path) -> None:
    """Validate and extract `zip_path` into `extract_root`.

    Raises UnsafeZipError on any zip-slip attempt, oversized/entry-count zip
    bomb, or corrupt zip file. `extract_root` must already exist and be
    empty -- caller's responsibility (this module never creates or cleans up
    the destination itself, see views_analyze.py's tempfile.mkdtemp() usage).
    """
    extract_root = extract_root.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRY_COUNT:
                raise UnsafeZipError(
                    f"Rejected: zip contains {len(infos)} entries, over the {MAX_ENTRY_COUNT} limit."
                )
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                mb = total_uncompressed / (1024 * 1024)
                raise UnsafeZipError(
                    f"Rejected: zip would decompress to {mb:.0f}MB, over the "
                    f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB limit."
                )

            names = [info.filename for info in infos]
            _reject_traversal_paths(names)

            # Second pass: resolve-and-check-descendant for every entry. Done as its
            # own pass (not fused into the loop above) so a traversal attempt anywhere
            # in the archive is caught before ANY member is extracted -- no partial
            # extraction of "the safe-looking half" of a hostile zip.
            for info in infos:
                target = (extract_root / info.filename).resolve()
                if not str(target).startswith(str(extract_root) + "/") and target != extract_root:
                    raise UnsafeZipError(
                        f"Rejected: zip entry {info.filename!r} resolves outside the "
                        "extraction directory."
                    )

            zf.extractall(extract_root)
    except zipfile.BadZipFile as exc:
        raise UnsafeZipError("Rejected: not a valid zip file.") from exc
