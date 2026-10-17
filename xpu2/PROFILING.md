# Native shading overhead measurements

The optional `--profile` build instruments the bounded Lambert diagnostic.
The normal build and installed runtime remain unchanged. `XPU2_PROFILE_FILE`
enables aggregate counters and nanosecond wall spans; `XPU2_PROFILE_QUIET=1`
suppresses per-packet bridge/queue logs and binary shader records. Exact CPU/GPU
comparison, returned-input verification, CPU fallback, native guards and ordered
collection remain active. This does not remove duplicated CPU shading.

Metrics are atomic aggregates written at standalone process exit. No queue or
native-pointer traversal occurs during that write. An absent/incomplete report
fails the probe. This is not a production DLL unload or device-loss contract.
Error messages remain available in quiet mode.

## What was measured

The nine-sample fixture ran twelve cases: original XPU, relinked control,
disabled hooks, two full-diagnostic renders, two quiet renders, two quiet renders
without selected-ray/contribution tracing, zero-capacity fallback, missing PTX,
and an intentionally altered GPU-color sentinel. The repeated diagnostic cases
run in reverse order on the second pass to expose ordering variation.

Every normal/fallback image matched original float32 RGBA exactly. Traced normal
cases also matched selected rays and radiance contribution multisets without
shadow visibility changes. The sentinel changed the image. Each normal GPU run
accepted and replaced all 210,114 samples, with 26,271 submitted and collected
packets and zero shader comparison errors. Quiet mode does not disable that
comparison. Six standalone ownership/guard/cleanup checks and 224 Python tests
passed. See [recorded evidence](profiling-20261017.json).

Renderer Mcrt times were 2.921 / 3.212 seconds with full diagnostics and
2.237 / 2.301 seconds with quiet diagnostics. Quiet runs without native tracing
were 2.307 / 2.287 seconds. Disabling that selected tracing showed no clear
additional benefit on this fixture.

Full diagnostics accumulated 1.205 / 1.509 seconds in measured logging regions.
Quiet runs accumulated 0.408 / 0.430 seconds in synchronous host-to-device copies
and 0.630 / 0.653 seconds in device-to-host copies. Their GPU event intervals
summed to 0.071 / 0.070 seconds. Waiting inside native collection accumulated
1.657 / 1.721 seconds. Host packing was only 0.008 / 0.009 seconds. These results
point toward transfer/synchronization and scheduling costs, not a heavy Lambert
kernel or expensive host packing.

Removing logging also changes scheduling: worker batches increased from
3,430 / 4,075 to 5,773 / 5,712. The existing coalescer stops waiting once four
packets are present, although this fixture can offer nine before collection.
Logging previously slowed the producer/consumer enough to change grouping.
The A/B comparison measures the total consequence of quiet diagnostics, not an
isolated subtraction of log I/O from an otherwise identical schedule.

Original XPU took 0.371 seconds; disabled hooks took 0.444 seconds. The relinked
control was an outlier at 1.384 seconds. Caches and machine load were uncontrolled,
so these are diagnostic observations, not a stable benchmark or a production
speedup claim. Even quiet XPU2 remains slower than original XPU here.

## Reading the counters

Do not sum all timing fields. Worker and native-thread spans overlap. Device
total contains initialization and validation; collect contains collect wait;
validation contains binary-record I/O. Diagnostic I/O sums measured logging
regions across both threads and includes entry/skip overhead in quiet mode.
Queue residence is summed per request, including concurrent requests and
coalescing, so it can exceed wall time. GPU event intervals overlap host launch
and wait spans and are not a utilization percentage. Context switches, queue
locking and small uninstrumented regions are not assigned separate percentages.
Timer calls and atomics also impose overhead; no instrument-free figure is claimed.

The next optimization should let the producer announce a complete bounded
window, allowing larger batches without relying on a guessed delay. Then test
pinned asynchronous transfers and overlapped dispatch while retaining audit
controls. Removing native reference shading needs a separately validated handoff:
CPU lighting currently uses native direction/PDF before GPU collection.

## Reproduce

Use new output directories. The retained runtime and link inputs are local
validation artifacts, not downloadable production dependencies.

    python tools/xpu2_build_batched_shading.py --profile --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/profile-build-new
    python tools/xpu2_profile_probe.py --build test-results/profile-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/profile-native-new
    python tools/xpu2_batched_guard_probe.py --profile --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/profile-guards-new
    python -m unittest discover -s tests -p "test_xpu2*.py"

Build inputs, preprocessed source, DLLs, PTX, device identity and output evidence
are hashed. This milestone does not certify multithread image parity, arbitrary
materials, texture streaming, scene loading or Modo lifecycle behavior.
