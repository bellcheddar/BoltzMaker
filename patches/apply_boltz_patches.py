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
        name="steering: the diagnostic reporter itself",
        relpath="boltz/model/modules/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: nan-reporter",
        old="""import boltz.model.layers.initialize as init""",
        new="""# BOLTZMAKER-PATCH: nan-reporter -- says WHICH quantity went non-finite first and
# how often it had to be repaired. A target sanitised at 2 steps of 200 is
# essentially untouched; one sanitised at 150 had substantially synthetic steering
# and its structure should be read with that in mind. Printing the count is what
# makes that judgeable per target rather than a blanket caveat.
_BM_NAN = {"count": 0, "first": None}


def _bm_note(where, n, step_idx):
    _BM_NAN["count"] += 1
    if _BM_NAN["first"] is None:
        _BM_NAN["first"] = where
        print(f"| STEERING_NAN first non-finite in {where} at step {step_idx} "
              f"({n} values) -- sanitised, steering continues", flush=True)
    elif _BM_NAN["count"] % 25 == 0:
        print(f"| STEERING_NAN sanitised {_BM_NAN['count']} times so far "
              f"(latest {where}, step {step_idx})", flush=True)


import boltz.model.layers.initialize as init""",
    ),
    dict(
        name="steering: sanitise non-finite energies and say so",
        relpath="boltz/model/modules/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: steering-nan-guard",
        old="""                    # Compute log G values
                    if step_idx == 0:
                        log_G = -1 * energy
                    else:
                        log_G = energy_traj[:, -2] - energy_traj[:, -1]""",
        new="""                    # BOLTZMAKER-PATCH: steering-nan-guard -- log_G is a difference of
                    # consecutive energies, so a steric clash that sends one to +inf makes
                    # this inf - inf = NaN. That NaN reaches the softmax below, the
                    # resampling weights, and finally the coordinates, which come back
                    # entirely non-finite. It is deterministic (a clash is a property of
                    # the structure, not of the noise), which is why it survived every
                    # precision and MSA-depth change we tried, and why turning potentials
                    # off was the only thing that helped.
                    #
                    # NaN becomes 0.0 -- an undefined energy change should leave a particle
                    # neither favoured nor penalised -- and infinities become large finite
                    # values so the ordering between particles is preserved. This branch
                    # only runs when a value is ALREADY non-finite, so a trajectory that
                    # never clashes is bit-identical to an unpatched run.
                    if step_idx == 0:
                        log_G = -1 * energy
                    else:
                        log_G = energy_traj[:, -2] - energy_traj[:, -1]
                    if not torch.isfinite(log_G).all():
                        _bm_note("log_G", int((~torch.isfinite(log_G)).sum()), step_idx)
                        log_G = torch.nan_to_num(log_G, nan=0.0, posinf=1e6, neginf=-1e6)""",
    ),
    dict(
        name="steering: fall back to uniform weights rather than NaN ones",
        relpath="boltz/model/modules/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: steering-weights-guard",
        old="""                    resample_weights = F.softmax(
                        (ll_difference + steering_args["fk_lambda"] * log_G).reshape(
                            -1, steering_args["num_particles"]
                        ),
                        dim=1,
                    )""",
        new="""                    resample_weights = F.softmax(
                        (ll_difference + steering_args["fk_lambda"] * log_G).reshape(
                            -1, steering_args["num_particles"]
                        ),
                        dim=1,
                    )
                    # BOLTZMAKER-PATCH: steering-weights-guard -- second line of defence.
                    # ll_difference divides by the noise variance, which shrinks towards the
                    # end of sampling, so it can go non-finite even with the energies clean.
                    # Uniform weights mean "no particle is preferred at this step", which
                    # degrades that one step rather than destroying the target.
                    if not torch.isfinite(resample_weights).all():
                        _bm_note("resample_weights", int((~torch.isfinite(resample_weights)).sum()),
                                 step_idx)
                        resample_weights = torch.full_like(
                            resample_weights, 1.0 / resample_weights.shape[-1])""",
    ),
    dict(
        name="report peak MPS memory per target",
        relpath="boltz/model/models/boltz2.py",
        marker="# BOLTZMAKER-PATCH: mps-peak",
        old="""            pred_dict["coords"] = out["sample_atom_coords"]""",
        new="""            # BOLTZMAKER-PATCH: mps-peak -- the only way to size a run on Apple
            # silicon. RSS does not include MPS memory at all (measured: a 4GB MPS
            # allocation moved RSS by 0.01GB), so every psutil-based figure this
            # project has ever printed excludes the thing that actually causes the
            # OOMs. driver_allocated_memory is the real number and can only be read
            # from inside the process.
            try:
                if torch.backends.mps.is_available():
                    print(f"| MPS_PEAK driver={torch.mps.driver_allocated_memory()/1e9:.2f}GB "
                          f"current={torch.mps.current_allocated_memory()/1e9:.2f}GB "
                          f"recommended_max={torch.mps.recommended_max_memory()/1e9:.2f}GB",
                          flush=True)
            except Exception:
                pass
            pred_dict["coords"] = out["sample_atom_coords"]""",
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


AUTOCAST_RULES = [
    ('with torch.autocast("cuda", enabled=False):',
     'with torch.autocast("cuda", enabled=False), torch.autocast("mps", enabled=False):'),
    ('with torch.amp.autocast("cuda", enabled=False):',
     'with torch.amp.autocast("cuda", enabled=False), torch.amp.autocast("mps", enabled=False):'),
]


def apply_autocast_mps(sp: Path, check: bool) -> tuple[int, int]:
    """Make every full-precision guard in boltz work off CUDA.

    boltz wraps its numerically fragile operations -- triangular attention,
    pairformer, attention, the distogram and confidence heads, the encoders and
    the diffusion sampler itself -- in `torch.autocast("cuda", enabled=False)`,
    because those steps overflow in reduced precision. The device type is
    hardcoded, so on Apple silicon (where autocast runs with device_type "mps")
    every one of those guards is inert and the fragile operations run in bfloat16
    anyway. Measured on torch 2.10: inside an MPS bf16 autocast, a matmul under
    boltz's own guard still returns bfloat16; adding an "mps" disable returns
    float32, which is what the guard was written to guarantee.

    Nesting a second context manager rather than rewriting the device is
    deliberate: it is a mechanical, reviewable change, and it is a no-op on a
    CUDA box, so a patched checkout still behaves identically where boltz is
    normally run.
    """
    changed = files = 0
    for path in sorted(sp.glob("boltz/**/*.py")):
        if path.suffix != ".py" or path.name.endswith(".orig"):
            continue
        text = path.read_text()
        new = text
        for old, repl in AUTOCAST_RULES:
            if old in new:
                new = new.replace(old, repl)
        if new == text:
            continue
        hits = sum(text.count(old) for old, _ in AUTOCAST_RULES)
        files += 1
        changed += hits
        if not check:
            backup = path.with_suffix(path.suffix + ".orig")
            if not backup.exists():
                shutil.copy2(path, backup)
            path.write_text(new)
    return changed, files

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

    hits, files = apply_autocast_mps(sp, args.check)
    if hits:
        verb = "would fix" if args.check else "fixed"
        print(f"  {verb}  full-precision guards inert off CUDA: {hits} site(s) in {files} file(s)")
        if args.check:
            missing += 1
    else:
        print("  already applied  full-precision guards work off CUDA")
        applied += 1

    print(f"\n{applied} applied, {missing} outstanding  [{sp}]")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
