# Explicit native sample-window dispatch

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

An optional `--profile --window-dispatch` build adds owned, unpublished queue
requests. `XPU2_WINDOW_DISPATCH=1` opts into the behavior at runtime. Existing XPU,
the default diagnostic build and the installed kit are unchanged.

The native Lambert hook copies each packet into the bounded queue, consuming a
credit immediately, but does not make it dispatchable. The first collection at
the end of the native sample window publishes that thread's outstanding tickets
under one queue lock. The worker can then pack the entire ready window without
waiting for a guessed coalescing delay. CPU fallback values, original SIMD lanes,
native light records and ordered collection are preserved. CPU reference shading
and exact GPU comparison remain enabled.

Publication validates every ticket before changing any: queue identity, revision,
credit, pending membership, cancellation/completion state, duplicate membership
and the sixteen-packet publication limit. Invalid publication leaves all tickets
held. The worker skips unfinished producers and can dispatch a different ready
producer's work. Held requests count against admission capacity. Cancellation
releases queued credits; stop cancels unpublished requests and drains published
work. Completed-but-uncollected results still own their credits until collection.

Native integration uses a thread-local pending-window marker. It rejects
publication while any slot still has an unfinished sampling/light stage. A
partial final window is published at collection, including a one-packet tail.
Multiple-Lambert and post-sampler guards retain their existing fallback behavior.
No native pointers are sent to the GPU worker.

## Limits

This groups independent shader packets inside the existing resident native stack.
It does not suspend whole paths, eliminate CPU reference shading or introduce
asynchronous CUDA copies. Holding a complete window delays GPU submission until
its CPU light work is prepared; reduced launch/transfer overhead may come at the
cost of less within-window overlap. Broader path ownership is still needed for
sustained cross-path CPU/GPU overlap. Multi-worker image parity and production
Modo shutdown/recovery are not certified by this diagnostic.

## Recorded validation

[Evidence](window-dispatch-20261017.json) records fifteen native render cases and
seven standalone guard processes. All 226 XPU2 Python tests also passed. Normal/fallback renders match original XPU
float32 RGBA, selected rays and radiance contribution multisets exactly, without
shadow visibility changes. The altered-color GPU sentinel changes the film.
Each normal candidate accepts all 210,114 shader samples across 26,271 tickets.

The timed-coalescing controls dispatched 5,790 / 5,793 GPU batches. Explicit
nine-packet windows dispatched exactly 2,919 in both repeats and the full-logging
audit. Four/four/one windows dispatched 8,757 batches; one-packet windows dispatched
26,271. These checks establish complete-window and partial-tail behavior rather
than inferring grouping from wall-clock speed.

Mcrt times were 2.694 / 2.252 seconds for quiet timed coalescing and 2.018 / 1.635
seconds for explicit windows. Synchronous host-to-device plus device-to-host copy
time dropped from 1.083 / 1.039 seconds to 0.518 / 0.496 seconds. GPU event
intervals totaled approximately 0.039 seconds for each grouped run. The serial
window control took 8.795 seconds; four/four/one took 3.338 seconds. Full diagnostic
logging with complete windows took 2.943 seconds.

Original XPU took 0.387 / 0.371 seconds; relinked controls took 0.381 / 0.359 seconds.
Explicit windows reduce this candidate's overhead but remain slower than XPU.
This is an instrumented single-worker fixture with uncontrolled caches and machine
load; the timing ranges are observations, not a production performance guarantee.

Guard coverage includes sixteen owned slots, reverse collection and caller-buffer
reuse; missing lanes, transformed answers and multiple-lobe rejection; unpublished
capacity limits; atomic rejection of foreign, stale, duplicate, cancelled, empty
and oversized publications; ready work passing an unfinished producer; and stop
cancelling held work while draining published work. Queue credits and GPU resources
were explicitly released in the standalone processes. Those checks do not certify
Modo DLL shutdown or full multi-worker renderer operation.

## Reproduce

Use fresh output directories and the retained native inputs:

    python tools/xpu2_build_batched_shading.py --profile --window-dispatch --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/window-build-new
    python tools/xpu2_profile_probe.py --window-dispatch --build test-results/window-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/window-native-new
    python tools/xpu2_batched_guard_probe.py --profile --window-dispatch --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/window-guards-new

Timing interpretation and overlap limitations follow [profiling](PROFILING.md).

The next optional experiment adds [pinned asynchronous transfers](ASYNC_TRANSFERS.md)
while retaining these explicit window boundaries and synchronous A/B controls.
