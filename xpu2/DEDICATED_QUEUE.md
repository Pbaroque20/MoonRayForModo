# Dedicated native GPU queue during active rendering

Status: **validated in an isolated native stress build**. XPU2 now has a
separately reserved OptiX queue slot for this diagnostic while original native
workers continue rendering. This does not enable an installable XPU2 engine or
add new GPU shading contributions to the film.

## Queue and lifetime rules

With both `XPU2_NATIVE_SCENE_DRAIN=1` and `XPU2_NATIVE_DEDICATED_QUEUE=1`, the
copied GeometryManager constructor allocates one extra native GPU slot. Native
worker indices remain unchanged; the diagnostic uses index `numCPUThreads`.
The native OptiX implementation allocates a separate pipeline, stream, parameter
buffer, ray buffer and output buffers for that slot. Both queues read the same
unchanged scene accelerator.

The first native shadow batch is copied with its reference visibility answers.
A background worker pushes the native CUDA context and immediately replays it
through the extra slot. Runtime guards verify the registered accelerator and
strictly separate queue indices. Scene changes, accelerator rebuilds and context
teardown retain the preceding drain/join guards. No scene mutation is permitted
while that borrowed accelerator is in use.

The stress worker repeats its copied batch 4,096 times. Native begin/end hooks
count complete native query calls that occur within the worker's service window
and before the stop request. This establishes host-side service interleaving and
independent queue use, not simultaneous hardware kernel execution. The repetitions
are diagnostic work, not additional image samples or a performance optimization.

Without the dedicated flag, the previous delayed-after-stop replay remains
available. With both flags disabled, neither replay nor the extra slot is enabled.
The shared native source checkout and installed runtime are unchanged.

## Rendered validation — 2026-10-17

Nine completed renders used the retained reference, hooks-disabled control and
hooks-enabled candidate: initial scene, mesh transform update, full scene reload.
A fourth session tested cancellation. All ran on one native renderer thread and
an RTX 3090. Completed renders used a 4 by 4 pixel sample grid at 256 by 144 pixels.

- All six float32 RGBA control/candidate comparisons matched exactly.
- The mesh update changed 26,371 pixels; full reload restored the initial image.
- The completed candidate replayed 44,257,280 ray queries with zero disagreements.
  Native queries completed during its service windows 18, 25 and 34 times: 77 total.
- The cancelled session replayed 14,774,272 ray queries with zero disagreements.
  Its stop request preceded worker completion; join preceded teardown. It exited
  cleanly with CANCELED and no DONE event for the interrupted frame.
- These 59,031,552 queries repeat 14,412 captured rays, including blocked rays.
  They do not represent 59 million distinct test cases.
- All 306 XPU2 regression checks passed, including 19 lifetime/evidence checks.

The initial 64-repetition burst was rejected by the overlap gate because it
finished before the next native GPU query. Increasing the bounded stress work
made concurrent queue use observable; the acceptance condition was not relaxed.
Images from that first rejected run were not certified by the runner.

## Remaining integration

Next, route accepted owned GPU shading/light results through this reserved slot's
visibility service and into native contribution acceptance. That still requires
revision-safe, exactly-once film writes and native continuation handling. The
current extra worker only checks visibility; it does not accelerate production
shading or establish faster scene loading.

This result covers one native renderer thread and one pending batch per frame.
Multiple native workers/contexts, device loss, general scene/resource ownership,
texture residency and broad scene parity remain separate gates. The existing
10-second drain timeout aborts the disposable diagnostic if work cannot finish;
that failure path was not injected here and is not production recovery.

## Reproduce

Build with `tools/xpu2_native_drain_build.py --source <read-only-native-checkout>
--frozen-build test-results/xpu2-origin-build --output <new-build-folder>`.
Run `tools/xpu2_native_drain_probe.py --build <new-build-folder> --reference
test-results/xpu2-origin-build/control --output <new-results-folder> --dedicated`.

This links retained native inputs with three newly preprocessed hook objects;
it is not a clean source rebuild. The build and local results are under
`test-results/xpu2-dedicated-queue-stress-build` and
`test-results/xpu2-dedicated-queue-stress-final`. Only source and aggregate
[evidence with hashes](dedicated-queue-20261017.json) are published.
