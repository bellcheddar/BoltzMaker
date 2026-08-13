"""The Runs archive: what the site keeps when a run is not marked private.

Two files per run at most -- the bundle that was downloaded, and the results file
that was uploaded back -- plus one line in a JSONL registry tying them together.

**Privacy is opt-in and stateless.** A bundle built with "Keep private" carries a
key, pack_results copies that key into the results manifest, and anything
carrying one is never written here. Nothing on the server needs to remember which
runs were private, because a private run deliberately leaves nothing to remember.
A file with no key is treated as not private: that is what the option describes,
and it means results produced before the option existed behave as they did.

**The archive is capped, hard.** This droplet has ~16GB free and a .bmz can be
200MB. An unbounded archive is a slow-motion disk-full outage on a box that also
serves three other apps -- and this one has already had 1.9GB of stray campaign
data pushed onto it once. Every write prunes the oldest entries until the archive
is under both a byte cap and a count cap, and what was pruned is recorded rather
than silently vanishing.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGISTRY_NAME = "registry.jsonl"

# Deliberately modest. Raise them only alongside a look at `df -h` on the host.
MAX_TOTAL_BYTES = 3 * 1024 * 1024 * 1024   # 3GB across every archived file
MAX_RUNS = 200                              # and never more than this many runs


def new_private_key() -> str:
    """Opaque, unguessable, and never stored server-side -- it exists only inside
    the user's own bundle and the results file that bundle writes."""
    return secrets.token_urlsafe(16)


@dataclass
class Run:
    key: str
    campaign: str
    created: str
    targets: int = 0
    bundle_name: str = ""
    bundle_bytes: int = 0
    results_name: str = ""
    results_bytes: int = 0
    results_uploaded: str = ""
    note: str = ""

    @property
    def has_bundle(self) -> bool:
        return bool(self.bundle_name)

    @property
    def has_results(self) -> bool:
        return bool(self.results_name)

    def to_json(self) -> dict[str, Any]:
        return dict(key=self.key, campaign=self.campaign, created=self.created,
                    targets=self.targets, bundle_name=self.bundle_name,
                    bundle_bytes=self.bundle_bytes, results_name=self.results_name,
                    results_bytes=self.results_bytes, results_uploaded=self.results_uploaded,
                    note=self.note)


class Archive:
    """File-backed, append-mostly. No database: this is a handful of rows on one
    small host, and a JSONL file survives a kill -9 mid-write with at worst one
    unreadable line, which the reader skips."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.bundles = self.root / "bundles"
        self.results = self.root / "results"
        for directory in (self.root, self.bundles, self.results):
            directory.mkdir(parents=True, exist_ok=True)

    # ---- reading ---------------------------------------------------------

    @property
    def registry(self) -> Path:
        return self.root / REGISTRY_NAME

    def _rows(self) -> dict[str, Run]:
        runs: dict[str, Run] = {}
        if not self.registry.is_file():
            return runs
        for line in self.registry.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue          # a torn final write; skip it rather than fail the page
            if not isinstance(record, dict) or not record.get("key"):
                continue
            existing = runs.get(record["key"])
            merged = {**(existing.to_json() if existing else {}), **record}
            runs[record["key"]] = Run(**{k: v for k, v in merged.items()
                                         if k in Run.__dataclass_fields__})
        return runs

    def list(self) -> list[Run]:
        """Newest first. A run appears once, however many times it was written."""
        return sorted(self._rows().values(), key=lambda r: r.created, reverse=True)

    def get(self, key: str) -> Run | None:
        return self._rows().get(key)

    def path_for(self, run: Run, kind: str) -> Path | None:
        name = run.bundle_name if kind == "bundle" else run.results_name
        if not name:
            return None
        root = (self.bundles if kind == "bundle" else self.results).resolve()
        path = (root / name).resolve()
        # The names are ours, but they end up in URLs, so resolve and confine.
        if path.parent != root or not path.is_file():
            return None
        return path

    # ---- writing ---------------------------------------------------------

    def _append(self, record: dict[str, Any]) -> None:
        with self.registry.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def record_bundle(self, key: str, campaign: str, targets: int, filename: str,
                      content: bytes) -> Run:
        stored = self.bundles / f"{key}.command"
        stored.write_bytes(content)
        run = Run(key=key, campaign=campaign,
                  created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  targets=targets, bundle_name=stored.name, bundle_bytes=len(content),
                  note=filename)
        self._append(run.to_json())
        self.prune()
        return run

    def record_results(self, key: str, campaign: str, source: Path, targets: int) -> Run:
        stored = self.results / f"{key}.bmz"
        shutil.copyfile(source, stored)
        existing = self.get(key)
        run = Run(
            key=key,
            campaign=campaign or (existing.campaign if existing else campaign),
            created=existing.created if existing else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            targets=targets or (existing.targets if existing else 0),
            bundle_name=existing.bundle_name if existing else "",
            bundle_bytes=existing.bundle_bytes if existing else 0,
            results_name=stored.name, results_bytes=stored.stat().st_size,
            results_uploaded=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            note=existing.note if existing else "",
        )
        self._append(run.to_json())
        self.prune()
        return run

    # ---- retention -------------------------------------------------------

    def total_bytes(self) -> int:
        total = 0
        for directory in (self.bundles, self.results):
            for path in directory.glob("*"):
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total

    def prune(self) -> list[str]:
        """Drop the oldest runs until the archive is inside both caps.

        Returns the keys removed. Callers do not have to care, but the registry
        records the removal so a missing run is explainable rather than a mystery.
        """
        runs = self.list()                       # newest first
        removed: list[str] = []

        while len(runs) - len(removed) > MAX_RUNS and runs:
            removed.append(runs[-(len(removed) + 1)].key)

        def bytes_after(dropped: set) -> int:
            return sum(r.bundle_bytes + r.results_bytes for r in runs if r.key not in dropped)

        dropped = set(removed)
        index = len(runs) - 1
        while bytes_after(dropped) > MAX_TOTAL_BYTES and index >= 0:
            if runs[index].key not in dropped:
                dropped.add(runs[index].key)
                removed.append(runs[index].key)
            index -= 1

        for key in removed:
            run = self.get(key)
            if run is None:
                continue
            for kind in ("bundle", "results"):
                path = self.path_for(run, kind)
                if path:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            self._append({"key": key, "campaign": run.campaign, "created": run.created,
                          "bundle_name": "", "results_name": "", "bundle_bytes": 0,
                          "results_bytes": 0,
                          "note": "pruned: the archive is capped and this was the oldest"})
        return removed
