# Native integration profiling and completion waits

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Experimental work on PR #130. Original XPU and the installed kit are unchanged.
The objective remains lower total render time with identical native samples and
float32 RGBA. These experiments do not establish that objective yet.

## What changed

`native_integration_profile.py` derives the isolated eight-block/64-ray candidate
and instruments preparation, submission, CPU lobe work, result collection and
publication. Timers are off by default. Phase totals are **inclusive and nested**:
window preparation includes record submission; resumption includes collection.
They cannot be summed into a frame budget or treated as pure CPU execution time.

`XPU2_VECTOR_PACK=1` replaces lane-by-lane input stores with varying ISPC stores.
`XPU2_VECTOR_PACK_VERIFY=1` also executes the original stores and compares every
byte of every packet, including inactive lanes. It preserves native sampling,
wire format and replay validation. All 406,278 packets in the main fixture
matched. The first timing/profile pair showed little benefit; it stays disabled.

`native_collect_profile.py` adds opt-in `XPU2_COLLECT_SPIN_US=64` or `256`.
The owning CPU worker first tries collection, then briefly polls with processor
pause instructions before using the existing condition-variable wait. Each
poll retains queue ownership/revision validation. Cancellation, ten-second
pending timeout, fallback results and ticket lifetime remain checked. It also
aggregates per-packet lane statistics and avoids constructing a deadline for
already-ready results. The unchanged control remains available with the flag
absent or zero. Busy waiting consumes CPU resources; multiworker scaling is not
qualified by this one-worker experiment.

## Why this experiment

On the first isolated fine-profile pair, collection occupied about 1.43 seconds,
while window preparation occupied about 0.19 seconds. Submission, GPU execution,
transfers and collection overlap; collection includes waiting, not only copying.
Lane-parallel packing did not materially change those measurements.

The GPU currently receives small diffuse-sampling jobs. About 5,600 submissions
are issued for the main fixture. Two outstanding batches are possible, but the
producer often provides only a small second batch, and the native worker must
consume its answers before advancing. More frequent completion checks cannot
create more independent work. Larger useful submissions, with safe native
continuations, remain a stronger hypothesis than additional polling.

## Reproduction

Use `tools/xpu2_native_integration_build.py` for packing/profile diagnostics and
`tools/xpu2_native_collect_build.py` for the bounded-completion candidate. Both
require the retained original runtime/link manifest, a source checkout and a
new isolated output directory. Neither modifies the source checkout or kit.

`tools/xpu2_native_integration_probe.py --checks` validates packing, strict images
and injected failures. `tools/xpu2_native_collect_probe.py --checks` validates
64/256-microsecond waits and the same failure controls. Use a rough-transmission
fixture with `--cases reference,spin64,spin256,sentinel`, and the adaptive fixture
with `--bypass`. Every ordinary image must match original XPU exactly; the GPU
color sentinel must intentionally differ.

`tools/xpu2_native_collect_cancel.py --spin-us 64` (or `256`) interrupts a live
persistent render and checks replacement output against fresh and original XPU
renders. `tools/xpu2_native_collect_probe.py --repeats 3` runs a discarded warmup
and three rotated rounds of original XPU, frozen previous candidate, same-build
control, and both wait budgets. Fine phase profiling is disabled during timing.

`tools/xpu2_native_integration_evidence.py` verifies dated reports, raw RGB/alpha
hashes and periodic renderer-process monitoring, then writes the evidence JSON.
These tests cover a single native render worker on the local AVX1 CPU/RTX3090;
full material coverage, multiworker repeatability and production speed remain
open. Periodic process monitoring cannot exclude all unrelated system load.

## Recorded result — 2026-10-18

All **59 ordinary images** match original XPU float32 RGBA and raw RGB/alpha
file hashes exactly. Three deliberate GPU-color sentinels differ. Both wait
budgets pass persistent cancellation/replacement; rough diffuse, adaptive bypass,
missing PTX, zero capacity, partial upload failure, replay mismatch and discard
controls pass. The packing diagnostic compares all 406,278 main-fixture packets.

Three rotated timing rounds after discarded warmups give median MCRT times:
original XPU **8.105 s**, frozen preceding candidate **11.404 s**, same-build
control **11.358 s**, 64-us wait **11.351 s**, and 256-us wait **11.613 s**.
The 64-us change is only **0.062%** with overlapping ranges; no speed gain is
established. The 256-us change is **2.25% slower** than the same-build control.
Both remain disabled. The historical 7.6-second target is not reached; original
XPU was itself slower in this run, so comparisons use the paired reference.

The 64-us candidate still makes about 5,631 submissions and avoids sleep only
about 27 times per measured frame (median). The 256-us candidate avoids more
sleeps, but spends more time polling without improving frame time. Two batches
remain outstanding at peak and all runs replace the same 1,625,067 GPU lanes.
This supports investigating more independent useful work per handoff, rather
than harder polling. It does not prove which larger continuation design will win.

Evidence: [native-integration-20261018.json](native-integration-20261018.json).
