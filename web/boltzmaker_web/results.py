"""Reading and validating .bmz results files.

The .bmz is the contract between the two steps of Fully Automated Mode: the
bundle's pack_results.py writes one on the user's machine, and this module
reads it back. Its layout is fixed by runtime/pack_results.py.j2 and mirrored
by BMZ_VERSION in bundle.py; when those disagree, this module is the one that
has to say so plainly rather than guess.

Everything here treats the file as hostile. It arrives over an upload form from
an unauthenticated user, and a zip is the classic vehicle for path traversal
and decompression bombs, so extraction is bounded on every axis: entry count,
declared size, actual written size, compression ratio and resolved path. The
checks run as a full pass over the member list *before* anything is written, so
a hostile archive cannot get its safe-looking half extracted before the
dangerous member is noticed.

On the flags this module reads but never recomputes: BoltzMaker assigns
HIGH_CONFIDENCE_POOR_AFFINITY and LOW_CONFIDENCE_STRONG_AFFINITY from
within-campaign terciles, not absolute cutoffs (see apply_confidence_flags in
BoltzMaker.py). Only LOW_CONFIDENCE has a real absolute threshold, 0.5. That
distinction has to survive into the UI: a tercile flag says "relative to the
other 14 targets you ran", which is a different claim from "weak", and the
explorer must not redraw it as an absolute threshold line.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The layouts this module understands. A file declaring anything else is
# refused rather than parsed optimistically.
SUPPORTED_BMZ_VERSIONS = (1,)

# --- extraction limits -----------------------------------------------------
# A results file is a manifest, a handful of CSVs, one structure per target and
# one image per target. Even a large campaign is a few hundred members, so
# these caps are far above any real file and far below anything useful to an
# attacker.
MAX_ENTRIES = 4000
MAX_TOTAL_UNCOMPRESSED = 600 * 1024 * 1024
MAX_SINGLE_MEMBER = 128 * 1024 * 1024
# Not reachable by real data: structures and CSVs are text and compress well,
# but nowhere near this. A ratio this high is the signature of zero padding.
MAX_COMPRESSION_RATIO = 500

# The absolute threshold BoltzMaker uses for LOW_CONFIDENCE. Mirrored here so
# the explorer can draw the one line that genuinely is a fixed cutoff.
LOW_CONFIDENCE_THRESHOLD = 0.5

FLAG_NOTES = {
    "MISSING_OUTPUTS": "prediction did not complete -- re-run this target.",
    "LOW_CONFIDENCE": "low structural confidence (below 0.5).",
    "HIGH_CONFIDENCE_POOR_AFFINITY":
        "high structural confidence but weak predicted affinity, relative to the rest of this "
        "campaign -- verify the pocket and binding mode.",
    "LOW_CONFIDENCE_STRONG_AFFINITY":
        "strong predicted affinity but low structural confidence, relative to the rest of this "
        "campaign -- verify the pose before trusting it.",
    "LOW_POCKET_PLDDT": "low pLDDT near the specified pocket (approximate, complex-level proxy).",
}


class BmzError(ValueError):
    """The upload is not a usable .bmz. Message is safe to show the user
    directly and never carries raw exception internals."""


def _reject_unsafe_members(infos: list[zipfile.ZipInfo], extract_root: Path) -> None:
    if len(infos) > MAX_ENTRIES:
        raise BmzError(f"Rejected: {len(infos)} entries, over the {MAX_ENTRIES} limit.")

    total = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or name.startswith("\\"):
            raise BmzError(f"Rejected: absolute path in entry ({name!r}).")
        if ".." in Path(name).parts:
            raise BmzError(f"Rejected: path traversal ('..') in entry ({name!r}).")
        if info.file_size > MAX_SINGLE_MEMBER:
            raise BmzError(
                f"Rejected: {name!r} declares {info.file_size // 1024 // 1024}MB, over the "
                f"{MAX_SINGLE_MEMBER // 1024 // 1024}MB per-file limit."
            )
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > MAX_COMPRESSION_RATIO:
                raise BmzError(
                    f"Rejected: {name!r} has a compression ratio of {ratio:.0f}:1, which real "
                    "results data does not reach."
                )
        total += info.file_size

    if total > MAX_TOTAL_UNCOMPRESSED:
        raise BmzError(
            f"Rejected: would decompress to {total // 1024 // 1024}MB, over the "
            f"{MAX_TOTAL_UNCOMPRESSED // 1024 // 1024}MB limit."
        )

    # Separate resolve pass, run only after every cheap check has passed on every
    # member, so nothing is written before the whole list is known to be safe.
    root = extract_root.resolve()
    for info in infos:
        target = (root / info.filename).resolve()
        if target != root and not str(target).startswith(str(root) + "/"):
            raise BmzError(f"Rejected: entry {info.filename!r} resolves outside the extraction directory.")


def extract(zip_path: Path, extract_root: Path) -> None:
    """Validate and extract a .bmz. `extract_root` must already exist."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            _reject_unsafe_members(infos, extract_root)

            written = 0
            for info in infos:
                # Re-check against what is actually produced, not only what the
                # header declared: the central directory is attacker-controlled
                # and can understate a member's real size.
                with zf.open(info) as src:
                    dest = extract_root / info.filename
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open("wb") as out:
                        while chunk := src.read(1024 * 1024):
                            written += len(chunk)
                            if written > MAX_TOTAL_UNCOMPRESSED:
                                raise BmzError(
                                    "Rejected: the archive writes more data than it declared."
                                )
                            out.write(chunk)
    except zipfile.BadZipFile as exc:
        raise BmzError("Rejected: not a valid zip file.") from exc


def _num(raw: str):
    """CSV cell -> float, or None. BoltzMaker leaves a cell empty for a metric
    that does not apply to a target (no affinity prediction, a chain index the
    complex does not have), and 'NA' where a value was expected and missing.
    Both mean 'no number', and neither should become 0.0."""
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "" or raw.upper() in ("NA", "NAN", "NONE"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass
class Target:
    target_id: str
    display_name: str
    family_id: str
    family_group: str
    ligand_id: str
    ligand_smiles: str
    ligand_role: str
    flags: list[str] = field(default_factory=list)
    note: str = ""
    confidence: float = None
    ptm: float = None
    iptm: float = None
    complex_plddt: float = None
    affinity: float = None
    pic50: float = None
    pic50_std: float = None
    plip_status: str = ""
    plip_counts: dict[str, int] = field(default_factory=dict)
    has_structure: bool = False
    has_image: bool = False

    @property
    def plip_total(self) -> int:
        return sum(self.plip_counts.values())


@dataclass
class Results:
    manifest: dict[str, Any]
    targets: list[Target]
    families: list[str]
    campaign_name: str
    created_utc: str
    md_text: str = ""
    sse_rows: list[dict] = field(default_factory=list)

    @property
    def incomplete(self) -> int:
        """Targets the campaign was supposed to produce but did not."""
        expected = self.manifest.get("targets_expected") or 0
        return max(0, int(expected) - len(self.targets))

    #: Reports BoltzMaker generated, present in the file if the campaign wrote them.
    reports: list = field(default_factory=list)
    #: Every PLIP contact, by target_id -- the detail behind the counts.
    interactions: dict = field(default_factory=dict)
    #: UniProt accession by protein short name, when the Prepare form was told one.
    accessions: dict = field(default_factory=dict)

    @property
    def private(self) -> bool:
        """Whether this results file asked not to be kept.

        A file with no flag at all is treated as NOT private: privacy is opt-in,
        and results written before the option existed behave as they always did.
        """
        return bool(self.manifest.get("private"))

    @property
    def run_key(self) -> str:
        """Ties this file to the bundle that produced it, so an upload weeks later
        lands on the same Runs row rather than a second, unrelated one."""
        key = self.manifest.get("run_key")
        return str(key) if isinstance(key, (str, int)) else ""

    @property
    def has_affinity(self) -> bool:
        return any(t.pic50 is not None for t in self.targets)


_PLIP_COLUMNS = {
    "plip_hydrophobic_count": "hydrophobic",
    "plip_hydrogen_bonds_count": "hydrogen bonds",
    "plip_salt_bridges_count": "salt bridges",
    "plip_pi_stacks_count": "pi stacks",
    "plip_halogen_bonds_count": "halogen bonds",
}


#: PLIP writes one geometry column per interaction, as "key=value; key=value",
#: and the keys differ by interaction type -- a hydrogen bond carries donor and
#: acceptor types and a donor angle, a pi stack carries an offset and a T/P
#: classification. Rather than a column per key across every type (mostly empty),
#: the fields are parsed out here and labelled for display.
_GEOMETRY_LABELS = {
    "dist": ("Distance", "\u00c5"),
    "dist_h-a": ("H\u00b7\u00b7\u00b7A", "\u00c5"),
    "dist_d-a": ("D\u00b7\u00b7\u00b7A", "\u00c5"),
    "centdist": ("Centroid distance", "\u00c5"),
    "don_angle": ("Donor angle", "\u00b0"),
    "acc_angle": ("Acceptor angle", "\u00b0"),
    "angle": ("Ring angle", "\u00b0"),
    "offset": ("Ring offset", "\u00c5"),
    "type": ("Stacking", ""),
    "donortype": ("Donor atom", ""),
    "acceptortype": ("Acceptor atom", ""),
    "lig_group": ("Ligand group", ""),
    "sidechain": ("Side chain", ""),
    "protisdon": ("Protein is donor", ""),
    "protispos": ("Protein is positive", ""),
}

#: Atom indices are PLIP's internal numbering into its own parsed structure. They
#: identify nothing a reader can look up and change between runs, so they are
#: dropped rather than shown as if they meant something.
_GEOMETRY_SKIP = {"donoridx", "acceptoridx", "don_idx", "acc_idx"}

#: The keys that can hold the same number as the row's own distance column.
_GEOMETRY_DISTANCE_KEYS = {"dist", "centdist", "dist_d-a"}


def _parse_geometry(raw: str, distance: float | None = None) -> list[dict]:
    """"sidechain=True; dist_h-a=3.20; ..." into labelled fields, in PLIP's order.

    A field repeating the distance the row already leads with is dropped. PLIP
    puts the headline distance in its own column AND in the geometry string, under
    a name that changes with the interaction type, so every hydrophobic contact
    rendered as "3.53 A" followed by "Distance 3.53 A".
    """
    fields = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if key in _GEOMETRY_SKIP:
            continue
        label, unit = _GEOMETRY_LABELS.get(key, (key.replace("_", " "), ""))
        if distance is not None and key in _GEOMETRY_DISTANCE_KEYS:
            try:
                if abs(float(value) - distance) < 0.005:
                    continue
            except ValueError:
                pass
        if value in ("True", "False"):
            value = "yes" if value == "True" else "no"
        fields.append({"label": label, "value": value, "unit": unit})
    return fields


def _load_interactions(root: Path) -> dict[str, list[dict]]:
    """Every PLIP contact, by target_id.

    The counts in boltz_summary.csv are the same data summed, so this is the
    detail behind the numbers the Targets table already shows.
    """
    path = root / "summary" / "boltz_interactions.csv"
    if not path.is_file():
        return {}
    by_target: dict[str, list[dict]] = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            target = (row.get("target_id") or "").strip()
            if not target:
                continue
            resnr = (row.get("prot_resnr") or "").strip()
            by_target.setdefault(target, []).append({
                "type": (row.get("interaction_type") or "").strip(),
                "restype": (row.get("prot_restype") or "").strip(),
                "resnr": int(resnr) if resnr.isdigit() else None,
                "chain": (row.get("prot_chain") or "").strip(),
                "lig_restype": (row.get("lig_restype") or "").strip(),
                "lig_chain": (row.get("lig_chain") or "").strip(),
                "distance": _num(row.get("distance_A")),
                "geometry": _parse_geometry(row.get("geometry") or "",
                                            _num(row.get("distance_A"))),
            })
    return by_target


def load(root: Path) -> Results:
    """Read an extracted .bmz directory into structured records."""
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise BmzError(
            "No manifest.json in the upload -- this does not look like a .bmz results file. "
            "Upload the file the bundle wrote, not the campaign folder itself."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BmzError("Rejected: manifest.json is not valid JSON.") from exc
    if not isinstance(manifest, dict):
        # json.loads("3") is a perfectly valid int, and .get() on it raises
        # AttributeError rather than anything a caller would recognise.
        raise BmzError("Rejected: manifest.json is not a JSON object.")

    version = manifest.get("bmz_version")
    if version not in SUPPORTED_BMZ_VERSIONS:
        raise BmzError(
            f"This results file declares format version {version!r}, and this site understands "
            f"{', '.join(str(v) for v in SUPPORTED_BMZ_VERSIONS)}. It was probably written by a "
            "different version of the bundle -- prepare a fresh one and re-run."
        )

    summary = root / "summary" / "boltz_summary.csv"
    if not summary.is_file():
        raise BmzError("Rejected: the results file has a manifest but no summary/boltz_summary.csv.")

    with summary.open(newline="", encoding="utf-8", errors="replace") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise BmzError("The summary in this results file has no rows -- no target completed.")

    targets: list[Target] = []
    for row in rows:
        target_id = (row.get("target_id") or "").strip()
        if not target_id:
            continue
        flags = [f for f in (row.get("flags") or "").split(";") if f]
        counts = {}
        for column, label in _PLIP_COLUMNS.items():
            value = _num(row.get(column))
            if value:
                counts[label] = int(value)
        targets.append(Target(
            target_id=target_id,
            display_name=(row.get("display_name") or target_id).strip(),
            family_id=(row.get("family_id") or "").strip(),
            family_group=(row.get("family_group") or "").strip(),
            ligand_id=(row.get("ligand_id") or "").strip(),
            ligand_smiles=(row.get("ligand_smiles") or "").strip(),
            ligand_role=(row.get("ligand_role") or "").strip(),
            flags=flags,
            note=(row.get("notes") or "").strip(),
            confidence=_num(row.get("confidence_score")),
            ptm=_num(row.get("ptm")),
            iptm=_num(row.get("iptm")),
            complex_plddt=_num(row.get("complex_plddt")),
            affinity=_num(row.get("affinity_pred_value")),
            # The ensemble mean is the headline number when affinity ran more
            # than one sample; plain pIC50 is the single-sample case.
            pic50=_num(row.get("pIC50_ensemble_mean")) or _num(row.get("pIC50")),
            pic50_std=_num(row.get("pIC50_ensemble_std")),
            plip_status=(row.get("plip_status") or "").strip(),
            plip_counts=counts,
            has_structure=(root / "structures" / f"{target_id}.cif").is_file(),
            has_image=(root / "plip" / f"{target_id}.png").is_file(),
        ))

    if not targets:
        raise BmzError("The summary has rows but none carry a target_id -- the file looks corrupt.")

    sse_rows: list[dict] = []
    sse_csv = root / "summary" / "boltz_sse_comparison.csv"
    if sse_csv.is_file():
        with sse_csv.open(newline="", encoding="utf-8", errors="replace") as fh:
            sse_rows = list(csv.DictReader(fh))

    # config.json is the website's own record of the campaign, written at Prepare
    # time and carried through the bundle. The UniProt accessions live here rather
    # than in boltz_input.md because they are metadata for this page, not an
    # instruction to the pipeline -- BoltzMaker.py never has to learn a new key.
    accessions: dict[str, str] = {}
    config_path = root / "config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            raw = config.get("uniprot") if isinstance(config, dict) else None
            if isinstance(raw, dict):
                accessions = {str(k): str(v) for k, v in raw.items() if v}
        except (json.JSONDecodeError, OSError):
            accessions = {}

    md_path = root / "boltz_input.md"
    families = sorted({t.family_id for t in targets if t.family_id})

    # Only the reports this campaign actually produced: compare-sse writes its page
    # only when a family had an apo structure, so its absence is normal.
    known_reports = (
        ("boltz_dashboard.html", "Full dashboard",
         "Every panel BoltzMaker computed: campaign summary, ligand preparation and 2D "
         "structures, ranked pIC50 and confidence, selectivity heatmap, interaction counts, "
         "per-family interaction fingerprints and a binding-site panel per target."),
        ("boltz_sse_comparison.html", "Secondary structure (apo vs holo)",
         "Per-motif Ca RMSD, the motif-by-target heatmap, and the per-residue detail behind "
         "the comparison."),
    )
    reports = [
        {"name": name, "title": title, "blurb": blurb,
         "bytes": (root / "reports" / name).stat().st_size}
        for name, title, blurb in known_reports
        if (root / "reports" / name).is_file()
    ]

    return Results(
        manifest=manifest,
        targets=targets,
        families=families,
        campaign_name=str(manifest.get("campaign_name") or "campaign"),
        created_utc=str(manifest.get("created_utc") or ""),
        md_text=md_path.read_text(encoding="utf-8", errors="replace") if md_path.is_file() else "",
        sse_rows=sse_rows,
        reports=reports,
        interactions=_load_interactions(root),
        accessions=accessions,
    )


def _apo_rmsd(sse_rows: list[dict]) -> dict[str, dict]:
    """Per target, its Ca RMSD against the apo reference.

    compare-sse measures per motif, not per chain, so there is no single number
    in the file to read. This is the residue-weighted mean across a target's
    motifs -- weighted because a 4-residue loop and a 30-residue helix are not
    equal evidence, and a plain mean lets the shortest motif in the set move the
    figure as much as the longest.

    Reported with the motif count beside it so it reads as what it is: an
    aggregate over the regions compare-sse could align, not a global
    superposition of the whole chain.
    """
    totals: dict[str, list] = {}
    for row in sse_rows:
        target = (row.get("target_stem") or "").strip()
        raw = (row.get("ca_rmsd_A") or "").strip()
        if not target or raw in ("", "N/A"):
            continue
        try:
            rmsd = float(raw)
            weight = float(row.get("n_residues") or 0)
        except ValueError:
            continue
        if weight <= 0:
            continue
        entry = totals.setdefault(target, [0.0, 0.0, 0])
        entry[0] += rmsd * weight
        entry[1] += weight
        entry[2] += 1
    return {
        target: {"rmsd": round(weighted / weight, 2), "motifs": count}
        for target, (weighted, weight, count) in totals.items() if weight
    }


def to_json(results: Results) -> str:
    """The payload the explorer's JavaScript reads. Serialised once, server-side,
    rather than re-fetched per view."""
    apo = _apo_rmsd(results.sse_rows)
    return json.dumps({
        "campaign": results.campaign_name,
        "created": results.created_utc,
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "flag_notes": FLAG_NOTES,
        "families": results.families,
        "has_affinity": results.has_affinity,
        "targets": [
            {
                "id": t.target_id, "name": t.display_name, "family": t.family_id,
                "group": t.family_group, "ligand": t.ligand_id, "smiles": t.ligand_smiles,
                "role": t.ligand_role, "flags": t.flags, "note": t.note,
                "confidence": t.confidence, "ptm": t.ptm, "iptm": t.iptm,
                "plddt": t.complex_plddt, "affinity": t.affinity,
                "pic50": t.pic50, "pic50_std": t.pic50_std,
                "plip_status": t.plip_status, "plip": t.plip_counts, "plip_total": t.plip_total,
                "structure": t.has_structure, "image": t.has_image,
                "interactions": results.interactions.get(t.target_id, []),
                "apo_rmsd": apo.get(t.target_id),
            }
            for t in results.targets
        ],
    })
