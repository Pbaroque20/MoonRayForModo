# Exclusive bridge-stage cost diagnostic

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The bridge-enabled frame now has exclusive host stages: nested scopes pause their
parent, and each thread's stage sum equals its covered time. GPU upload, kernel
and readback intervals are separate. This fixes double-counting within a thread;
it does not make concurrent threads additive frame time.

**The measurement is still perturbed.** With profiling off, this build averages
10.649 s MCRT against 7.658 s original XPU, a 2.991 s gap. The profiled frame takes
12.219 s: 1.570 s (14.7%) slower. Profiling also changes device ownership. Thus the
following numbers locate costs, but cannot precisely allocate the unprofiled
3-second gap or establish a production break-even threshold. Larger architecture
changes remain paused pending that distinction.

## One frame, exclusive host wall seconds

384 x 216 rough-diffuse/transmission fixture, fixed sampling, one native render
worker plus the sampler and light dispatch threads, RTX 3090 / driver 591.74.
All five control/profile images match original XPU exactly in float32 RGBA.

| Stage | Native worker | Sampler queue | Light queue |
| --- | ---: | ---: | ---: |
| Packing | 0.229719 | 0.101498 | 0.022200 |
| Upload API | 0 | 0.051503 | 0.049769 |
| Kernel launch API | 0 | 0.062615 | 0.063504 |
| Completion API | 0 | 0.112297 | 0.305325 |
| Readback API | 0 | 0.268682 | 0.153458 |
| Replay / validation | 0.337987 | 0.083186 | 0.005615 |
| Rejected-result fallback | 0.000156 | 0 | 0 |
| Queue / ownership coordination | 0.380679 | 0.679027 | 0.660696 |
| CUDA context switching | 0 | 0.415382 | 0 |
| Explicit waits / yields | 2.005788 | 10.394906 | 10.833172 |
| Marked native shading | 1.919237 | 0 | 0 |
| Setup / cleanup | 0 | 0.124519 | 0.146526 |
| Extra profiler GPU queries | 0 | 0.003803 | 0.005768 |
| Covered time | 4.873566 | 12.297416 | 12.246034 |

Only columns are exclusive partitions. Adding the columns would double-count
simultaneous work. Queue waits include idle time, not just time blocking useful
render work. Host API durations include scheduling and preemption; they are not
CPU-cycle measurements or the device transfer durations.

The native worker spends 0.948385 s in packing, validation and coordination plus
2.005788 s in explicit waits. That resembles the unprofiled gap numerically, but
is **not** a causal subtraction: it includes waits for useful GPU work, comes from
a perturbed run, and omits native work outside the marked functions. Rejected
fallback is negligible here; unsupported/native work belongs to native shading,
not that failure counter. Math auditing is off (zero sampler/light math checks);
replay/validation measures state consistency and result handling, not full CPU
recomputation of every GPU answer.

## GPU service intervals and cost per trip

CUDA event boundaries separate upload, kernel and readback within each trip.
Summed across four streams they are 0.715086 s upload, 1.585056 s kernel and
0.571282 s readback. Streams can overlap and these intervals include device
scheduling effects, so their sum is not frame elapsed time or pure hardware busy
time. Original XPU's OptiX intersection work is not counted as GPU shading.

- Sampling: 7,108 trips, 3,250,134 accepted lanes (about 457/trip). Queue plumbing
  is 250 microseconds/trip; GPU service is 282 microseconds/trip.
- Lighting: 3,106 trips, 43,665 used lanes (about 14/trip). Queue plumbing is
  406 microseconds/trip; GPU service is 280 microseconds/trip.
- Across both, including native admission/replay plumbing, the serialized model
  is 390 microseconds of host plumbing plus 281 microseconds of GPU service per
  trip, or **671 microseconds/trip**. It excludes native shading, explicit waits,
  setup, failure fallback and extra profiler query scopes. It still contains
  profiler perturbation and is not an asynchronous critical-path threshold.

The unprofiled controls average 7,672 trips. Dividing the measured 2.991 s elapsed
gap by that count gives **390 microseconds of additional net elapsed savings per
trip** to equal original XPU, assuming the count remains unchanged. This is a
planning scale, not the total CPU work each trip must replace. Actual break-even
also depends on overlap, dependency stalls and the CPU work already displaced.
No speedup or precise break-even qualification is claimed.

## Observer effect and remaining measurement work

Unprofiled controls take 10.604 and 10.694 s. The previous build without compiled
hooks takes 10.632 s. Profiling changes sampling trips only slightly (7,113 / 7,106
versus 7,108), but lighting trips rise from 486 / 639 to 3,106. GPU light lanes
rise from 9,871 / 12,568 to 43,665. Slowing the native producer changes which
worker wins claims. Do not normalize all stages by one elapsed-time correction:
that cannot undo different work ownership.

The first full steady-clock measurement added 16.5%. A calibrated invariant TSC
reduced this to 14.7%; its elapsed clock differs from steady time by 0.0069%, within
the 0.2% validity gate. Clock accuracy is not the same as low instrumentation
cost. The next profiling refinement should reduce native per-lobe hooks or use
sampled/external profiling, and verify both render time and ownership against
controls before using costs to resize GPU jobs. Merely increasing batches or
removing validation is not justified by this measurement.

## Implementation and validation

`native_exclusive_profile.py` patches isolated copied sources only. It adds
exclusive host scopes, driver API scopes, GPU event boundaries and balanced ISPC
entry/exit hooks. `native_exclusive.h` uses a calibrated invariant clock when
supported, otherwise steady time. It writes raw host, GPU and clock CSV files.

The analyzer rejects unfinished scopes, mismatched totals, duplicate stages,
unaccounted GPU trips and excessive clock drift. Seven negative/positive evidence
tests pass. The C++ accounting/clock contract passes normal and native fast-math
builds. All 10,214 profiled GPU trips are accounted for; no GPU errors, retained
records or image differences were observed. These are one-worker correctness
checks, not enabled multiworker qualification.

An earlier attempt rendered its profiled image but stopped at a positive-resident-
reuse gate. Rare reuse can legitimately be zero when profiling changes scheduling;
the profiling probe now allows that while retaining GPU-work, ownership and
lifetime checks. The ordinary resident regression keeps its positive-reuse gate.
Failed/perturbed reports are preserved. A later CSV file-handle cleanup reproduced
the captured analysis exactly without rerendering.

Reproduce with fresh output directories:

```text
python tools/xpu2_native_build.py --stage exclusive_profile --source <source> --base <reviewed-resident-build> --output <profile-build>
python tools/xpu2_exclusive_probe.py --build <profile-build> --previous <reviewed-resident-build> --reference <original-xpu-runtime> --scene <fixture.rdla> --ptx <resident-film.ptx> --light-ptx <direct-light.ptx> --output <frame-results>
python tools/xpu2_exclusive_contract.py
```

[Compact results and provenance](exclusive-profile-20261019.json).
Original XPU and the installed kit are unchanged. No merge or installation.
