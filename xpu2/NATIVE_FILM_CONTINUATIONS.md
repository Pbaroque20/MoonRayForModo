# Native terminal-radiance suspension and film resumption

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This opt-in diagnostic moves **completed beauty contributions** across an owned
queue and resumes them through MoonRay's original film handler. It does not yet
suspend a path during shading, texture lookup, light evaluation or traversal.
Stock XPU and the installed Modo kit are unchanged.

## Ownership and native integration

`deferred_film.h` owns copies of RGBA, pixel weight, pixel/sample coordinates and
tile/pass identity. Each batch carries an epoch, revision, owner token and unique
serial. The native adapter uses one epoch per frame, including a full context
reload; this is not yet the scene index's resource revision. Its worker accesses
no native scene, film, arena or TLS pointer. Its current backend is a transport
validation pass, **not new GPU shading or accelerated rendering**.

The original native film callback can return after admission. A later callback or
explicit tile/pass drain takes the completion on its owning native thread,
reconstructs an aligned native radiance batch and calls the original film handler.
Original sorting and batch boundaries are retained in FIFO order per owner. The
native handler continues to manage pixel weights, alpha, tile activity and beauty
output. This does not promise deterministic accumulation across multiple workers.

The queue allows 32 outstanding batches and 8 MiB of sample payload, including
both originals and candidate results. Allocator metadata, native input scratch
and the reconstructed film batch are outside that payload limit. Capacity pressure
drains that owner's existing work, then falls back synchronously if admission is
still unavailable. It never waits for another owner to release its queue credits.

Completed failures, invalid identities/weights, changed batch sizes, and NaN/Inf
colors use the intact native contribution. The finite guard inspects float bits
because native fast-math flags can remove ordinary `isfinite` checks. Epoch
changes revoke old queued results without prematurely releasing their storage.
A result can be taken only once. The backend must eventually return; shutdown
joins it, and does not attempt unsafe forced thread cancellation.

Native cancellation preserves already-computed contributions in the *old* film,
as MoonRay normally does. Every native worker drains before it exits its pass;
frame stop checks that no completions remain before joining and destroying the
queue. A subsequent frame has a new epoch. Multiple simultaneous RenderContexts
are not supported by this diagnostic's single active-frame adapter.

## Deliberate synchronous fallbacks

- Any batch with deep or Cryptomatte handles stays entirely on the native path;
  copying integer handles would not own their referenced data.
- Adaptive sampling stays on the native path. A trial that deferred its film
  writes changed convergence decisions (4,897 pixels in the one-worker fixture).
  Draining only after tile groups/passes was too late. Adaptive suspension needs
  completion barriers for film readers across *all* relevant owners before it can
  be enabled. We retain the original sampler instead of relaxing image parity.
- Other AOV queues remain native. Their full output semantics are not certified
  by beauty-only image comparisons.

## Reproduce

Use new output directories. No Modo launch or kit installation is needed.

```powershell
python tools/xpu2_deferred_film_contract.py --source <read-only-primary> --output <contracts>
python tools/xpu2_deferred_film_build.py --source <read-only-primary> --base test-results/xpu2-origin-build --output <build>
python tools/xpu2_deferred_film_probe.py --build <build> --reference test-results/xpu2-origin-build/control --output <images>
```

The image runner also accepts `--adaptive`, `--crypto`, `--threads 4`, and
`--persistent`. The latter runs three complete reloads in each of two sessions.
Use its passed result with:

```powershell
python tools/xpu2_deferred_film_cancel.py --build <build> --baseline <persistent-results> --output <cancel-results>
```

`XPU2_DEFERRED_FILM=1` enables the isolated adapter. `XPU2_DEFERRED_PROFILE`
records frame accounting. FAIL, INVALID, SENTINEL and DELAY_MS variants under the
same prefix are diagnostic injections only. A sentinel changes RGB to prove
that resumed contributions reach the real film, not merely a sidecar buffer.

## Validation — 2026-10-17

The final build completed 25 native frames and one cancelled frame across the
fixed-sample, adaptive-fallback, persistent reload, restart and four-worker checks.

- 61 lifecycle assertions and 1,000 concurrent-owner jobs passed under fast-math;
  all 368 existing XPU2 regression tests passed.
- 13 non-reference one-worker RGBA comparisons were exact. This includes exception
  and NaN fallback, adaptive bypass, three persistent frames and cancellation/reload.
- Four multithread comparisons passed the predeclared 1e-6 absolute/relative bound.
  Their largest difference was 1.49e-8, including the disabled adapter control.
  This is RGB tolerance parity, not multithread bitwise repeatability.
- The sentinel changed 23,346 pixels with one worker and 20,370 with four workers,
  confirming native film integration. Adaptive bypass correctly ignored it.
- Cancellation drained 16 batches / 7,885 contributions before context teardown.
  The next frame resumed 411 batches / 503,073 contributions and matched a fresh
  reference. A 50 ms worker delay forced bounded queue pressure: 32 jobs,
  7,749,632 payload bytes, 12 declined admissions followed by safe drain/retry.
- The Cryptomatte fixture failed in the unchanged reference runtime during
  rendering, before an image was produced. Its native handle bypass is therefore
  **unvalidated**, as is deep-output bypass. Neither is counted as passing.

Compact hashes/accounting are in `native-film-continuations-20261017.json`.
Full local reports are under `test-results/xpu2-deferred-film-final-*`; the build
is `test-results/xpu2-deferred-film-build-v3`. This uses retained native link inputs,
not a clean rebuild. Timings are not evidence of a speed improvement.

## Remaining native path work

A terminal film record has no pending ray to resume. Arbitrary native path
continuations still require splitting the integrator at a supported stage,
owning sampler/BSDF/light state and native handles, scheduling on valid CPU TLS,
and connecting texture-ready jobs and GPU completion fences. The current transport
worker and texture dispatcher are not joined yet. This step establishes a tested
film boundary for that work; it is not a completed XPU2 architecture or a speedup.
