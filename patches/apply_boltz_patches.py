#!/usr/bin/env python3
"""Apply BoltzMaker's local fixes to an installed `boltz` package.

Two defects in boltz 2.x cost a GLP1R_GIPR campaign 14.5 hours and 20 invocations
for zero structures. Both are patched here. The script is idempotent, keeps a .orig
backup of every file it edits, and must be re-run after any `boltz` reinstall or
upgrade -- `--check` reports whether the patches are present (BoltzMaker's preflight
calls it).

    python3 apply_boltz_patches.py [--check] [--site-packages PATH]

PATCH 1 -- contain numerical failures to one target
    boltz2.py predict_step() catches RuntimeError, skips the batch on out-of-memory,
    and re-raises everything else. torch.linalg.LinAlgError subclasses RuntimeError,
    so a NaN-driven SVD failure in one target aborts the entire `boltz predict`
    process. Any target queued behind it is never attempted. This patch treats a
    LinAlgError exactly like an OOM: report it, skip that target, keep going.

PATCH 2 -- make the full-precision alignment guard work off CUDA
    diffusionv2.py wraps weighted_rigid_align in `torch.autocast("cuda", enabled=False)`
    to force the Kabsch alignment into fp32. On MPS that guard is inert -- autocast is
    active for device_type "mps", so despite the explicit .float() casts the covariance
    einsum still runs under bfloat16. This patch makes the guard follow the tensors'
    actual device.

PATCH 3 -- say what actually went wrong
    torch reports a NaN covariance matrix as "failed to converge because the input
    matrix is ill-conditioned or has too many repeated singular values", which sends
    you looking at conditioning. Measured on this machine: of every degenerate 3x3
    (rank-1, zeros, repeated singular values, 1e-20, 1e20) plus 2000 random matrices,
    the *only* input that raises it is one containing NaN. This patch checks for
    non-finite values first and reports which tensor carried them, so the next
    occurrence names its own cause.
"""

import argparse
import shutil
import sys
from pathlib import Path

PATCHES = [
    dict(
        name="predict_step contains LinAlgError",
        relpath="boltz/model/models/boltz2.py",
        marker="# BOLTZMAKER-PATCH: contain-linalg",
        old="""        except RuntimeError as e:  # catch out of memory exceptions
            if "out of memory" in str(e):
                print("| WARNING: ran out of memory, skipping batch")
                torch.cuda.empty_cache()
                gc.collect()
                return {"exception": True}
            else:
                raise e""",
        new="""        except RuntimeError as e:  # catch out of memory exceptions
            if "out of memory" in str(e):
                print("| WARNING: ran out of memory, skipping batch")
                torch.cuda.empty_cache()
                gc.collect()
                return {"exception": True}
            # BOLTZMAKER-PATCH: contain-linalg -- LinAlgError subclasses RuntimeError,
            # so without this one target's numerical failure aborts the whole predict
            # process and every target queued behind it is silently never attempted.
            if isinstance(e, torch.linalg.LinAlgError):
                print(f"| WARNING: numerical failure, skipping batch: {e}")
                gc.collect()
                return {"exception": True}
            else:
                raise e""",
    ),
    dict(
        name="fp32 alignment guard follows the device",
        relpath="boltz/model/modules/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: autocast-device",
        old="""            if self.alignment_reverse_diff:
                with torch.autocast("cuda", enabled=False):""",
        new="""            if self.alignment_reverse_diff:
                # BOLTZMAKER-PATCH: autocast-device -- hardcoding "cuda" makes this
                # guard inert on MPS, so the covariance einsum below runs in bfloat16
                # despite the .float() casts. Follow the tensors' actual device.
                with torch.autocast(atom_coords_noisy.device.type, enabled=False):""",
    ),
    dict(
        name="report non-finite input instead of blaming conditioning",
        relpath="boltz/model/loss/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: nan-diagnostic",
        old="""    U, S, V = torch.linalg.svd(
        cov_matrix_32, driver="gesvd" if cov_matrix_32.is_cuda else None
    )""",
        new="""    # BOLTZMAKER-PATCH: nan-diagnostic -- torch reports a NaN covariance matrix as
    # "ill-conditioned or too many repeated singular values", which points the reader
    # at conditioning. Measured: every degenerate 3x3 (rank-1, zeros, repeated
    # singular values, 1e-20, 1e20) and 2000 random matrices pass; only NaN raises.
    # Name the tensor that actually carried the NaN so the next one is diagnosable.
    if not torch.isfinite(cov_matrix_32).all():
        def _nf(t):
            return int((~torch.isfinite(t)).sum().item()), int(t.numel())
        raise torch.linalg.LinAlgError(
            "weighted_rigid_align: covariance matrix is not finite -- the diffusion "
            "coordinates had already diverged before alignment. Non-finite/total: "
            f"true_coords {_nf(true_coords)}, pred_coords {_nf(pred_coords)}, "
            f"weights {_nf(weights)}, cov_matrix {_nf(cov_matrix_32)}; "
            f"weight-sum min {float(weights.sum(dim=-2).min()):.6g}, dtype {original_dtype}."
        )

    U, S, V = torch.linalg.svd(
        cov_matrix_32, driver="gesvd" if cov_matrix_32.is_cuda else None
    )""",
    ),
    dict(
        name="affinity phase skips targets with no pre_affinity file",
        relpath="boltz/main.py",
        marker="# BOLTZMAKER-PATCH: skip-missing-pre-affinity",
        old="""    # Get all affinity targets
    existing = {
        r.id
        for r in manifest.records
        if r.affinity
        and (outdir / "predictions" / r.id / f"affinity_{r.id}.json").exists()
    }""",
        new="""    # Get all affinity targets
    existing = {
        r.id
        for r in manifest.records
        if r.affinity
        and (outdir / "predictions" / r.id / f"affinity_{r.id}.json").exists()
    }

    # BOLTZMAKER-PATCH: skip-missing-pre-affinity -- this filter drops targets that
    # already have an affinity result but never checks for the pre_affinity_*.npz the
    # phase is about to load. Any target whose structure prediction was skipped (OOM,
    # or a numerical failure) has no such file, so the shared affinity phase dies with
    # FileNotFoundError partway through -- taking down every already-successful target
    # queued behind it. Observed on GLP1R_GIPR: affinity was asked for 24 inputs when
    # only 13 had the file, and it crashed at 8/24 after 13 minutes of real work.
    missing_pre = {
        r.id
        for r in manifest.records
        if r.affinity
        and r.id not in existing
        and not (outdir / "predictions" / r.id / f"pre_affinity_{r.id}.npz").exists()
    }
    if missing_pre:
        click.echo(
            f"Skipping affinity for {len(missing_pre)} target(s) whose structure "
            f"prediction did not complete: {sorted(missing_pre)}"
        )
        manifest = Manifest([r for r in manifest.records if r.id not in missing_pre])""",
    ),
    dict(
        name="OOM skip frees MPS memory, not just CUDA",
        relpath="boltz/model/models/boltz2.py",
        marker="# BOLTZMAKER-PATCH: mps-flush-loop",
        count=2,
        old="""                    torch.cuda.empty_cache()
                    gc.collect()
                    return""",
        new="""                    # BOLTZMAKER-PATCH: mps-flush-loop -- torch.cuda.empty_cache() is a
                    # silent no-op without CUDA, so on Apple silicon an OOM skip freed
                    # nothing: the allocator kept its cached blocks and the next target
                    # inherited the same pressure. One campaign OOM-skipped 11 targets in a
                    # row this way. Free the pool that is actually in use.
                    torch.cuda.empty_cache()
                    if torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                    gc.collect()
                    return""",
    ),
    dict(
        name="predict_step's OOM skip frees MPS memory too",
        relpath="boltz/model/models/boltz2.py",
        marker="# BOLTZMAKER-PATCH: mps-flush-step",
        old="""                print("| WARNING: ran out of memory, skipping batch")
                torch.cuda.empty_cache()
                gc.collect()""",
        new="""                print("| WARNING: ran out of memory, skipping batch")
                # BOLTZMAKER-PATCH: mps-flush-step -- see mps-flush-loop; without this an
                # OOM skip on Apple silicon reclaims nothing at all.
                torch.cuda.empty_cache()
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                gc.collect()""",
    ),
]


def find_site_packages() -> Path:
    for p in sys.path:
        if p and (Path(p) / "boltz").is_dir():
            return Path(p)
    raise SystemExit("could not locate an installed `boltz` on sys.path; pass --site-packages")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report status without editing")
    ap.add_argument("--site-packages", type=Path, default=None)
    args = ap.parse_args()

    sp = args.site_packages or find_site_packages()
    applied = missing = 0

    for p in PATCHES:
        path = sp / p["relpath"]
        if not path.is_file():
            print(f"  MISSING FILE  {p['name']}: {path}")
            missing += 1
            continue
        text = path.read_text()
        if p["marker"] in text:
            print(f"  already applied  {p['name']}")
            applied += 1
            continue
        if args.check:
            print(f"  NOT APPLIED  {p['name']}  ({p['relpath']})")
            missing += 1
            continue
        expected = p.get("count", 1)
        if text.count(p["old"]) != expected:
            print(f"  CANNOT APPLY  {p['name']}: anchor found {text.count(p['old'])}x, expected "
                  f"{expected} -- boltz has changed, re-derive against {p['relpath']}")
            missing += 1
            continue
        if p["old"] not in text:
            print(f"  CANNOT APPLY  {p['name']}: anchor text not found -- boltz has changed, "
                  f"re-derive the patch against {p['relpath']}")
            missing += 1
            continue
        backup = path.with_suffix(path.suffix + ".orig")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(text.replace(p["old"], p["new"], expected))
        print(f"  applied  {p['name']}  (backup {backup.name})")
        applied += 1

    print(f"\n{applied} applied, {missing} outstanding  [{sp}]")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
