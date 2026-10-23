# Native split-phase Lambert handoff

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The experimental native adapter submits a copied Lambert packet, returns to
MoonRay, lets the CPU evaluate the light set, and collects the GPU answer before
integrating that BSDF sample's contribution. This is a deferred native result
handoff with a resident stack, not suspension of a whole MoonRay path.

## Ordering and ownership

The isolated PathIntegratorUtil patch opens a thread-local scope immediately
before BsdfSampler_sample. The nested Lambert hook submits numeric copies to
the existing GPU queue and returns the original CPU answer without waiting.
After the sampler returns, further Lambert calls cannot enter that scope.

Valid lanes perform the original light intersection/evaluation on the CPU.
All sampled lanes then reconverge for collection, including invalid lanes that
still own requests. Before integrating the contribution, collection may replace
only the BSDF RGB value. It never changes the direction, PDF, sample validity,
light choice or sampler counters used by the intervening CPU work.

This uses the native CPU answer speculatively. The existing GPU bridge requires
bitwise equality of direction, RGB, PDF and validity before accepting a GPU
replacement. CPU reference computation remains duplicated. Missing PTX,
unsupported shader inputs or full GPU admission preserve the CPU result.

The additional handoff guard checks that the post-sampler direction, RGB and PDF
still equal the Lambert answer captured at submission. A wrapper that changed
them keeps its CPU result. Multiple Lambert calls in a single scope cancel the
ticket rather than guessing which output belongs to the final sample. Collection
checks the original SIMD lanes; a missing lane cancels the whole packet.
Collection sleeps on the ticket completion condition instead of spinning.
The predicate handles completion before the wait starts. The wait has a deadline
and cancels on timeout.

The worker owns copied values and cannot access the native sample array,
intersection, BSDF, arena or TLS. Their lifetime remains protected by the native
call stack, which does not return until this handoff has finished. This avoids
the original use-after-free hazard without claiming a restorable native path.

## Scope and remaining work

This probe is single-worker, fixture-specific, and opt-in through diagnostic
environment settings. Each diagnostic process renders one immutable scene and
uses a fixed ticket revision; this does not handle live edits or render restarts.
It is not included in the Modo kit. The diagnostic helper
DLL uses a process-lifetime queue; production cancellation, render-attempt
integration and unload-safe service ownership are not implemented here.
Standalone guard tests explicitly drain and join their queue, but that is not
a native Modo lifecycle test.

The GPU kernel and queue are unchanged. Native CPU reference shading is still
computed, and collection may wait for the GPU. No speedup is claimed. Measurements
of a pending GPU or kernel overlap are observations, not throughput benchmarks.
Full asynchronous path scheduling still needs owned integrator/BSDF/light state,
resumption on the proper CPU queue and deterministic contribution accounting.
Multithread image parity and general materials remain separate gates.

## Recorded validation

[Evidence](deferred-shading-20261017.json) includes the final ten-case native
matrix, five standalone guard cases, complete build manifest and earlier results.

All ten native cases passed: original retained runtime, rebuilt control, disabled
adapter, replacement, repeat, altered-result sentinel, zero-capacity fallback,
missing-PTX fallback, unsupported control and unsupported fallback. Normal and
fallback images match their reference RGBA bit for bit, as do selected native
rays and radiance contribution multisets; shadow visibility is unchanged.
The sentinel intentionally changes returned RGB and reaches the film.

Each ordinary replacement run submitted and collected 11,680 packets containing
93,384 native Lambert samples. GPU direction, RGB, PDF and validity matched their
native reference bits. All 11,680 packets passed through native light evaluation
before collection, without guard fallbacks, timeouts or outstanding queue credits.

The first successful candidate repeatedly polled for completion millions of times.
The final candidate sleeps on completion instead: 11,680 waits in each replacement
run. Both native rendering and standalone guards were rerun after this change.

Five final standalone cases passed: successful delivery, transformed post-sampler
data, a missing lane, multiple Lambert calls and rejected nested scopes. Their
queues explicitly drained, joined and released GPU resources.

Neither replacement run observed a GPU-kernel/CPU-light overlap. This tiny
fixture's CPU light stage is too short to establish useful overlap at this
boundary, and the instrumented candidate is slower than the control. Batching
more independent work and reducing diagnostic overhead are still needed before
claiming acceleration. These warmed, heavily instrumented runs are not a
representative performance benchmark.

An initial run stopped because the rebuilt renderer lacked contribution trace
objects. The corrected build retains those hooks in both control and candidate,
and additionally verifies the original retained runtime. The failed run is kept
in evidence. The unchanged 219-test suite and multithread matrix were not rerun
for this native-only change.

## Reproduce

Use fresh output directories and the retained inputs:

    python tools/xpu2_build_deferred_shading.py --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/deferred-build-new
    python tools/xpu2_deferred_shading_probe.py --build test-results/deferred-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/deferred-native-new
    python tools/xpu2_deferred_guard_probe.py --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/deferred-guards-new

The builder patches only isolated copies, freezes both rendering DLLs' original
link inputs, retains contribution-tracing objects in both control and candidate,
and records hashes of source, compiler, preprocessed source and output DLLs.
The final native matrix also compares the rebuilt control with the original
retained tracing runtime.

## Batching follow-up

[BATCHED_SHADING.md](BATCHED_SHADING.md) extends this handoff to bounded windows
of native samples before ordered collection. Full path suspension remains separate.
