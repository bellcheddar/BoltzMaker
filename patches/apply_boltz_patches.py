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
import ast
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


# How many times the 99.9th-percentile per-atom gradient an atom may be pushed
# before the push is treated as a singularity rather than a force. Measured live on
# a healthy step: median 1.0e-2, largest legitimate force 2.45. The failure being
# caught is ~1e12. With the quantile as the reference, 100x sits roughly two orders
# above anything real and ten below the divergence, so a healthy trajectory is
# untouched and the singularity is unarguable.
_BM_GRADIENT_CLAMP = 100.0

# The furthest one guidance step may move one atom, in angstroms. Guidance nudges a
# structure toward physical plausibility; it does not relocate atoms.
#
# Tuned on measurements, not taste. Unclamped, orforglipron's methyl C96 ended 2147A
# from the molecule. Clamping the gradient alone brought that to 48.9A. Adding this
# cap at 0.5A brought it to 2.07A -- a real bond, stretched 37% past the 1.51A the
# same atom has in a clean structure, and still long enough that a viewer inferring
# bonds by distance draws nothing there. 0.1A is a tenth of a carbon-carbon bond per
# descent step and, with 20 of those per diffusion step, still lets an atom move 2A in
# a step that genuinely calls for it.
_BM_MAX_STEP_A = 0.1

_BM_SCALE = {"n": 0}


def _bm_note_scale(busy, cap, norms, step_idx):
    # Called from the guidance block on every step, so it must not read a device
    # value every time: each read is a pipeline sync. It reports every 500th call.
    # The numbers are the evidence for where the cap belongs -- max/busy on a
    # healthy step is single digits, and the divergence this catches is twelve
    # orders of magnitude beyond it.
    # A comment and not a docstring on purpose: this is injected from inside a
    # triple-quoted string, which a nested triple quote would close.
    _BM_SCALE["n"] += 1
    if _BM_SCALE["n"] % 500 == 1:
        # The REAL cap, passed in. An earlier version recomputed it here as
        # busy * factor, which is the pre-anchoring formula -- so once the cap was
        # anchored to the quietest scale, the line printed a cap the code was not
        # using and called a clamped step "no clamp needed". Report the number that
        # was actually applied, never a reconstruction of it.
        b, c, m = float(busy), float(cap), float(norms.max())
        print(f"| STEERING_SCALE step {step_idx}: busy {b:.3e}, max {m:.3e}, "
              f"cap {c:.3e} -- " + ("CLAMPING" if m > c else "no clamp needed"),
              flush=True)


def _bm_note_clamp(n, worst, cap, busy, step_idx):
    _BM_CLAMP["count"] += 1
    _BM_CLAMP["worst"] = max(_BM_CLAMP["worst"], worst)
    # First and then sparsely, with the true magnitudes rather than a bare
    # "clamped": those numbers are the evidence for whether the threshold is in the
    # right place, and the first version of this clamp was wrong precisely because
    # it was set without them.
    if _BM_CLAMP["count"] == 1 or _BM_CLAMP["count"] % 25 == 0:
        print(f"| STEERING_CLAMP {n} atom(s) at step {step_idx}: worst {worst:.3e} "
              f"vs cap {cap:.3e} (p99.9 {busy:.3e}, {worst / max(cap, 1e-12):.1f}x over) "
              f"-- rescaled, direction kept; {_BM_CLAMP['count']} clamp(s) so far",
              flush=True)


import boltz.model.layers.initialize as init""",
    ),
    dict(
        # NOT USED BY DEFAULT, and the measurement is why. `any` is semantically what
        # "be somewhere on this protein" means, but boltz sums a penalty over every
        # contact, so unioning them into a soft-min returns ONE contact's worth of
        # gradient. Measured on a live run: max gradient 0.18-1.07, and a ligand fifty
        # angstroms away on a G protein did not move at all. BoltzMaker uses a sparse
        # sweep with boltz's native summing instead. Kept because the patch is correct
        # and a future caller may want the semantics where the force is already enough.
        name="pocket constraint: accept `any`, satisfied by the nearest contact",
        relpath="boltz/data/parse/schema.py",
        marker="# BOLTZMAKER-PATCH: pocket-any-parse",
        old="""            force = constraint["pocket"].get("force", False)
            pocket_constraints.append((binder, contacts, max_distance, force))""",
        new="""            force = constraint["pocket"].get("force", False)
            # BOLTZMAKER-PATCH: pocket-any-parse -- `any: true` means the constraint is
            # satisfied by the NEAREST listed contact rather than by all of them at
            # once. Boltz's own semantics sum a penalty over every contact, which is
            # right for a handful of residues lining one site and unsatisfiable for a
            # whole chain. Carrying the flag through lets a target say "be somewhere on
            # this protein" -- the baseline a campaign wants when the alternative is a
            # ligand docking onto a co-folded G protein instead of the receptor.
            any_contact = constraint["pocket"].get("any", False)
            pocket_constraints.append(
                (binder, contacts, max_distance, force, any_contact))""",
    ),
    dict(
        name="pocket constraint: union the contacts when `any` is set",
        relpath="boltz/data/feature/featurizerv2.py",
        marker="# BOLTZMAKER-PATCH: pocket-any-union",
        old="""    for binder, contacts, max_distance, force in inference_pocket_constraints:
        if not force:
            continue

        binder_chain = data.structure.chains[binder]""",
        new="""    # BOLTZMAKER-PATCH: pocket-any-union -- the tuple gained a fifth element; older
    # four-element ones keep Boltz's behaviour exactly.
    for _constraint in inference_pocket_constraints:
        binder, contacts, max_distance, force = _constraint[:4]
        any_contact = _constraint[4] if len(_constraint) > 4 else False
        if not force:
            continue

        # One union group for the whole constraint, so the soft-min runs across every
        # contact and the nearest one satisfies it. Boltz gives each contact its own
        # group and sums, which requires proximity to all of them simultaneously.
        _shared_union = union_idx if any_contact else None

        binder_chain = data.structure.chains[binder]""",
    ),
    dict(
        name="pocket constraint: one union index per `any` constraint",
        relpath="boltz/data/feature/featurizerv2.py",
        marker="# BOLTZMAKER-PATCH: pocket-any-index",
        old="""                pair_index.append(atom_idx_pairs)
                union_index.append(torch.full((atom_idx_pairs.shape[1],), union_idx))
                negation_mask.append(
                    torch.ones((atom_idx_pairs.shape[1],), dtype=torch.bool)
                )
                thresholds.append(torch.full((atom_idx_pairs.shape[1],), max_distance))
                union_idx += 1""",
        new="""                pair_index.append(atom_idx_pairs)
                # BOLTZMAKER-PATCH: pocket-any-index
                union_index.append(torch.full(
                    (atom_idx_pairs.shape[1],),
                    _shared_union if _shared_union is not None else union_idx))
                negation_mask.append(
                    torch.ones((atom_idx_pairs.shape[1],), dtype=torch.bool)
                )
                thresholds.append(torch.full((atom_idx_pairs.shape[1],), max_distance))
                if _shared_union is None:
                    union_idx += 1
        if _shared_union is not None:
            union_idx += 1""",
    ),
    dict(
        name="steering: resample on the CPU, off the MPS random-number kernel",
        relpath="boltz/model/modules/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: multinomial-on-cpu",
        old="""                    resample_indices = (
                        torch.multinomial(
                            resample_weights,
                            resample_weights.shape[1]
                            if step_idx < num_sampling_steps - 1
                            else 1,
                            replacement=True,
                        )""",
        new="""                    # BOLTZMAKER-PATCH: multinomial-on-cpu -- torch.multinomial goes
                    # through uniform_(), and on Metal that lands in uniform_mps_ ->
                    # MPSGraph::encodeToCommandBuffer -> MLIR kernel compilation. Sampled
                    # live on a wedged run, the main thread sat there for tens of minutes
                    # with the log frozen and the GPU at 1-4%, which reads exactly like a
                    # hang; it was killed as one four times. This call is the ONLY random
                    # draw on the steering path, which is why --no-potentials runs never
                    # showed it.
                    #
                    # resample_weights is (batch, num_particles) -- three columns -- so
                    # drawing on the CPU costs microseconds and a copy of a handful of
                    # integers, against a Metal kernel compile per new shape. The draw is
                    # from the same distribution; only the generator differs, and the
                    # weights are computed on device exactly as before.
                    resample_indices = (
                        torch.multinomial(
                            resample_weights.float().cpu(),
                            resample_weights.shape[1]
                            if step_idx < num_sampling_steps - 1
                            else 1,
                            replacement=True,
                        ).to(resample_weights.device)""",
    ),
    dict(
        name="steering: keep an exploding guidance gradient out of the coordinates",
        relpath="boltz/model/modules/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: guidance-gradient-guard",
        old="""                        guidance_update -= energy_gradient
                    atom_coords_denoised += guidance_update""",
        new="""                        # BOLTZMAKER-PATCH: guidance-gradient-guard -- this is where the
                        # NaN actually comes from. compute_gradient of a repulsive
                        # potential blows up as two atoms approach, and num_gd_steps (20)
                        # descent iterations compound it, so guidance_update goes
                        # non-finite and the line below writes it into EVERY atom. That
                        # matches what was measured: pred_coords 91584/91584 non-finite,
                        # deterministic across 20 unseeded attempts, cured only by
                        # --no-potentials, and untouched by guards on log_G or the
                        # resampling weights, which sit in a different block entirely.
                        #
                        # A non-finite gradient means "no usable direction here", so it
                        # contributes nothing rather than infinity. Only ever fires on
                        # values that are already broken, so a clean trajectory is
                        # bit-identical.
                        if not torch.isfinite(energy_gradient).all():
                            _bm_note("energy_gradient",
                                     int((~torch.isfinite(energy_gradient)).sum()), step_idx)
                            energy_gradient = torch.nan_to_num(
                                energy_gradient, nan=0.0, posinf=0.0, neginf=0.0)
                        # Sanitising non-finite values is not enough on its own, and the
                        # GLP1R+orforglipron targets are why. Only 144 entries went
                        # non-finite there and were zeroed; their finite-but-enormous
                        # neighbours passed straight through and were applied, 20 descent
                        # steps per diffusion step for the last 80 steps, until four atoms
                        # of a symmetric dimethylphenyl ring sat 49, 58, 737 and 2147A from
                        # the molecule. Same four atoms, same distances, three independent
                        # runs. The structure still scored 0.80 confidence and led the
                        # binder ranking, because nothing downstream looks at geometry.
                        #
                        # So bound the step as well. The threshold is taken from the
                        # gradient's own distribution rather than being a constant: the
                        # scale of a legitimate gradient depends on the system, the step
                        # and the potential, and a number tuned on one campaign would be
                        # wrong for the next. A per-atom displacement that is orders of
                        # magnitude larger than the median for that same step is not a
                        # force, it is a singularity, and rescaling preserves its
                        # direction while refusing its magnitude.
                        # Bound the step as well as sanitising it. Only 144 entries
                        # went non-finite on GLP1R+orforglipron and were zeroed; their
                        # finite-but-enormous neighbours were applied, 20 descent steps
                        # per diffusion step, until four atoms sat 49, 58, 737 and 2147A
                        # from the molecule -- the same four, three independent runs.
                        #
                        # Scaled against a HIGH QUANTILE, not the median: almost every
                        # atom feels no guidance force, so the median is ~0 and a
                        # multiple of it is still ~0. Measured live, a median-based cap
                        # sat at 1.0 while the largest legitimate force that same step
                        # was 2.45, and it clamped a healthy gradient at step 11.
                        #
                        # Everything here stays on the device. No boolean mask (its
                        # output shape is data-dependent, which syncs), no .item(), no
                        # branch on the data: the clamp is applied unconditionally and
                        # is a no-op scale of 1.0 wherever nothing exceeds the cap. An
                        # earlier version read four host values per guidance step --
                        # about 4000 per target -- and the run crawled so badly it was
                        # indistinguishable from a hang, and was twice killed as one.
                        # topk, not torch.quantile. Both are MPS-native in isolation,
                        # but the runs that never reached diffusion step 1 were exactly
                        # the ones carrying quantile here, while the same clamp built on
                        # a cheaper reduction reached step 11 and the unclamped build ran
                        # all 26 targets. quantile sorts the whole tensor; topk of the
                        # top 0.1% touches thirty values and is the reduction actually
                        # wanted -- the boundary of the busy atoms.
                        _norms = energy_gradient.norm(dim=-1, keepdim=True)
                        _flat = _norms.flatten().float()
                        _k = max(1, int(_flat.numel() * 0.001))
                        _busy = torch.topk(_flat, _k).values.min()
                        # Anchored to the QUIETEST scale seen in this trajectory, not to
                        # this step's. A threshold taken from the current step is blind
                        # to a divergence that inflates the whole distribution, and this
                        # one does: measured live, the busy scale sat at 0.068-0.076 for
                        # a hundred steps, then at step 125 went to 0.363 while the max
                        # went to 34 -- so a cap of 100x the current scale rose to 36 and
                        # the runaway passed under it by 6%. Against the running minimum
                        # the same step is capped at ~6.8 and clamped, which is the whole
                        # point. Reset per trajectory at step 0, since this module-level
                        # state outlives a single target.
                        if step_idx == 0 or _BM_SCALE.get("ref") is None:
                            _BM_SCALE["ref"] = _busy.detach()
                        else:
                            _BM_SCALE["ref"] = torch.minimum(_BM_SCALE["ref"], _busy.detach())
                        _cap = torch.clamp(_BM_SCALE["ref"], min=1e-12) * _BM_GRADIENT_CLAMP
                        energy_gradient = energy_gradient * torch.clamp(
                            _cap / _norms.clamp(min=1e-12), max=1.0)
                        _bm_note_scale(_busy, _cap, _norms, step_idx)
                        guidance_update -= energy_gradient
                    if not torch.isfinite(guidance_update).all():
                        _bm_note("guidance_update",
                                 int((~torch.isfinite(guidance_update)).sum()), step_idx)
                        guidance_update = torch.nan_to_num(
                            guidance_update, nan=0.0, posinf=0.0, neginf=0.0)
                    # Bound the DISPLACEMENT, which is the quantity that actually goes
                    # wrong. Clamping the gradient alone took the failure from a 2154A
                    # span to 48.9A -- better by a factor of forty, still not a molecule,
                    # because the atoms whose gradient was non-finite are zeroed and then
                    # have no restoring force at all, so they drift freely for the last
                    # eighty steps. Guidance is a nudge: a per-atom step beyond
                    # _BM_MAX_STEP_A angstroms is not a nudge, whatever produced it.
                    # Rescaled rather than zeroed, so the direction still counts.
                    _disp = guidance_update.norm(dim=-1, keepdim=True)
                    guidance_update = guidance_update * torch.clamp(
                        _BM_MAX_STEP_A / _disp.clamp(min=1e-12), max=1.0)
                    atom_coords_denoised += guidance_update""",
    ),
    dict(
        name="steering: last line of defence on the denoised coordinates",
        relpath="boltz/model/modules/diffusionv2.py",
        marker="# BOLTZMAKER-PATCH: denoised-coords-guard",
        old="""            if self.alignment_reverse_diff:""",
        new="""            # BOLTZMAKER-PATCH: denoised-coords-guard -- whatever produced them, once
            # the denoised coordinates are non-finite every downstream step is garbage
            # and the target is lost. Reverting the affected atoms to the pre-guidance
            # noisy coordinates keeps the trajectory alive with a real position rather
            # than an undefined one, and says how many atoms it had to rescue.
            if not torch.isfinite(atom_coords_denoised).all():
                _bad = ~torch.isfinite(atom_coords_denoised)
                _bm_note("atom_coords_denoised", int(_bad.sum()), step_idx)
                atom_coords_denoised = torch.where(
                    _bad, atom_coords_noisy, atom_coords_denoised)
            if self.alignment_reverse_diff:""",
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
        name="steering: flat-bottom shape reporter",
        relpath="boltz/model/potentials/potentials.py",
        marker="# BOLTZMAKER-PATCH: flatbottom-report",
        old="""class FlatBottomPotential(Potential):""",
        new="""# BOLTZMAKER-PATCH: flatbottom-report -- the masked assignments in
# FlatBottomPotential can raise "shape mismatch: value tensor of shape [N] cannot be
# broadcast to indexing result of shape [M]", which names neither the operand that is
# mis-sized nor the potential it came from, and kills the whole predict process with
# every target queued behind it. This prints every operand's shape and then re-raises
# the original exception unchanged -- diagnosis only, it can never alter a result.
# Written after eight such crashes across a 58-target campaign produced nothing to act
# on; one run with this in place identified the cause immediately.
def _bm_safe(fn):
    try:
        return fn()
    except Exception as e:
        return f"<{type(e).__name__}>"


def _bm_flat_report(which, value, k, lower_bounds, upper_bounds, neg_mask, pos_mask):
    def s(t):
        try:
            return tuple(t.shape)
        except AttributeError:
            return repr(t)
    print(
        f"| FLATBOTTOM_SHAPE_MISMATCH in {which}: "
        f"value={s(value)} k={s(k)} lower={s(lower_bounds)} upper={s(upper_bounds)} "
        f"neg_mask={s(neg_mask)} pos_mask={s(pos_mask)} "
        f"neg_true={int(neg_mask.sum())} pos_true={int(pos_mask.sum())} "
        f"k*(lower-value)={_bm_safe(lambda: tuple((k * (lower_bounds - value)).shape))} "
        f"k.expand_as(mask)={_bm_safe(lambda: tuple(k.expand_as(neg_mask).shape))}",
        flush=True,
    )


class FlatBottomPotential(Potential):""",
    ),
    dict(
        name="steering: elementwise select dodges the MPS masked-select miscount",
        relpath="boltz/model/potentials/potentials.py",
        marker="# BOLTZMAKER-PATCH: flatbottom-where",
        old="""        energy = torch.zeros_like(value)
        energy[neg_overflow_mask] = (k * (lower_bounds - value))[neg_overflow_mask]
        energy[pos_overflow_mask] = (k * (value - upper_bounds))[pos_overflow_mask]
        if not compute_derivative:
            return energy

        dEnergy = torch.zeros_like(value)
        dEnergy[neg_overflow_mask] = (
            -1 * k.expand_as(neg_overflow_mask)[neg_overflow_mask]
        )
        dEnergy[pos_overflow_mask] = (
            1 * k.expand_as(pos_overflow_mask)[pos_overflow_mask]
        )""",
        new="""        # BOLTZMAKER-PATCH: flatbottom-where -- `t[mask] = other[mask]` compacts twice
        # through MPS's masked-select kernel, and on a large tensor with a sparse mask
        # the two compactions disagree. Measured live at value=(3, 35830451) with the
        # SAME mask object: energy[mask] gave 73 elements (== mask.sum()) while
        # (k*(lower-value))[mask] gave 82, so the assignment raised "value tensor of
        # shape [82] cannot be broadcast to indexing result of shape [73]" and killed
        # the predict process. Across eight crashes the discrepancy was +1, -2, -3, -4,
        # -6, -2, -71 and -623 -- mixed sign and magnitude, i.e. a racy compaction, not
        # an off-by-one. torch.where is elementwise: no compaction, no count to
        # disagree about, and arithmetically the identical function. Verified identical
        # to the masked form on 600 randomised CPU cases (rank-1 and rank-2, +/-inf and
        # None bounds, scalar and vector k, both branches, the negation_mask path), on
        # the production geometry (3, 200000), and exact against CPU when run on MPS.
        energy = torch.zeros_like(value)
        try:
            energy = torch.where(neg_overflow_mask, k * (lower_bounds - value), energy)
            energy = torch.where(pos_overflow_mask, k * (value - upper_bounds), energy)
        except Exception:
            _bm_flat_report("energy", value, k, lower_bounds, upper_bounds,
                            neg_overflow_mask, pos_overflow_mask)
            raise
        if not compute_derivative:
            return energy

        dEnergy = torch.zeros_like(value)
        try:
            dEnergy = torch.where(
                neg_overflow_mask, -1 * k.expand_as(neg_overflow_mask), dEnergy
            )
            dEnergy = torch.where(
                pos_overflow_mask, 1 * k.expand_as(pos_overflow_mask), dEnergy
            )
        except Exception:
            _bm_flat_report("dEnergy", value, k, lower_bounds, upper_bounds,
                            neg_overflow_mask, pos_overflow_mask)
            raise""",
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
        name="release the allocator cache between targets",
        relpath="boltz/model/models/boltz2.py",
        marker="# BOLTZMAKER-PATCH: mps-flush-between-targets",
        old="""            except Exception:
                pass
            pred_dict["coords"] = out["sample_atom_coords"]""",
        new="""            except Exception:
                pass
            # BOLTZMAKER-PATCH: mps-flush-between-targets -- empty_cache is otherwise
            # only called from the out-of-memory handlers, so after a target finishes the
            # allocator keeps every cached block and the next target starts against them.
            # Measured on a live campaign: 47GB allocated from the driver with 5.5GB
            # actually live, i.e. ~41GB of cache held while the ceiling is 55.7GB. That
            # gap is most of the reason a slightly larger target has nowhere to go.
            #
            # Releasing it costs only the re-allocation the next target would have done
            # anyway, which is nothing against ~44 minutes of sampling, and it changes no
            # numbers -- this is memory management, not arithmetic. The reclaimed figure
            # is printed so the effect is visible rather than assumed.
            try:
                if torch.backends.mps.is_available():
                    _before = torch.mps.driver_allocated_memory()
                    torch.mps.empty_cache()
                    _after = torch.mps.driver_allocated_memory()
                    print(f"| MPS_FLUSH released={(_before - _after)/1e9:.2f}GB "
                          f"held_after={_after/1e9:.2f}GB", flush=True)
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


def verify_injected_symbols(site: Path) -> list:
    """Every helper these patches call must exist, in that file, with that arity.

    Twice now a patch has installed cleanly, parsed cleanly, and then failed at
    runtime deep into a campaign: once with `_bm_note` anchored into a file where it
    was never defined, and once with a reporter whose signature had moved on from its
    call site, costing 34 minutes of a run that had otherwise worked. Neither is
    visible to "does it compile" -- a call is only checked when it executes, and these
    execute inside a diffusion loop that takes half an hour to reach.
    """
    problems = []
    for relpath in sorted({p["relpath"] for p in PATCHES}):
        path = site / relpath
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError as exc:
            problems.append(f"{relpath}: injected code does not parse ({exc})")
            continue
        defined = {n.name: len(n.args.args) for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            name = node.func.id
            if not name.startswith("_bm_"):
                continue
            if name not in defined:
                problems.append(f"{relpath}:{node.lineno} calls {name}(), which is not "
                                f"defined in this file")
            elif defined[name] != len(node.args):
                problems.append(f"{relpath}:{node.lineno} calls {name}() with "
                                f"{len(node.args)} args, defined with {defined[name]}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report status without editing")
    ap.add_argument("--reapply", action="store_true",
                    help="restore every .orig first, so a REVISED patch body actually lands. "
                         "Application is detected by marker and not by content, so editing a "
                         "patch here and re-running without this prints 'already applied' and "
                         "changes nothing.")
    ap.add_argument("--site-packages", type=Path, default=None)
    args = ap.parse_args()

    sp = args.site_packages or find_site_packages()
    applied = missing = 0

    if args.reapply and not args.check:
        # Every patched file back to stock, so the loop below re-applies all of them
        # from the current definitions. Restoring per-file rather than per-patch
        # because several patches can share a file, and reverting one of them would
        # leave the others half-applied.
        restored = 0
        for relpath in sorted({q["relpath"] for q in PATCHES}):
            target = sp / relpath
            backup = target.with_suffix(target.suffix + ".orig")
            if backup.is_file():
                shutil.copy2(backup, target)
                restored += 1
        print(f"  restored {restored} file(s) from .orig before re-applying")

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

    broken = verify_injected_symbols(sp)
    for line in broken:
        print(f"  BROKEN PATCH  {line}")
        missing += 1

    print(f"\n{applied} applied, {missing} outstanding  [{sp}]")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
