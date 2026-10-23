# Native synchronous/asynchronous timeline diagnostic

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This opt-in diagnostic isolates the shading bridge's host work, native waits and
CUDA stream intervals in the frozen four-owned-chunk candidate. Original XPU,
shader kernels, sample identities, film order and the installed kit are unchanged.
It is a measurement tool, not a speed optimization.

`XPU2_TIMELINE=<csv path>` records bounded writer-owned thread buffers and flushes
them only after the renderer's shading queue has joined. No file output or shared
trace mutex occurs on each event. Thread registration takes one registry lock.
Each thread has a one-million-event limit; the analyzer rejects dropped records.
Absent the flag, no trace records or additional CUDA events are created.

## What is separated

- Native window preparation, later CPU lobe work and native resume scopes.
- Condition-variable waits for unfinished shading results. These include wakeup
  and queue-lock reacquisition; they do not include all possible CPU mutex waits.
- Worker packing, host enqueue calls, inclusive dispatch, retirement and empty
  queue waits. Empty waits start only when both pending and in-flight work are empty.
- CUDA upload-to-kernel, kernel-to-download and download-to-completion intervals,
  identified by batch and stream slot. Events are read only after existing completion.
- Host observation of completion, correlated approximately with GPU completion.

Stage scopes overlap or nest. The analyzer merges intervals before computing
coverage and overlap, rather than adding inclusive totals. CUDA intervals can
include scheduling delays and work from other streams; they are not isolated
PCIe-transfer durations or hardware occupancy. See NVIDIA's
[CUDA event timing documentation](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__EVENT.html).
Native OptiX traversal is not instrumented here: a gap in shading does not mean
the entire GPU is idle.

## Clock correlation and perturbation

A diagnostic event at stream setup is bracketed by host timestamps. An end event
provides another bracket after flights retire. The analyzer maps GPU timestamps
linearly between those anchors, reports drift and bracket widths, and labels
cross-device overlap/detection times approximate. This is not equivalent to a
hardware profiler's clock correlation. GPU phase durations and host durations
should carry more weight than sub-millisecond cross-device comparisons.

The first diagnostic exposed millisecond-scale drift with a single anchor.
Its images/failure controls passed, but its uncorrected completion-detection
latencies must not be used. The v3 build requires both anchors for GPU analyses.
Setup/end event synchronization, extra event recording, timestamp calls and
buffer storage perturb execution. Repeated rotated rounds compare trace off/on,
plus frozen predecessor and original XPU. Trace-enabled time is not a speed claim.

## Reproduction

Build `tools/xpu2_native_timeline_build.py` with the primary checkout as read-only
`--source`, the frozen `xpu2-local-neighbor-build` as `--base`, and a fresh isolated
`--output`. Only the copied PathIntegratorUtil translation unit is rebuilt.
Build/link inputs and runtime identity are pinned. No installed runtime is changed.

`tools/xpu2_native_timeline_probe.py --checks` accepts a subset such as
`reference,control,profile_control,missing,upload_failure`. The `profile_control`
case traces the same FIFO four-chunk configuration as `control`. Without `--checks`,
the probe runs warmup plus rotated original/frozen/off/on comparisons. Every normal
image must match original float32 RGBA exactly. `tools/xpu2_native_timeline_cancel.py`
uses that baseline to check cancellation/replacement with tracing enabled.

Run `tools/test_xpu2_native_timeline.py` for interval and calibration contracts.
`tools/xpu2_native_timeline_analyze.py` rejects incomplete/dropped/duplicate traces.
`tools/xpu2_native_timeline_evidence.py` collects image, recovery and timing reports.
The persistent CSV holds the final frame; per-frame lifetime profiles remain the
source for canceled-frame cleanup evidence.

## Recorded results (2026-10-18)

`native-timeline-20261018.json` records 24 exact ordinary RGBA renders across
controls, warmup/repeated timing and persistent cancellation/replacement checks.
Missing PTX and injected upload failure still produce the exact CPU fallback image.
Nine interval/calibration tests pass. No trace buffer overflow or retained queue
credits occurred. Validation remains limited to one native render worker and the
reflection/transmission fixture; no new GPU shader family is added.

Three rotated rounds after warmup gave MCRT medians of 7.738 s for original XPU,
9.876 s for the frozen predecessor, 9.673 s for the new tracing-off candidate,
and 10.069 s with tracing. Tracing adds an observed 4.09%; it is not enabled by
default or proposed as a speed improvement. No competing MoonRay process was
reported before or after the timing renders; brief activity between checks is
not excluded. This is not production/multiworker performance qualification.

The untraced native Integration bucket increases from 2.51705 s in original XPU
to 4.29413 s in this candidate. Its 1.77708 s increase accounts for about 92% of
the 1.935 s total median gap. This identifies a region for deeper attribution,
not one proven root cause. Original XPU uses 32-ray native chunks and the candidate
uses 64, so that configuration difference is still part of the comparison.

The traced runs give median empty-shading-worker wait of 8.7685 s within a
10.2130 s queue/frame scope, versus 0.2882 s of native condition-variable wait
for shading results. Measured shading GPU intervals cover about 1.0713 s,
with negligible cross-slot kernel-interval overlap. These intervals include
stream scheduling delays. They do not measure total GPU utilization and omit
native intersection/occlusion work. Already-retired work can await native
consumption while the shading worker waits for more input.

Host dispatch takes about 0.6631 s; worker packing 0.0342 s and retirement
0.0737 s. Native window preparation covers 0.2732 s and native resume 0.6167 s,
including waits. These overlapping/nested figures must not be added to the
native Integration total. Copy/compute overlap and completion latency use
approximate two-anchor clock alignment; no sub-millisecond critical-path claim
is based solely on that mapping.

The evidence favors investigating CPU integration/replay/eligibility and supply
of independent GPU work before more neighbor-search or polling tuning. Moving
an entire useful supported integration block can amortize dispatch, but its
speed and parity must be measured, not assumed.

## Performance objective

The agreed success target is 30–40% lower complete render time than original XPU,
with 50% as the stretch target. For this 7.738 s baseline that means 4.643–5.417 s,
or 3.869 s for the stretch goal. XPU2 is currently slower; these are targets.
First recover the added integration cost, then qualify a smaller net offload gain
before expanding material/light coverage. Keep original XPU selectable and preserve
image comparison gates. Report scene loading separately from MCRT and retain
end-to-end timings; a kernel-only win is not a full-render win.
