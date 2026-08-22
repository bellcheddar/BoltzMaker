"""Rebuild the Prepare form's saved page from a campaign spec.

Bundles built before the wizard stored its own state -- every example campaign,
and every bundle in the Runs archive -- carry `boltz_input.md` but no
`page_state.json`, so uploading one to Step 1 could only report that there was
nothing to restore. The spec does describe the campaign, though, so the page can
be reconstructed from it.

The reason this is delicate rather than mechanical: a hand-written spec can say
things the form has no field for, and a derivation that quietly drops them
produces a form which *looks* right, rebuilds into a different campaign, and
says nothing. On the ADRB2 example that would silently discard per-protein
`Ligands:` scoping -- the one thing that example exists to demonstrate, since a
G protein only forms a ternary complex with an agonist-bound receptor.

So every derivation is checked: the page is rebuilt into a spec and compared,
semantically, against the one it came from. A mismatch refuses the file and
names what differs, rather than handing back a plausible lie.
"""

from __future__ import annotations

import re

#: Bumped in step with form_state.js's own STATE_VERSION.
STATE_VERSION = 1

_BLOCK_START = ("Protein:", "Partner:", "Ligand:")

#: Statement lines live at the top level of a spec but the examples also write them
#: directly after a block, where a naive parser absorbs them as that block's fields
#: and then drops them. Recognised by key wherever they appear.
_STATEMENTS = ("Covalent bond", "Distance constraint")

#: Fail closed. Anything a block can say that is not listed here is a directive this
#: derivation has never been taught, and the safe answer is to refuse the file rather
#: than return a form that silently means something else. An EGFR bundle's
#: `Covalent bond:` was absorbed and dropped exactly this way before the check existed.
_KNOWN_FIELDS = {
    "Protein": {"Sequence", "Partners", "Ligands", "Apo structure", "Apo chain",
                "Pocket source", "Pocket contact", "Family type", "Group"},
    "Partner": {"Sequence"},
    "Ligand": {"SMILES", "CCD", "Role", "Class"},
}


class DerivationError(Exception):
    """The spec cannot be represented as a form, and we will not pretend."""


def _blocks(md_text: str) -> tuple[dict, list[tuple[str, str, list[tuple[str, str]]]]]:
    """Split a spec into (settings, [(kind, name, [(key, value)])]).

    Comments and blank lines go; a spec's prose header is not part of what the
    form holds, and the examples are mostly prose.
    """
    settings: dict[str, str] = {}
    blocks: list[tuple[str, str, list[tuple[str, str]]]] = []
    current: list[tuple[str, str]] | None = None
    in_settings = False

    for raw in md_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "Settings:":
            in_settings, current = True, None
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in _STATEMENTS:
            blocks.append(("Statement", line, []))
            continue
        if line.startswith(_BLOCK_START):
            in_settings = False
            current = []
            blocks.append((key, value, current))
            continue
        if in_settings:
            settings[key] = value
        elif current is not None:
            current.append((key, value))
        else:
            # A statement line (Covalent bond / Distance constraint / Pocket
            # contact outside a block). Kept as a pseudo-block so nothing is
            # dropped unnoticed -- the round-trip check will catch it if the form
            # cannot carry it.
            blocks.append(("Statement", line, []))
    return settings, blocks


def _one(fields: list[tuple[str, str]], key: str, default: str = "") -> str:
    for k, v in fields:
        if k == key:
            return v
    return default


def _all(fields: list[tuple[str, str]], key: str) -> list[str]:
    return [v for k, v in fields if k == key]


_POCKET_RE = re.compile(
    r"^(?P<owner>\S+)\s+residue\s+(?P<pos>\d+)\s+as\s+(?P<code>\S+)$", re.IGNORECASE)


_COVALENT_RE = re.compile(
    r"^Covalent bond:\s+(?P<owner>\S+)\s+residue\s+(?P<r1>\S+)\s+atom\s+(?P<a1>\S+)"
    r"\s+to\s+(?P<other>\S+)\s+residue\s+(?P<r2>\S+)\s+atom\s+(?P<a2>\S+)$", re.I)
_DISTANCE_RE = re.compile(
    r"^Distance constraint:\s+(?P<owner>\S+)\s+residue\s+(?P<r1>\S+)\s+to\s+"
    r"(?P<other>\S+)\s+residue\s+(?P<r2>\S+)\s+within\s+(?P<dist>\S+)\s+Angstrom$", re.I)


def _constraint_row(sentence: str) -> dict:
    """The exact inverse of wizard.Constraint.to_sentence().

    Written against that function rather than against the examples, so the two
    cannot drift apart without a test noticing.
    """
    m = _COVALENT_RE.match(sentence)
    if m:
        return {"constraint_kind[]": "covalent", "constraint_owner[]": m.group("owner"),
                "constraint_residue1[]": m.group("r1"), "constraint_atom1[]": m.group("a1"),
                "constraint_other[]": m.group("other"),
                "constraint_residue2[]": m.group("r2"), "constraint_atom2[]": m.group("a2"),
                "constraint_distance[]": ""}
    m = _DISTANCE_RE.match(sentence)
    if m:
        return {"constraint_kind[]": "distance", "constraint_owner[]": m.group("owner"),
                "constraint_residue1[]": m.group("r1"), "constraint_atom1[]": "",
                "constraint_other[]": m.group("other"),
                "constraint_residue2[]": m.group("r2"), "constraint_atom2[]": "",
                "constraint_distance[]": m.group("dist")}
    raise DerivationError(f"could not read the constraint {sentence!r}")


def derive(md_text: str, config: dict | None = None) -> dict:
    """Spec -> the page_state shape form_state.js writes and reads.

    Raises DerivationError when the spec uses something the form cannot hold.
    """
    config = config or {}
    settings, blocks = _blocks(md_text)

    constraint_rows = [_constraint_row(value)
                       for kind, value, _ in blocks if kind == "Statement"]

    # Fail closed on anything unrecognised. A directive this function has never been
    # taught must refuse the file, not vanish into a form that then rebuilds into a
    # different campaign.
    for kind, name, fields in blocks:
        if kind == "Statement":
            continue
        unknown = sorted({k for k, _ in fields} - _KNOWN_FIELDS.get(kind, set()))
        if unknown:
            raise DerivationError(
                f"{kind} '{name}' uses {', '.join(unknown)}, which the Prepare form "
                "has no field for -- loading it would quietly drop it.")

    proteins = [(name, f) for kind, name, f in blocks if kind == "Protein"]
    partners = [(name, f) for kind, name, f in blocks if kind == "Partner"]
    ligands = [(name, f) for kind, name, f in blocks if kind == "Ligand"]

    # Apo companions are generated by the assembler, not typed by anyone: a block
    # scoped to `Ligands: none`. Recovering them as protein rows would double the
    # campaign on every re-download, so they are dropped and recorded instead as
    # the apo_predict tick on the protein they belong to.
    companions = {name for name, f in proteins if _one(f, "Ligands").lower() == "none"}
    real = [(name, f) for name, f in proteins if name not in companions]
    if not real:
        raise DerivationError("the spec has no protein blocks the form can show")

    # Which protein each companion belongs to, read off the reference that points at
    # it: `Apo structure: boltz_cif/<companion>_model_0.cif`. Matching by sequence
    # instead looks reasonable and is wrong the moment two Protein blocks share one
    # sequence -- which is the whole idiom of the 5HT2 example, where three receptor
    # variants share a construct and the first match swallowed all three companions.
    # Two passes, because the reference only names the companion when there is no
    # experimental apo to prefer. Where a real structure is named the companion is
    # still predicted -- it is a target in its own right -- but nothing points at it,
    # so it has to be matched on sequence instead.
    companion_of: dict[str, str] = {}
    claimed: set[str] = set()
    for pname, pf in real:
        m = re.match(r"^boltz_cif/(?P<name>.+)_model_0\.cif$", _one(pf, "Apo structure"))
        if m and m.group("name") in companions:
            companion_of[pname] = m.group("name")
            claimed.add(m.group("name"))
    by_sequence: dict[str, list[str]] = {}
    for cname in companions - claimed:
        by_sequence.setdefault(
            _one(dict((n, f) for n, f in proteins)[cname], "Sequence"), []).append(cname)
    for pname, pf in real:
        if pname in companion_of:
            continue
        pool = by_sequence.get(_one(pf, "Sequence"))
        if pool:
            companion_of[pname] = pool.pop(0)
    leftover = sorted(companions - set(companion_of.values()))
    if leftover:
        raise DerivationError(
            "could not tell which protein these ligand-free companions belong to: "
            + ", ".join(leftover))

    protein_rows = []
    for name, f in real:
        apo = _one(f, "Apo structure")
        # A predicted companion's own output file is not a reference the user chose;
        # it is the companion, and it comes back as the tick rather than as a path.
        apo_is_companion = apo.startswith("boltz_cif/")
        pockets: dict[str, list[int]] = {}
        for raw in _all(f, "Pocket contact"):
            m = _POCKET_RE.match(raw)
            if not m:
                raise DerivationError(f"could not read the pocket contact {raw!r}")
            pockets.setdefault(m.group("code"), []).append(int(m.group("pos")))

        source = _one(f, "Pocket source")
        pocket_pdb = pocket_ligand = ""
        if source:
            m = re.match(r"^(?P<code>\S+)\s+from\s+(?P<pdb>\S+)$", source, re.IGNORECASE)
            if m:
                pocket_ligand, pocket_pdb = m.group("code"), m.group("pdb")

        scoped = [x.strip() for x in _one(f, "Ligands").split(",") if x.strip()]
        protein_rows.append({
            "protein_name[]": name,
            "protein_sequence[]": _one(f, "Sequence"),
            "protein_partners[]": _one(f, "Partners"),
            "protein_ligands[]": ", ".join(scoped),
            "protein_apo_pdb[]": "",
            "protein_apo_path[]": "" if apo_is_companion else apo,
            "protein_apo_predict[]": bool(name in companion_of),
            "protein_apo_chain[]": _one(f, "Apo chain"),
            "protein_apo_name[]": companion_of.get(name, ""),
            "protein_uniprot[]": (config.get("uniprot") or {}).get(name, ""),
            "protein_group[]": _one(f, "Group"),
            "protein_family_type[]": _one(f, "Family type"),
            "pockets": [{"code": code, "residues": sorted(pos), "owner": name,
                         "pdb": pocket_pdb, "ligand": pocket_ligand}
                        for code, pos in sorted(pockets.items())],
        })

    partner_rows = [{
        "partner_name[]": name,
        "partner_sequence[]": _one(f, "Sequence"),
        "partner_uniprot[]": (config.get("uniprot") or {}).get(name, ""),
    } for name, f in partners]

    ligand_rows = []
    for name, f in ligands:
        ccd, smiles = _one(f, "CCD"), _one(f, "SMILES")
        ligand_rows.append({
            "ligand_name[]": name,
            "ligand_kind[]": "ccd" if ccd else "smiles",
            "ligand_value[]": ccd or smiles,
            "ligand_role[]": _one(f, "Role"),
            "ligand_class[]": _one(f, "Class"),
        })

    run_settings = dict(config.get("run_settings") or {})
    scalars: dict[str, object] = {
        "campaign_name": config.get("campaign_name", ""),
        "predict_affinity": settings.get("Predict affinity", "no").lower() == "yes",
        # "Confine to receptor" is only written when off, so absence means on.
        "confine_to_receptor": settings.get("Confine to receptor", "yes").lower() != "no",
        "compare_sse": bool(companion_of) or any(
            r["protein_apo_path[]"] for r in protein_rows),
        "pocket_distance": settings.get("Pocket distance", ""),
        "targets_per_invocation": settings.get("Targets per invocation", ""),
    }
    for key, value in run_settings.items():
        scalars.setdefault(key, value)

    return {
        "version": STATE_VERSION,
        "derived_from_spec": True,   # so the page can say where it came from
        "scalars": scalars,
        "groups": {
            "protein": protein_rows,
            "partner": partner_rows,
            "ligand": ligand_rows,
            "constraint": constraint_rows,
        },
    }


#: What the assembler writes when nobody says otherwise. Absent means these.
_SETTING_DEFAULTS = {
    "Output folder": "./boltz_yamls",
    "Predict affinity": "no",
    "Confine to receptor": "yes",
}


def _canonical(md_text: str) -> dict:
    """A spec reduced to what it *means*, for comparing two of them.

    Comments, blank lines, block order and field order within a block all vary
    freely between a hand-written spec and a generated one, and none of them
    changes the campaign. What must not vary is the set of blocks and the
    directives inside each.
    """
    settings, blocks = _blocks(md_text)
    # A spec that omits a setting means its default, so an omission and the default
    # spelled out are the same campaign. Filling them in on both sides stops a
    # hand-written spec with no Settings block reading as different from the one
    # rebuilt from it, which is every example campaign.
    canonical_settings = dict(_SETTING_DEFAULTS)
    canonical_settings.update(settings)
    out: dict = {"settings": canonical_settings, "statements": [], "blocks": {}}
    for kind, name, fields in blocks:
        if kind == "Statement":
            out["statements"].append(" ".join(name.split()))
            continue
        key = f"{kind}:{name}"
        pairs = [(k, " ".join(v.split())) for k, v in fields
                 if not (kind == "Ligand" and k == "Class" and v.strip() == "experimental")]
        out["blocks"][key] = sorted(pairs)
    out["statements"].sort()
    return out


def diff_specs(original: str, rebuilt: str) -> list[str]:
    """Human-readable differences between two specs, empty when equivalent.

    This is the check that makes derivation safe to ship. Deriving a form from a
    spec is guesswork until the form is rebuilt into a spec and the two agree;
    without it, a directive the derivation forgets simply disappears and the
    campaign quietly changes shape on the next download.
    """
    a, b = _canonical(original), _canonical(rebuilt)
    notes: list[str] = []

    for key in sorted(set(a["settings"]) | set(b["settings"])):
        if a["settings"].get(key) != b["settings"].get(key):
            notes.append(f"setting {key}: {a['settings'].get(key)!r} -> {b['settings'].get(key)!r}")

    missing = sorted(set(a["blocks"]) - set(b["blocks"]))
    added = sorted(set(b["blocks"]) - set(a["blocks"]))
    for key in missing:
        notes.append(f"lost {key}")
    for key in added:
        notes.append(f"gained {key}")

    for key in sorted(set(a["blocks"]) & set(b["blocks"])):
        if a["blocks"][key] != b["blocks"][key]:
            lost = [f"{k}: {v}" for k, v in a["blocks"][key] if (k, v) not in b["blocks"][key]]
            gained = [f"{k}: {v}" for k, v in b["blocks"][key] if (k, v) not in a["blocks"][key]]
            if lost:
                notes.append(f"{key} lost {'; '.join(lost[:4])}")
            if gained:
                notes.append(f"{key} gained {'; '.join(gained[:4])}")

    if a["statements"] != b["statements"]:
        for s in a["statements"]:
            if s not in b["statements"]:
                notes.append(f"lost statement {s}")
        for s in b["statements"]:
            if s not in a["statements"]:
                notes.append(f"gained statement {s}")
    return notes


def _form_data(state: dict) -> list[tuple[str, str]]:
    """Flatten a page back into the POST body the Prepare form would send.

    Deliberately goes through the real form fields rather than building
    dataclasses directly: the check is worthless if it exercises a second,
    parallel implementation of what the form does.
    """
    data: list[tuple[str, str]] = []
    for key, value in (state.get("scalars") or {}).items():
        if isinstance(value, bool):
            if value:
                data.append((key, "on"))
        elif value not in (None, ""):
            data.append((key, str(value)))
    if (state.get("groups") or {}).get("protein"):
        data.append(("protein_apo_predict[]", "-1"))
    for group in ("protein", "partner", "ligand", "constraint"):
        for index, row in enumerate((state.get("groups") or {}).get(group) or []):
            for field, value in row.items():
                if field == "pockets":
                    continue
                if isinstance(value, bool):
                    # The apo tick posts its row ordinal, not "on" -- an unticked box
                    # posts nothing at all, so the array is shorter than the others.
                    if value:
                        data.append((field, str(index)))
                else:
                    # Empty values are posted too, not skipped. These are parallel
                    # arrays read by index: dropping a blank shortens one of them and
                    # every later row's fields shift up a slot. That is how a covalent
                    # bond with no distance silently disappeared -- the form's own
                    # parser has a guard against exactly this shape of bug.
                    data.append((field, "" if value is None else str(value)))
    return data


def rebuild_spec(state: dict, app) -> str:
    """Push a derived page through the real form parser and assembler."""
    from . import views_new, wizard

    # MultiDict, not a list of pairs: werkzeug's EnvironBuilder calls .items() on
    # what it is given, and every field here is a repeated `name[]` key that a plain
    # dict would collapse to its last value.
    from werkzeug.datastructures import MultiDict

    with app.test_request_context(method="POST", data=MultiDict(_form_data(state))):
        predict_affinity, proteins, partners, ligands, confine = views_new._parse_form()

    # Pockets are attached after parsing in the live route too: they are resolved by
    # alignment against a downloaded structure, which is a network step _parse_form
    # has no business doing. Here they come from the page, already resolved.
    by_name = {p.name: p for p in proteins}
    pocket_distance = 0.0
    for row in (state.get("groups") or {}).get("protein") or []:
        protein = by_name.get(row.get("protein_name[]", ""))
        if protein is None:
            continue
        for pocket in row.get("pockets") or []:
            protein.pockets[pocket["code"]] = list(pocket["residues"])
            if pocket.get("pdb"):
                protein.pocket_pdb = pocket["pdb"]
                protein.pocket_ligand = pocket.get("ligand", "")
    raw_distance = (state.get("scalars") or {}).get("pocket_distance")
    if raw_distance:
        pocket_distance = float(raw_distance)

    return wizard.assemble_boltz_input_md(
        predict_affinity, proteins, partners, ligands,
        compare_sse=bool((state.get("scalars") or {}).get("compare_sse")),
        confine_to_receptor=confine,
        pocket_distance=pocket_distance,
        targets_per_invocation=(state.get("scalars") or {}).get("targets_per_invocation", ""),
    )


def derive_verified(md_text: str, config: dict | None = None, app=None) -> dict:
    """Derive a page and prove it rebuilds into the same campaign.

    Returns the page. Raises DerivationError, naming the differences, when
    rebuilding it would produce a different spec -- which is the only way to know
    that loading the form and pressing download is safe.
    """
    state = derive(md_text, config)
    if app is None:
        return state
    try:
        rebuilt = rebuild_spec(state, app)
    except Exception as exc:                       # noqa: BLE001 - reported, not raised
        raise DerivationError(f"the page could not be rebuilt into a spec: {exc}") from exc
    notes = diff_specs(md_text, rebuilt)
    if notes:
        raise DerivationError(
            "loading this bundle would change the campaign: " + "; ".join(notes[:6]))
    return state
