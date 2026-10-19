# Resume sample-coordinate reuse

This isolated opt-in XPU2 experiment reuses random coordinates already produced
for the same material continuation. CPU-ahead samples retain them in
`BsdfSample.sample`; a GPU request retains them in its immutable input packet.
The original collector still validates and consumes each GPU result, and only
accepted lanes use the retained coordinates. Null/failed/canceled GPU results
regenerate samples through the native sampler.

The existing numeric/pixel byte comparisons, owner/epoch guards, native shader
state, GPU kernel, sample sequence and film order remain intact. No new device
transfer is needed: coordinates are copied from the host-owned request before
collection releases its ticket. CPU-ahead coordinates remain in native storage.

`XPU2_SAMPLE_REUSE=1` enables reuse in material resume. In lanes that reuse a
coordinate, the sampler index advances once, matching `getSample`'s sole sampler
mutation. Other lanes execute native `getSample`. Light-filter sequences remain
independent and unchanged. The separate unstaged/native drawing path is unchanged.

`XPU2_SAMPLE_REUSE=verify` regenerates native coordinates and compares their float
bit patterns against every would-be reuse, then uses the generated values. A
mismatch fails the experiment. `XPU2_SAMPLE_REUSE_PROFILE` records mode, CPU/GPU
lane counts, checked coordinates and mismatches. Counts describe sample pairs
for active lanes, not whole rays or complete materials. The default is off.

This removes repeated coordinate generation on resume. It does **not** remove
initial sampler construction, prefetch/replay packet preparation, or the CPU's
remaining light evaluation and integration. It does not expand GPU shading
coverage or install a new plugin runtime.

## Reproduction

Build using `tools/xpu2_native_sample_build.py` with the frozen timeline-v3 build
as `--base`, the read-only primary checkout as `--source`, and a fresh isolated
`--output`. The builder copies the actual linked frozen ISPC source, patches and
rebuilds the C++ adapter plus that ISPC object, and retains the other link inputs.
Source hashes, preprocessed artifacts and runtime inventories detect drift.

Use `tools/xpu2_native_sample_probe.py` with build, reference, previous-build,
PTX/previous-PTX, scene and a fresh output directory. `--checks` selects correctness
and fault-injection cases. `profile_four` enables bit verification; `four` enables
reuse; `control` disables it. `profile_control` is a profiled reuse correctness
case, not the switch-off timing control. Timing compares reference, previous,
control and four in rotated rounds, without detailed integration profiling.

`tools/xpu2_native_sample_cancel.py` checks cancellation and replacement from a
qualified controls report. It also exercises bounded neighbor selection; timing
uses FIFO. `tools/xpu2_native_sample_evidence.py` preserves report hashes and paired
render-stage results. Single-worker fixture validation must not be presented as
production/multiworker coverage or as an installed feature.

## Qualified result, 2026-10-18

Evidence: [native-sample-reuse-20261018.json](native-sample-reuse-20261018.json).
The controls, rough-material follow-up, adaptive bypass, cancellation/restart and
rotated timing reports passed. Across those reports, 35 ordinary renders matched
float32 RGBA exactly; one intentional GPU color sentinel changed the image.
Two verification renders checked 6,500,268 active-lane coordinate pairs with
zero bit mismatches. Missing-kernel, queue-capacity, upload-failure, input-mismatch
and discarded-prefetch controls retained their expected fallback behavior.
Cancellation retired owned work and the replacement image matched a fresh render.

Three measured rotated rounds after warmups gave median MCRT times of 7.871 s
for original XPU, 9.992 s for the previous XPU2 candidate, 9.878 s for this build
with reuse off, and 9.590 s with reuse on. The paired on-minus-off differences
were -0.288, -0.417 and -0.019 s. Median wall time was 11.180 s off versus
11.003 s on. No competing MoonRay process was observed before or after each
measured render; those checks cannot exclude brief intervening activity.

The median MCRT reduction is approximately 2.9% against the same-build off
control. This is a limited, promising result on one fixture and three timing
rounds, with overlapping timing ranges. It is not a demonstrated speedup over
original XPU, which remains faster, or a general production performance claim.
The experiment stays opt-in and does not change the installed runtime.

This index advance is specific to the inspected ISPC IntegratorSample2D, whose
getSample mutation is one sample-number increment. It must not be generalized
to the separate C++ sampler implementation with cached windows.

## Next performance boundary

Larger useful GPU tasks must replace more native CPU shading/integration while
retaining intermediates on the device. The CPU can then prepare independent
batches and render unsupported work concurrently. A requested 75% GPU / 25% CPU
contribution is a target to measure, not a fixed batch quota: batches have unequal
cost, and utilization alone does not establish a faster render. Keep bounded
queues, one owner per contribution, the original sample identities and safe
fallback boundaries. This experiment does not implement that broader GPU task.
