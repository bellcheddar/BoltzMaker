"""The AlphaFold model of a target's protein, superposed onto the prediction.

Three problems, in order.

**Which model.** Nothing in a campaign records a UniProt accession, so it is
resolved in three steps, most trustworthy first: the accession the person typed
on the Prepare form, then an exact sequence match, then one typed into the panel.
Each route says which it was, because "AlphaFold model of this protein" is a claim
about identity and the reader should be able to see what it rests on.

The sequence route matches on a CRC64 checksum of the chain against UniParc,
which is exact by construction -- a construct that has been truncated or mutated
does not match anything, and is told so rather than being quietly matched to the
nearest thing. What comes back is a list of accessions, and picking the first is
not selection: for 5-HT2A that list opens with B2RAC5, a cDNA clone with no
AlphaFold model at all, and the entry anyone means is P28223. So the candidates
are checked against UniProtKB and the reviewed (Swiss-Prot) one wins.

**Where the file is.** Constructed filenames go stale: AF-P28223-F1-model_v4.cif
was a 404 by the time this was written, because the database is on v6. The API
is asked for the URL instead of the URL being guessed.

**Getting it into the same frame.** The superposition is done here and the file
is served already transformed, so the browser loads a structure that is simply in
the right place. Kabsch, by Horn's quaternion method, which needs the largest
eigenvector of a symmetric 4x4 rather than an SVD -- this venv is Flask and
nothing else, and there is no numpy to call.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request

UNIPARC_URL = "https://rest.uniprot.org/uniparc/search?query=checksum:{checksum}&format=json&size=1"
UNIPROTKB_URL = ("https://rest.uniprot.org/uniprotkb/search?query={query}"
                 "&fields=accession,reviewed,organism_name,length&format=json&size=25")
AFDB_API = "https://alphafold.ebi.ac.uk/api/prediction/{accession}"
USER_AGENT = "BoltzMaker (https://boltzmaker.mdeller.com)"
TIMEOUT_SECONDS = 30
#: A single-chain AlphaFold model is a few hundred KB; the largest into a few MB.
MAX_BYTES = 30 * 1024 * 1024


class AlphaFoldError(RuntimeError):
    """Anything that stops a model being shown, in words for the person asking."""


# --- checksum -----------------------------------------------------------------

_CRC64_POLY = 0xD800000000000000
_CRC64_TABLE = []
for _i in range(256):
    _crc = _i
    for _ in range(8):
        _crc = (_crc >> 1) ^ _CRC64_POLY if _crc & 1 else _crc >> 1
    _CRC64_TABLE.append(_crc)


def crc64(sequence: str) -> str:
    """UniProt's own CRC64-ISO of a sequence, which is how UniParc indexes it."""
    crc = 0
    for char in sequence.encode():
        crc = _CRC64_TABLE[(crc ^ char) & 0xFF] ^ (crc >> 8)
    return "%016X" % crc


# --- resolving an accession ---------------------------------------------------

def _get_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read(MAX_BYTES).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise AlphaFoldError(f"{urllib.parse.urlsplit(url).netloc} answered {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AlphaFoldError(f"{urllib.parse.urlsplit(url).netloc} could not be reached.") from exc


def accession_from_sequence(sequence: str) -> str:
    """The reviewed UniProt accession whose sequence is exactly this one."""
    data = _get_json(UNIPARC_URL.format(checksum=crc64(sequence)))
    results = data.get("results") or []
    if not results:
        raise AlphaFoldError(
            "No UniProt entry has exactly this sequence, so there is nothing to be "
            "confident is the same protein. This is normal for a construct that has "
            "been truncated or mutated -- type the accession in if you know it."
        )
    # "P28223-1" is an isoform of P28223 and "B2RAC5.1" a version of B2RAC5;
    # neither suffix is part of the accession AlphaFold is keyed on.
    candidates, seen = [], set()
    for raw in results[0].get("uniProtKBAccessions") or []:
        accession = str(raw).split(".")[0].split("-")[0]
        if accession and accession not in seen:
            seen.add(accession)
            candidates.append(accession)
    if not candidates:
        raise AlphaFoldError("UniParc knows this sequence but lists no UniProt entry for it.")

    query = urllib.parse.quote("(" + " OR ".join(f"accession:{a}" for a in candidates) + ")")
    entries = (_get_json(UNIPROTKB_URL.format(query=query)) or {}).get("results") or []
    reviewed = [e for e in entries
                if "reviewed" in str(e.get("entryType", "")).lower()
                and "unreviewed" not in str(e.get("entryType", "")).lower()]
    if reviewed:
        return reviewed[0].get("primaryAccession") or candidates[0]
    # Nothing reviewed: an unreviewed entry is still a real protein, and better
    # than refusing. The caller says which route was used, so this is visible.
    return (entries[0].get("primaryAccession") if entries else candidates[0])


UNIPROT_ENTRY_URL = ("https://rest.uniprot.org/uniprotkb/{accession}.json"
                     "?fields=accession,id,gene_primary,protein_name,sequence,organism_name")


def entry(accession: str) -> dict:
    """A UniProt entry, reduced to what the Prepare form needs.

    The gene name is the short name a chain wants -- HTR2A for P28223 -- and
    Boltz allows five characters, which most human gene symbols already fit. One
    that does not is truncated rather than rejected: a name is an identifier for
    the run, and the accession it came from is recorded beside it.
    """
    try:
        data = _get_json(UNIPROT_ENTRY_URL.format(accession=urllib.parse.quote(accession)))
    except AlphaFoldError as exc:
        # UniProt answers 400 for a well-formed accession that does not exist, so
        # the generic "the server answered 400" would be true and useless here.
        raise AlphaFoldError(f"UniProt has no entry {accession}.") from exc
    if not isinstance(data, dict) or not data.get("primaryAccession"):
        raise AlphaFoldError(f"UniProt has no entry {accession}.")
    genes = data.get("genes") or []
    gene = ""
    if genes:
        gene = ((genes[0].get("geneName") or {}).get("value") or "").strip()
    description = data.get("proteinDescription") or {}
    name = (((description.get("recommendedName") or {}).get("fullName") or {}).get("value")
            or ((description.get("submissionNames") or [{}])[0].get("fullName") or {}).get("value")
            or "")
    sequence = ((data.get("sequence") or {}).get("value") or "").strip()
    if not sequence:
        raise AlphaFoldError(f"UniProt entry {accession} carries no sequence.")
    return {
        "accession": data["primaryAccession"],
        "entry": data.get("uniProtkbId") or "",
        # Upper case and stripped of anything Boltz will not take in a chain id.
        "gene": "".join(c for c in gene.upper() if c.isalnum())[:5],
        "name": name,
        "organism": (data.get("organism") or {}).get("scientificName") or "",
        "sequence": sequence,
        "length": len(sequence),
    }


def model_url(accession: str) -> tuple[str, str]:
    """The AlphaFold model's URL and its entry id, from the database's own API."""
    data = _get_json(AFDB_API.format(accession=urllib.parse.quote(accession)))
    if not isinstance(data, list) or not data:
        raise AlphaFoldError(f"AlphaFold has no model for {accession}.")
    entry = data[0]
    url = entry.get("cifUrl")
    if not url:
        raise AlphaFoldError(f"AlphaFold lists {accession} but published no mmCIF for it.")
    return url, entry.get("entryId") or accession


def fetch_model(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        raise AlphaFoldError(f"The model could not be downloaded ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AlphaFoldError("The model could not be downloaded.") from exc
    text = body.decode("utf-8", "replace")
    # A 200 carrying an error page is not a structure, and would otherwise be
    # handed to the parser and produce an empty model with no explanation.
    if not text.lstrip().startswith("data_"):
        raise AlphaFoldError("What came back from AlphaFold was not an mmCIF file.")
    return text


# --- superposition ------------------------------------------------------------

def _jacobi_largest_eigenvector(matrix: list[list[float]], sweeps: int = 24) -> list[float]:
    """Largest eigenvector of a small symmetric matrix, by cyclic Jacobi rotation.

    Enough for the 4x4 this needs, and short enough to read. Power iteration would
    be shorter still and converges slowly when the top two eigenvalues are close,
    which is exactly the case for two structures that are nearly the same shape.
    """
    size = len(matrix)
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for _ in range(sweeps):
        off = sum(a[i][j] ** 2 for i in range(size) for j in range(size) if i != j)
        if off < 1e-18:
            break
        for p in range(size - 1):
            for q in range(p + 1, size):
                if abs(a[p][q]) < 1e-15:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(size):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(size):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(size):
                    vkp, vkq = vectors[k][p], vectors[k][q]
                    vectors[k][p] = c * vkp - s * vkq
                    vectors[k][q] = s * vkp + c * vkq
    best = max(range(size), key=lambda i: a[i][i])
    return [vectors[k][best] for k in range(size)]


def superpose(mobile: list, fixed: list) -> tuple[list, list, float]:
    """Rotation and translation putting `mobile` onto `fixed`, and the RMSD after.

    Horn's quaternion form of Kabsch: build a symmetric 4x4 from the covariance
    and take its largest eigenvector. It cannot produce a reflection, which is the
    failure mode the SVD form needs an explicit determinant check to avoid.
    """
    if len(mobile) < 3:
        raise AlphaFoldError("Fewer than three residues line up, which is not enough to superpose on.")
    n = len(mobile)
    centre_m = [sum(p[i] for p in mobile) / n for i in range(3)]
    centre_f = [sum(p[i] for p in fixed) / n for i in range(3)]
    m = [[p[i] - centre_m[i] for i in range(3)] for p in mobile]
    f = [[p[i] - centre_f[i] for i in range(3)] for p in fixed]

    sxx = sum(a[0] * b[0] for a, b in zip(m, f))
    sxy = sum(a[0] * b[1] for a, b in zip(m, f))
    sxz = sum(a[0] * b[2] for a, b in zip(m, f))
    syx = sum(a[1] * b[0] for a, b in zip(m, f))
    syy = sum(a[1] * b[1] for a, b in zip(m, f))
    syz = sum(a[1] * b[2] for a, b in zip(m, f))
    szx = sum(a[2] * b[0] for a, b in zip(m, f))
    szy = sum(a[2] * b[1] for a, b in zip(m, f))
    szz = sum(a[2] * b[2] for a, b in zip(m, f))

    n_matrix = [
        [sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
        [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
        [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
        [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
    ]
    q = _jacobi_largest_eigenvector(n_matrix)
    norm = math.sqrt(sum(v * v for v in q)) or 1.0
    w, x, y, z = [v / norm for v in q]
    rotation = [
        [w * w + x * x - y * y - z * z, 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), w * w - x * x + y * y - z * z, 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), w * w - x * x - y * y + z * z],
    ]

    total = 0.0
    for a, b in zip(m, f):
        moved = [sum(rotation[i][j] * a[j] for j in range(3)) for i in range(3)]
        total += sum((moved[i] - b[i]) ** 2 for i in range(3))
    rmsd = math.sqrt(total / n)

    # Applied as: x' = R(x - centre_m) + centre_f
    return rotation, [centre_m, centre_f], rmsd


def superpose_core(mobile: list, fixed: list, rounds: int = 6,
                   cutoff: float = 4.0, floor: int = 40) -> tuple:
    """Superpose on the part of two structures that agrees, and say how much that was.

    A whole-chain fit is a fit to whatever moves most. Two Boltz predictions of the
    SAME receptor with different ligands came out at 9.3A over all 471 CA -- not
    because the receptor differs by 9A but because its N-terminus and ICL3 are long,
    disordered and placed differently each time, and a least-squares fit spends its
    accuracy on them. The transmembrane bundle, which is the thing anyone is looking
    at, then does not overlay at all.

    The refinement is on a percentile, not on the cutoff alone. Dropping only the
    pairs beyond 4A cannot start when the first fit is bad enough that nothing is
    within 4A of anything -- three of the fifteen targets in the example campaign
    sat at 19A over every residue, having rejected all of them and kept the fit
    that produced that. Halving the set each round always makes progress, whatever
    the fit it starts from, and the absolute cutoff then decides when to stop.

    Returns the transform, the RMSD over the residues that survived, and which
    ones those were. The count is not decoration -- 1A over 40 residues and 1A
    over 400 are different claims, and only the second is about the protein -- and
    the caller needs the identities too, so it can draw the part that was actually
    fitted rather than the part that was not.
    """
    keep = list(range(len(mobile)))
    rotation, centres, rmsd = superpose(mobile, fixed)
    for _ in range(rounds - 1):
        centre_m, centre_f = centres
        deviations = []
        for index in keep:
            point = [mobile[index][i] - centre_m[i] for i in range(3)]
            moved = [sum(rotation[i][j] * point[j] for j in range(3)) + centre_f[i]
                     for i in range(3)]
            deviations.append((math.dist(moved, fixed[index]), index))
        deviations.sort()
        # The threshold is whichever is LARGER: the absolute cutoff, or the median
        # deviation. Halving unconditionally trims a good fit down to a quarter of
        # the chain and then reports a fine RMSD over a fragment; thresholding on
        # the cutoff alone cannot start from a bad one. Taking the larger halves
        # while the fit is poor and then keeps everything that genuinely agrees.
        median = deviations[len(deviations) // 2][0]
        threshold = max(cutoff, median)
        survivors = [index for distance, index in deviations if distance <= threshold]
        if len(survivors) < floor:
            survivors = [index for _, index in deviations[:floor]]
        if len(survivors) >= len(keep) or len(survivors) < 3:
            break
        keep = survivors
        rotation, centres, rmsd = superpose([mobile[i] for i in keep],
                                            [fixed[i] for i in keep])
    return rotation, centres, rmsd, keep


def apply_transform(cif_text: str, rotation: list, centres: list) -> str:
    """Rewrite an mmCIF's coordinates in place, leaving everything else alone.

    Only the three coordinate columns change, so every other category the file
    carries -- and the pLDDT in the B-factor column, which is the useful thing
    about an AlphaFold model -- survives untouched.
    """
    from . import sequences

    lines = cif_text.splitlines()
    columns, start = sequences._atom_site_columns(lines)
    needed = ("Cartn_x", "Cartn_y", "Cartn_z")
    if not all(name in columns for name in needed):
        raise AlphaFoldError("The AlphaFold file has no coordinates this could move.")
    cx, cy, cz = (columns[name] for name in needed)
    width = len(columns)
    centre_m, centre_f = centres

    out = lines[:start]
    for line in lines[start:]:
        if not line.startswith(("ATOM ", "HETATM ")):
            out.append(line)
            continue
        fields = line.split()
        if len(fields) < width:
            out.append(line)
            continue
        try:
            point = [float(fields[cx]) - centre_m[0],
                     float(fields[cy]) - centre_m[1],
                     float(fields[cz]) - centre_m[2]]
        except ValueError:
            out.append(line)
            continue
        moved = [sum(rotation[i][j] * point[j] for j in range(3)) + centre_f[i] for i in range(3)]
        fields[cx], fields[cy], fields[cz] = (f"{value:.3f}" for value in moved)
        out.append(" ".join(fields))
    return "\n".join(out) + "\n"


def transform_subset(cif_text: str, rotation: list, centres: list, keep) -> str:
    """The same rewrite as apply_transform, over a chosen subset of the atoms.

    Used to cut a whole complex down to the few hundred atoms a panel actually
    draws -- one chain's CA, or one ligand -- so a page showing fifteen targets
    at once fetches a few hundred KB rather than fifteen megabytes.

    `keep` is called with the row's split fields and the column index map.
    """
    from . import sequences

    lines = cif_text.splitlines()
    columns, start = sequences._atom_site_columns(lines)
    needed = ("Cartn_x", "Cartn_y", "Cartn_z")
    if not all(name in columns for name in needed):
        raise AlphaFoldError("This structure has no coordinates.")
    cx, cy, cz = (columns[name] for name in needed)
    width = len(columns)
    centre_m, centre_f = centres

    out = lines[:start]
    for line in lines[start:]:
        if not line.startswith(("ATOM ", "HETATM ")):
            # The atom loop has ended; everything after it belongs to other
            # categories and would be meaningless without the atoms it describes.
            break
        fields = line.split()
        if len(fields) < width or not keep(fields, columns):
            continue
        try:
            point = [float(fields[cx]) - centre_m[0],
                     float(fields[cy]) - centre_m[1],
                     float(fields[cz]) - centre_m[2]]
        except ValueError:
            continue
        moved = [sum(rotation[i][j] * point[j] for j in range(3)) + centre_f[i] for i in range(3)]
        fields[cx], fields[cy], fields[cz] = (f"{value:.3f}" for value in moved)
        out.append(" ".join(fields))
    return "\n".join(out) + "\n"


def matched_atoms(model_chain: dict, target_chain: dict) -> tuple[list, list]:
    """CA pairs the two chains agree on, by residue number AND residue type.

    Number alone is enough when the sequences are identical, and quietly wrong
    when they are not -- a construct numbered from its own start would pair every
    residue with the wrong one and still superpose, on nonsense.
    """
    by_number = {}
    for number, restype, point in zip(model_chain["numbers"], model_chain["restypes"],
                                      model_chain["ca"]):
        by_number[number] = (restype, point)
    mobile, fixed = [], []
    for number, restype, point in zip(target_chain["numbers"], target_chain["restypes"],
                                      target_chain["ca"]):
        found = by_number.get(number)
        if found and found[0] == restype:
            mobile.append(found[1])
            fixed.append(point)
    return mobile, fixed
