# Bounded native material lookahead

This opt-in experiment extends the efficiency candidate without replacing XPU or
installing a kit. `XPU2_WINDOW_BLOCKS` selects zero (disabled), one (diagnostic), or
up to four native SIMD shading blocks. The CUDA shading PTX is unchanged.

## Lifetime and ordering

MoonRay already owns the shaded BSDF and ray-state blocks for a bundled integrator
call. The candidate prepares numeric GPU inputs for a bounded window of those
blocks, publishes them together, then lets the original integrator consume the
blocks in its original order. Native temporary sampler allocations are rewound
immediately after preparation. Only numeric inputs, pixel identities and owned
queue tickets survive preparation; no BSDF or arena pointer crosses the queue.

A normal sampling call regenerates its input and compares every input byte and
pixel identity before taking a prefetched ticket. A mismatch cancels that ticket
and uses normal dispatch. Native sampling sequences and film contribution order
are unchanged. This deliberately repeats sampler setup and input packing to
verify compatibility; it is not a claim of zero-overhead continuation restoration.

The scope stays on its native thread and frame revision. At the end of each window,
unused tickets are cancelled. The exported integrator wrapper also cleans up on
native cancellation returns. Nested native integration bypasses a new window.
Frame completion requires zero active scopes and published = reused + discarded.
The existing transport handles in-flight device retirement before buffer reuse.

A window holds at most four blocks and 32 packets per block; the existing queue
capacity remains independently bounded. The probes use capacity 64 and a 64-packet
batch limit. No timer waits for future paths: the bounded existing block window is
published immediately after its preparation. It has no hard wall-clock preparation
deadline. Zero capacity and overload keep the existing native fallback.

## Admission and limits

Speculation requires complete primary SIMD blocks, no volume hit or subsurface
mutation, full presence, and no early-termination mask. Existing GPU-family,
fixed-sampling, empty-AOV and first-nonmirror-bounce gates remain. Partial blocks,
unsupported lobes and changed inputs retain the original path.

This batches work across native SIMD material evaluations within one existing
bundle lifetime. It does not suspend arbitrary shaders beyond that lifetime,
migrate native arenas, implement a learned profitability threshold, or expand
GPU material coverage. All current image qualification uses one native render
worker; native multiworker repeatability remains a separate unresolved gate.

## Validation tools

- `tools/xpu2_native_window_build.py` copies and patches isolated native sources,
  including the bundled integrator, and links retained baseline objects.
- `tools/xpu2_native_window_probe.py` compares original XPU, disabled candidate,
  no-window control, one-block and four-block lookahead. It also checks the
  deliberate GPU-color sentinel, missing PTX, zero capacity, partial upload,
  forced input mismatch and explicit prefetched-ticket discard.
- `tools/xpu2_native_window_cancel.py` checks persistent cancellation and frame
  replacement with exact images and balanced window ownership.

All enabled probe paths use lean transfers, 16-microsecond event-query spacing,
CPU lobe work, and the same capacity/batch cap. The labels `control`, `transport`,
and `ahead` mean zero, one, and four window blocks respectively. Timing checks
record start/end times and reject detected competing render processes. These
checks do not measure all system load or prove continuous system idleness.

## Completed correctness checks

The eleven-case reflection/transmission matrix passes. Normal, disabled, fallback,
forced input-mismatch and explicit-discard images are exact float32 RGBA to
original XPU. The GPU-color sentinel differs as intended. A separate rough-diffuse
matrix also passes with an effective sentinel. Adaptive bypass (one-block option)
produces exact images and dispatches no prefetched work.

Persistent fresh and cancellation/replacement images match original XPU exactly;
the replacement also matches fresh rendering. Scope and ticket ownership balance
on both the cancelled and replacement frames. These checks cover 20 ordinary
images and two deliberate GPU-color sentinels, before the timing sweep.

The initial matrix stopped at the forced mismatch due to a harness assumption:
it required all submitted packets to be scheduler-selected. Cancellation can
correctly prune a packet before selection. The corrected check bounds unselected
packets by discarded tickets, alongside exact scope/publication accounting and
zero retained queue credits. The complete matrix was rerun and passed. The first
report is retained as an excluded harness attempt, not counted as a passing run.

On the four-block reflection/transmission check, all 203,013 prefetched tickets
are reused, without input mismatch or discard. GPU submissions fall from 22,585
to 5,709. Approximately three quarters of tickets are ready before native sampling
needs them. The 252 tickets outside prefetch coverage keep normal dispatch.
Readiness and waiting-event counts indicate improved overlap, not a direct
measurement of CPU blocked duration.

## Measured performance

Warmup plus three rotated rounds produce 16 additional exact float32 RGBA images.
No competing renderer was detected in per-render before/after snapshots or 47
periodic process snapshots. The resulting validation total is **36 ordinary exact
images and two intentional GPU-color sentinels**. Warmup is excluded from timing.

MCRT medians and ranges, in seconds:

- Original XPU: **7.632**, range 7.463-7.790.
- Same-build no-window control: **15.455**, range 13.606-15.515.
- One-block lookahead: **15.219**, range 15.068-15.427.
- Four-block lookahead: **11.783**, range 11.557-11.885.

Four blocks reduce median MCRT by **23.76%** against the same-build no-window
control, but remain **54.39% slower** than original XPU. All variants use the same
single-worker scene and sample settings. These are three measurements of one
fixture, not a general production performance claim.

Measured median GPU submissions fall from 22,585 to 5,710; completion queries fall
from 214,082 to 73,738. All variants consume the same 1,625,067 accepted GPU samples.
The four-block median has 151,947 of 203,265 tickets ready on native resume (74.75%)
and 5,703 collect-wait events instead of 22,584. It reaches two concurrent flights
in the measured median, which is a peak statistic, not sustained GPU occupancy.
Median submission instrumentation falls from 1.978 to 0.649 seconds. These counters
have overlapping scopes and do not constitute an additive frame-time breakdown.

This establishes useful batching across native material evaluations and reduces
handoff frequency. Arbitrary retained shader continuations, measured CPU/GPU
profitability admission, and more expensive fused GPU material operations remain
future work. The candidate stays disabled by default and is not installed.

Complete source/runtime identities, reports and excluded harness attempt:
[native-material-window-20261018.json](native-material-window-20261018.json).
