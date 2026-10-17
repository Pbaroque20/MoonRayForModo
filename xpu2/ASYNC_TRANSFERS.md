# Pinned asynchronous transfers

The optional `--profile --window-dispatch --async-transfers` build includes a
separate CUDA transfer path, selected by `XPU2_ASYNC_TRANSFERS=1`. The same build
can run the existing synchronous path for comparison. Existing XPU, the installed
kit and the default diagnostic build are unchanged.

The worker allocates four pinned host buffers once, totaling 118,784 bytes for
up to 512 shader samples, plus a nonblocking CUDA stream and a completion event.
Each batch copies inputs into those owned buffers, queues two uploads, kernel
start/end events, the kernel, two downloads and a completion event on that stream.
It waits on the completion event before reading outputs or reusing staging memory.
The existing returned-input echo and exact CPU/GPU comparison remain mandatory.
Only validated output is eligible for the guarded native handoff.

This is one stream with one batch in flight. It replaces repeated synchronous
transfer barriers with one completion boundary; it does not overlap independent
batches, suspend native paths, or remove CPU reference shading. The worker waits
without polling, so kernel-window polling observations are not collected in this
path and must not be compared with the synchronous path as overlap measurements.

## Failure and lifetime rules

A batch exception disables reuse of the bridge, drains its stream when available,
and retains CPU fallback values. Shutdown first confirms device completion before
freeing pinned memory. An unconfirmed drain leaves resources retained and reports
cleanup failure rather than releasing possible DMA targets. Partial allocations
are tracked individually. These are standalone diagnostic semantics, not a Modo
DLL-unload or device-loss recovery implementation.

The test-only `XPU2_ASYNC_FAIL_STAGE` can inject failures after the second pinned
allocation, uploads, kernel launch or queued readback. Injected failures exercise
ordinary exception cleanup with a functioning CUDA context; they do not simulate
a driver reset or GPU hang.

## Timing interpretation

In async mode, `htod_ns` and `dtoh_ns` measure host enqueue cost, not completed
transfer duration. `device_wait_ns` includes remaining transfer and kernel work;
`staging_ns` measures CPU copies into/out of pinned memory. Kernel event intervals
exclude copies. The renderer's Mcrt time is the end-to-end rendering comparison.
These spans overlap with native collection wait and must not be summed together.
Raw enqueue timings cannot be compared to synchronous transfer times as proof of
PCIe bandwidth improvement.

## Recorded validation

[Evidence](async-transfers-20261017.json) records seventeen native render cases
and twelve standalone guard processes. All 229 XPU2 Python tests passed. Normal/fallback images match original XPU
float32 RGBA exactly, with identical selected rays and radiance contribution
multisets and no shadow visibility changes. The altered-color sentinel changes
the image. Each ordinary GPU run accepts all 210,114 shader samples and collects
all 26,271 packets. Async runs record 2,919 completed GPU batches; synchronous
controls record no async batches. The partial four/four/one case completes 8,757.

Synchronous windows took 1.544 / 1.556 seconds of Mcrt time. Async windows took
1.376 / 1.366 seconds, about 11â€“12% less on this run. Original XPU took
0.370 / 0.376 seconds and remains faster. Full logging with async transfers took
2.856 seconds. These are instrumented single-worker observations with uncontrolled
caches/load, not a production performance guarantee.

Async upload enqueue spans totaled 0.028 / 0.027 seconds, readback enqueue spans
0.335 / 0.344 seconds, and completion waits 0.255 / 0.239 seconds. CPU staging
copies took about 0.004 seconds. Readback submission remains costly: CUDA async
calls can incur driver/submission overhead even with pinned memory. GPU event
intervals increased to 0.228 / 0.225 seconds from about 0.040 seconds in the sync
controls. They can include scheduling/submission gaps between stream events;
these numbers do not establish that shader arithmetic became slower or measure
pure ALU time. This comparison changes submission/wait strategy as a whole.

Standalone checks reuse pinned buffers across batches of 1, 8, 72, 512 and 3
samples, checking all 596 outputs before cleanup. Additional cases inject failure
after partial pinned allocation, uploads, kernel launch and queued readback.
They verify unchanged CPU output, disabled failed-bridge reuse, and explicit
release of pinned buffers, stream, events and context. Existing lane/slot,
publication, cancellation and shutdown guard cases also pass with async enabled.
Native failure cases after upload/launch/readback preserve the full image, with
one failed async batch and no async completion/publication.

## Reproduce

Use fresh output directories and retained native link inputs:

    python tools/xpu2_build_batched_shading.py --profile --window-dispatch --async-transfers --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/async-transfer-build-new
    python tools/xpu2_profile_probe.py --window-dispatch --async-transfers --build test-results/async-transfer-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/async-transfer-native-new
    python tools/xpu2_batched_guard_probe.py --profile --window-dispatch --async-transfers --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/async-transfer-guards-new

The native diagnostic remains a single-worker Lambert fixture. It does not
certify arbitrary materials, textures, multithread film parity or scene-load speed.
