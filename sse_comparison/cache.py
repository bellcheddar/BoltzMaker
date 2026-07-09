"""Content-addressed disk cache shared by the GPCRdb/KLIFS/PDBe API clients.

Keyed by sha256(sequence-or-accession), not by campaign -- unlike BoltzMaker's
per-campaign boltz_plip cache, a receptor/kinase lookup here is reusable across
every campaign that ever asks about the same sequence.
"""

import hashlib
import json
import os
from pathlib import Path


NOT_FOUND = {"status": "not_found"}


def cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cached_lookup(cache_dir: Path, key: str, fetch_fn, refresh: bool = False) -> object:
    """Returns the fetched payload, or None if the lookup is known to fail.

    fetch_fn() must return a JSON-serializable payload on success. Any exception it
    raises (network error, timeout, no-match) is caught here and cached as a
    "not_found" sentinel so a failing lookup isn't retried on every single run --
    nothing propagates past this function.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{key}.json"

    if cache_path.exists() and not refresh:
        try:
            payload = json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            payload = None
        if payload is not None:
            return None if payload == NOT_FOUND else payload

    try:
        payload = fetch_fn()
    except Exception:
        payload = None

    tmp_path = cache_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload if payload is not None else NOT_FOUND))
    os.replace(tmp_path, cache_path)
    return payload
