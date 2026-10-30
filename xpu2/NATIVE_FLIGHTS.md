# Bounded native batches in flight

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Experimental extension to the copied native diffuse-shading candidate. It leaves
original XPU and the installed kit unchanged. This is numerical early diffuse
shading, not full asynchronous material evaluation or whole-path ownership.

## Ownership and execution

`XPU2_INFLIGHT_BATCHES` selects 0 (the serial bridge, default), 1, 2, 3 or 4
independent slots. Each enabled slot has persistent pinned host staging, device
buffers, a nonblocking CUDA stream, kernel timing events and a completion event.
Allocations finish before the first asynchronous submission. The worker fills
available slots before polling, and can retire completed slots in any order.

Each submission schedules input and length uploads, shader execution and both
result readbacks on its own stream. A completion event follows the readbacks.
Until that event completes, neither staging nor device buffers can be reused.
Returned values are copied into the original request, whose scene revision and
owner are checked before its caller can consume the result. Sampling values,
ISPC lane grouping and CPU-side film publication are unchanged.

Pending cancellations release their credits immediately. Worker-owned requests
retain credits and referenced resources until their slots retire, and cancelled
results never publish. Queue stop drains outstanding slots before freeing host
or device memory. Recoverable submission errors synchronize outstanding GPU work,
discard affected results and permit native CPU fallback. Fatal device/context
loss fails closed in this isolated process; production recovery from that loss
is not claimed.

An owned-child continuation addresses a different lifetime: it carries a path's
resume state instead of referring to a parent's temporary arena. It can own a
request in this pipeline, but cannot replace stream events, revision checks,
bounded buffers or exactly-once publication. This change preserves the existing
early-dispatch path; it does not merge the separate owned-child prototype.

The implementation uses pinned allocations and asynchronous driver copies with
explicit streams; see NVIDIA's [memory API](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__MEM.html).
Several outstanding submissions do not prove simultaneous kernel execution,
transfer/compute overlap or an improvement over native AVX shading.

## Validation and timing protocol

The standalone CUDA stress cases check multiple outstanding flights, reverse-order
collection, stale/foreign/duplicate rejection, cancellation, missing PTX and full
slot cleanup. An injected error after uploads verifies draining before fallback.
A separate host-callback gate holds four real CUDA streams incomplete: cancelling
their requests must retain resources until the gate is released, publish nothing,
and reclaim every credit after drain. This gate is not an executing shader kernel.

Rendered controls compare original XPU, disabled hooks, four slots, a deliberate
GPU color perturbation, missing PTX, zero capacity and upload-failure fallback.
Persistent-session checks compare fresh frames and cancel/reload output.
The 1e-6 image gate remains unchanged, with exactness also recorded.

Timing compares original XPU, the candidate serial bridge, and 1/2/4 slots with
identical FIFO selection, packet limits, fixture, PTX, thread count and settings.
Each configuration has a warmup process followed by three rotated-order measured
rounds. Per-batch logs are off; linear image extraction runs outside timing.
Process wall time and native MCRT time are reported separately. All processes
still initialize their own GPU contexts.

Flight telemetry records configured and peak occupied slots, submitted/retired
batches, event polls, incomplete-event observations, submission/poll CPU intervals,
error drains and summed kernel-event duration. Peak occupancy measures outstanding
submissions; it is not measured simultaneous GPU kernel occupancy. Tile-profile
device time becomes a sum of overlapping batch lifetimes and must not be compared
as exclusive worker utilization against the serial bridge.

## Reproduce

- Build with `tools/xpu2_native_flight_build.py`, using the same frozen origin
  link inputs and read-only native source checkout as the tile candidate.
- Run `tools/xpu2_native_flight_stress.py`; add `--upload-failure` for the
  partial-upload fault.
- Run `tools/xpu2_native_flight_held.py` for incomplete-stream cancellation.
- Run `tools/xpu2_native_flight_benchmark.py` with `--checks` for image controls,
  or `--threads 1 --repeats 3` for paired timing.
- Run `tools/xpu2_native_flight_cancel.py` against a passed controls directory
  for native persistent-frame cancellation/reload.

Every command requires new isolated output paths; no installation is performed.

## Results on RTX 3090 / native AVX1 (2026-10-18)

Reports and hashes: [native-flights-20261018.json](native-flights-20261018.json).
The fixed diffuse fixture is 384 x 216, with three measured rounds per mode.

- One CPU worker: median MCRT is **14.586 s serial**, **13.974 s one slot**,
  **11.786 s two slots**, **11.802 s four slots**. Two slots shorten the serial
  candidate's render phase by **19.2%**. Median process time falls from 15.983 to
  13.120 s (17.9%). All 20 images, including warmups, are exact relative to the
  original XPU reference. Original XPU itself remains much faster at **3.734 s**
  MCRT / 5.018 s process time: this is a candidate improvement, not an XPU speedup.
- Four CPU workers: median MCRT is **5.029 / 4.962 / 4.148 / 4.797 s** for the
  same modes. Original XPU is **1.225 s**. The strict image gate fails for original
  XPU repetitions as well as candidate runs; these are diagnostic timings only.
  Queue-capacity refusals and therefore GPU/CPU workload shares also differ with
  scheduling. No multiworker parity or production-speed claim is made.
- Two-slot runs reach two occupied slots; four-slot runs reach three with one CPU
  worker and four with four CPU workers. This proves multiple outstanding native
  submissions, not simultaneous hardware kernel execution. More slots do not
  consistently help this small-workload pipeline.
- Seven rendered controls pass: disabled hooks, real GPU shading, deliberate
  color perturbation, missing PTX, zero capacity and injected upload failure.
  Three ordinary CUDA stress cases and the separate partial-upload failure case
  pass. The gated-stream check holds four incomplete flights, cancels them,
  retains their resources until drain and publishes zero cancelled results.
- Persistent fresh and cancel/reload runs pass, including exact final RGBA and
  retirement of all submitted flights in both cancelled and replacement frames.

Summed kernel-event intervals may include submission/scheduling gaps and can
span overlapping work; they are not exclusive GPU compute utilization. The
candidate still uses small shader packets, frequent driver calls and dependent
native barriers. Two slots are the preferred **next experimental comparison**;
production remains unchanged and the default environment setting remains serial.
Larger useful batches and more independent ready work are still needed. Owned-child
continuations may supply that work, provided sampler state, arena ownership and
exactly-once film publication survive suspension/resumption.
