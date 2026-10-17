# Bounded native shading batches

The next native diagnostic prepares a small window of BSDF samples and CPU light
evaluations before collecting GPU results in the original sample order. Each
Lambert request owns copied numbers. Native light records stay on the live CPU
stack and never enter the GPU queue.

The window defaults to four SIMD packets and has a hard limit of sixteen per
native thread. Each packet holds up to eight active lanes. Partial windows and
per-lane sample counts keep their original masks. Invalid samples still collect
or retire their tickets before continuing. Sampler sequence state, light choices,
contribution order and clamping stay in the native integrator.

This is still a resident-stack adapter. It does not suspend whole paths, free
native arenas early, or support live scene revision changes. Fixed revision 1
is valid only for these immutable, single-render diagnostic processes.

## Ownership and fallback

The bridge tracks a distinct slot for every outstanding native packet. A slot
cannot be reused before collection. Bounds checks reject negative or overflowing
indices; switching slots cannot abandon an unfinished sample/light stage.
The earlier handoff guards remain: reject multiple Lambert calls, missing lanes
and post-sampler values that differ from the submitted native answer.

Only RGB is substituted, after the unchanged GPU bridge's exact comparison of
direction, RGB, PDF and validity. CPU reference shading is deliberately retained.
Collection uses completion-event waiting. Unsupported inputs, missing PTX and
full admission keep the CPU answer. The process-lifetime helper is not a
production DLL-unload service.

A six-case standalone check covers the previous guards plus sixteen concurrent
slots, caller-buffer reuse, distinct lane routing, reverse-order collection,
rejected slot reuse and explicit GPU drain/join/cleanup. Native rendering is
checked separately; standalone cleanup does not establish Modo lifecycle safety.

## Scope

These experiments test batching within a lobe's sample loop. They do not batch
arbitrary independent paths across a render, move general material shading to
the GPU, or remove duplicated CPU work. General materials, multithread bitwise
image parity, live cancellation/revision integration, texture residency and
geometry streaming remain unfinished.

The queue's optional coalescing delay affects tiny workloads. The four-sample
matrix uses a 100-microsecond coalescing ceiling in both serial and batched cases.
The wider fixture additionally compares an immediate, zero-delay serial control.
Instrumentation and cache state make these diagnostic timings unsuitable as
production speedup claims.

## Recorded validation

[Evidence](batched-shading-20261017.json) records nineteen native render cases,
six standalone guard processes, the frozen build inputs and all source hashes.

The eleven-case four-sample fixture passed original/control/disabled, batched
replacement/repeat, one-packet control, altered-RGB sentinel, zero-capacity,
missing-PTX and unsupported-input controls. GPU dispatches dropped from 11,680
in the serial case to 2,952 in the replacement run (2,942 on repeat), with up to
32 samples per GPU batch. Kernel-window overlap was not observed on this fixture.

The eight-case nine-sample fixture adds a wider sixteen-slot limit and a
four-slot case with a one-slot final tail. All normal/repeat/tail images, selected
rays and radiance contribution multisets match their original XPU reference
exactly, with unchanged shadow visibility. The sentinel changes the film as
intended. Each fixture uses its own reference at the same sampling settings.

The wider replacement run reduced dispatches from 26,271 in the immediate
one-packet control to 3,326 (3,479 on repeat), with up to 72 samples per GPU batch.
The bridge recorded 10 and 81 kernel-window CPU-light observations in replacement
and repeat. Those are polling observations, not overlap duration or utilization.
Different GPU batch groupings still produced identical images.

No native tickets or batch slots remained outstanding. The standalone sixteen-slot
test also passed reverse collection, buffer reuse, lane routing, rejected slot
reuse/bounds, and explicit cleanup. The tested single-worker native peak was
four slots on the first fixture and nine on the second.

The instrumented nine-sample Mcrt time was 0.355 seconds for original XPU,
11.967 seconds for the immediate one-packet candidate, and 2.764 / 2.883 seconds
for wider replacement / repeat. Batching substantially reduces this diagnostic's
dispatch overhead, but it is still slower than existing XPU. CPU reference
shading and per-packet tracing remain present. These are not cold-load or
production performance measurements.

No installed kit/runtime, user scene or concurrent checkout was modified.
The unchanged 219-test unit suite and multithread image matrix were not rerun.

## Reproduce

Use new output directories and the retained source/build fixtures:

    python tools/xpu2_build_batched_shading.py --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/batched-build-new
    python tools/xpu2_batched_shading_probe.py --build test-results/batched-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/batched-native-new
    python tools/xpu2_batched_window_probe.py --build test-results/batched-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/batched-wide-new
    python tools/xpu2_batched_guard_probe.py --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/batched-guards-new

Optional aggregate timing and quiet diagnostics are described in
[Native shading overhead measurements](PROFILING.md). The audited shader
comparisons remain enabled in that mode.
