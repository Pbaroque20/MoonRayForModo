# Native lighting work during GPU dispatch

The optional native-overlap candidate tests actual MoonRay CPU light evaluation
between GPU publication and collection. It does not suspend or migrate native
paths. The stack, arena, BSDF and light references stay alive until collection.
No installed runtime or kit changes; existing XPU remains independent.

## Scheduling boundary

For each bounded window the candidate:

1. Generates the original BSDF and light-filter samples in their per-stream order,
   retaining validity and light-filter values in sixteen bounded stack slots.
2. Publishes the complete owned GPU packet window.
3. Evaluates native CPU lighting in sample order, using the unchanged native
   direction/PDF and the saved light-filter random values.
4. Collects in original sample order and integrates/clamps native contributions.

GPU requests still own numeric copies, and all native references remain on the
resident CPU stack. The new slot-selection hook cannot abandon active sampling
or lighting; early publication rejects unfinished windows. Publication is
idempotent after release. Existing post-sampler, lane, fallback and ownership
checks remain. Full GPU shader auditing is enabled throughout the render matrix.
Duplicated CPU reference shading has not been removed.

Both build flag `--native-overlap` and runtime flag `XPU2_NATIVE_LIGHT_OVERLAP=1`
are required. The flag-off path retains the previous sample/light preparation
order. No plugin engine selector exposes this experiment.

## Validation

Evidence is retained in `native-light-overlap-20261017.json`, including source,
compiler, executable/runtime, PTX, GPU and log identities. The isolated build is
`test-results/xpu2-native-overlap-build`; render results are in
`test-results/xpu2-native-overlap-renders`; guards are in
`test-results/xpu2-native-overlap-guards`.

All 15 native render cases passed on the single-worker Lambert fixture:
original XPU, relinked control, disabled hooks, prior packed schedule/repeat,
overlap/repeat, four/four/one tail, zero capacity, missing PTX, injected readback
failure, color sentinel, verbose audit, and repeated control/original.

Every non-sentinel image matches the reference float32 RGBA bits exactly, along
with selected rays, radiance contribution multisets and shadow visibility.
The sentinel deliberately changes the film. Normal overlap runs each replace
210,114 shader samples in 2,919 GPU batches. All 26,271 CPU lighting starts observe
their GPU result still pending. This includes queued/transferring/driver work;
it does not establish simultaneous GPU kernel execution or utilization.

All 19 standalone GPU guard cases passed. The new early-publication guard holds
the GPU worker, rejects publication during sampling, publishes a complete window
once, enters CPU lighting before GPU completion, rejects abandoning active light
state, collects reversed slots correctly, rejects retired slots, and drains all
resources. This is standalone shutdown evidence, not Modo unload/device-loss
validation. The complete XPU2 unit suite passed 238 tests.

## Timing result

There is **no convincing native render speedup** on this fixture:

- Prior packed schedule Mcrt: 1.337 / 1.398 seconds.
- Native lighting overlap Mcrt: 1.310 / 1.388 seconds.
- Original XPU Mcrt: 0.405 / 0.353 seconds.
- Relinked XPU controls: 0.358 / 0.368 seconds; disabled hooks: 0.424 seconds.

CPU lighting spans total only 11.3-13.0 ms over all 2,919 windows, roughly four
microseconds per window. Collection wait spans are 717-751 ms with overlap and
807-858 ms with the prior schedule; they include initialization and are not
independent components to add to other timings. Driver enqueue and scheduling
variation remain substantial. Two repetitions, uncontrolled cache/clock state
and a small diagnostic scene do not establish a statistically robust improvement.
Regression tests and compilation had finished before the render matrix began.

The earlier synthetic 1.94x scheduling result has not translated into native
render acceleration. This narrower boundary proves safe ordering for the tested
fixture but provides too little useful CPU work to hide most of the handoff cost.
The next architectural step remains independently owned native paths, so workers
can process substantially more ready work while GPU batches are outstanding.

## Limits

Only the restricted single-worker Lambert fixture has rendered validation.
Saved light-filter state is explicit, but arbitrary light filters and general
materials have not been validated by this matrix. Whole-path suspension, valid
TLS/arena restoration, full native state ownership, multi-worker film parity,
texture residency and geometry streaming remain incomplete. Do not enable this
candidate as a production renderer or describe it as independent native-path
scheduling.

## Reproduce

Use new output directories, outside the shared source checkout:

    python tools/xpu2_build_batched_shading.py --profile --window-dispatch --async-transfers --packed-readback --native-overlap --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/native-overlap-build-new
    python tools/xpu2_batched_guard_probe.py --profile --window-dispatch --async-transfers --packed-readback --native-overlap --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/native-overlap-guards-new
    python tools/xpu2_profile_probe.py --window-dispatch --async-transfers --packed-readback --native-overlap --build test-results/native-overlap-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/native-overlap-renders-new
