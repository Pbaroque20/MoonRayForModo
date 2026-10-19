# Native coordination overhead experiment

Opt-in extension to owner-thread four-chunk preparation. Original XPU and the
installed kit are unchanged. Native chunk width is 64 rays, with two GPU flight
slots and original per-chunk integration order.

## Early rejection

`XPU2_COORDINATION=early` bypasses material staging for groups failing the existing
zero non-mirror-depth gate. This is MoonRay's non-mirror bounce count, not a
new classification of every reflection/refraction ray. The rejected path does not clear the large token/prepared arrays;
callers consume those arrays only when staging returns true. Existing shader
admission and CPU fallback remain authoritative. This changes preparation cost,
not GPU shader coverage or the sample sequence. Groups admitted by that gate retain
the existing per-lobe checks.

## Ready-only grouped collection

`XPU2_COORDINATION=claim` claims already-completed tickets while the material
resume operation holds its existing queue mutex. The same owner then copies each
result in native sample order without taking that mutex a second time. Pending
tickets retain the original wait, timeout and cancellation path. This never
waits for an entire material group to finish.

Claiming uses the existing owner, epoch, cancellation and duplicate-consumption
checks. Queue credit is released on successful claim; the owner's shared ticket
keeps immutable result storage alive until native consumption. The claim marker
is written and read only by that native owner. The worker finishes writing the
result before publishing completion under the mutex. Frame counters require
all claimed results to be consumed, including canceled results discarded by the
owner. GPU submission and film publication order are unchanged.

`XPU2_COORDINATION=both` enables both changes; absent or `off` retains control
behavior. The probe compares separate switches, both together, a same-build
four-chunk control, and the frozen earlier four-chunk runtime. The shared
control also evaluates the depth gate before querying material-stage mode; the
frozen prior runtime is retained to expose common refactoring costs or gains.
Profiled diagnostic
cases are separate from rotated timing rounds.

## Scope

This is CPU-side result consumption, not a new GPU completion-event scheme:
the GPU worker already retires batches together. It does not implement arbitrary
native-thread migration, full-material GPU shading, or unconstrained device tile
ownership. Neighbor-first selection remains a subsequent experiment. Stable
sample identities and original accumulation order remain required regardless of
where a queued numeric shading packet is executed.

## Reproduction

Build with `tools/xpu2_native_coordination_build.py`, using the frozen original
runtime manifest and a new output directory. Run
`tools/xpu2_native_coordination_probe.py --checks`, then rough-diffuse and adaptive
bypass fixtures. `tools/xpu2_native_coordination_cancel.py` checks frame replacement.
Run the probe without `--checks` for rotated timing rounds, with other rendering
and compilation idle. Do not infer transfer bandwidth or full copy/compute overlap
from host collection timers.

## Recorded results (2026-10-18)

`native-coordination-20261018.json` records 48 ordinary float32 RGBA images
exact to original XPU, with matching raw RGB/alpha hashes. Two GPU-color
sentinels change the rendered image. Controls include rough diffuse, adaptive
bypass, unavailable PTX, zero queue capacity, failed upload, mismatched replay
and dropped speculation. Persistent cancellation/replacement also passes: the
interrupted frame consumes all 792 claimed results and replacement consumes all
201,699, with no retained claims and an exact original/fresh image.

Three rotated rounds excluding warmup gave MCRT medians of 7.764 s for original
XPU, 9.918 s for the frozen prior four-chunk candidate, 9.836 s for the new
control, 10.455 s for early rejection alone, 9.962 s for grouped claiming alone,
and 9.666 s for both. The combined observed median is 1.73% below its control,
but ranges overlap (combined 9.610–9.850 s, control 9.780–10.592 s). This does
not establish a reliable/general speed gain. Both switches remain experimental
and off by default; neither independent switch is promoted. The combined path
is still 24.50% slower than original XPU in this comparison. The 7.6 s target
is not reached.

Combined runs claim a median 199,530 ready results without an additional
per-packet queue lock, while preserving the same 1,625,067 GPU shading lanes.
No queue-capacity fallback occurred. These operation counts demonstrate the
protocol is exercised; they do not prove that mutex cost dominated render time.
Fine-profile correctness runs overlapped installed-renderer activity and are
retained as diagnostic data only. The separate timing activity record contains
no competing MoonRay process. No GPU timeline claim is inferred from host timers.
