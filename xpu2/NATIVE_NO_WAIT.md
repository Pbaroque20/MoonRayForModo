# Opportunistic no-wait GPU shading

Step 1 is implemented as the experimental `XPU2_NO_WAIT=1` policy. Original XPU,
production defaults and the installed kit are unchanged. Explicit `0` disables
both the policy and its new held-flight test flag.

## Policy and lifetime

- Submission rejects work when all GPU flight slots are reserved. Pending groups
  are bounded by the remaining free-flight capacity, in addition to existing
  record and request limits. Reservation starts before packing/upload, not only
  after CUDA launch, so preparation cannot overbook the slots.
- A ready sampler result is consumed once. If it is still pending when native
  shading needs it, readiness and cancellation are decided under the same queue
  lock, and native shading runs immediately with the original sample sequence.
- The light collector follows the same rule. Undispatched canceled light jobs
  leave the pending queue immediately; in-flight jobs keep their storage and
  credits until GPU retirement. Late results are discarded, never also committed
  to the film.
- The native sampler/light collectors do not wait on completion condition
  variables in this mode. Short mutex acquisitions, allocation, original XPU
  intersection synchronization and final GPU cleanup remain. This is not a
  lock-free implementation or a promise of zero total rendering overhead.

The native queue reports busy refusals, late CPU takeovers and retained flight
state. Accepted GPU kernel lanes and GPU results actually consumed by native
shading are separate quantities: a late kernel can finish successfully yet
contribute nothing after CPU takeover.

## Validation

The admission contract checks free-flight bounds and explicit zero flags. Native
checks compare float32 RGBA with original XPU, exercising normal mode, the disabled
control, zero flags, held sampler/light flights, missing PTX, upload failures on
both queues, stale resident records, exhausted prepared storage and an intentional
GPU sentinel. Cancellation occurs while a sampler flight is reserved; its
replacement is compared with fresh and original images. Each completed frame must
retire all tickets, credits, descriptors, native chunks and resident transactions.
Actual consumed GPU samples are required in normal and replacement renders.

Measurements use one native worker and fixed sampling on the existing 384 x 216
diffuse/transmission fixture. This does not qualify enabled multiworker rendering,
adaptive sampling or arbitrary material coverage.

## Measured result (2026-10-19)

[Machine-readable evidence](no-wait-20261019.json) records all runs, configuration,
source/runtime hashes, lifecycle counters and the original report hashes.

With profiling disabled, one warmup plus three rotated measured rounds gave these
MCRT medians and ranges:

- Original XPU: **7.778 s** (7.741–8.202).
- Previous reviewed bridge: **11.236 s** (10.977–17.172).
- Same candidate with waiting enabled: **11.407 s** (10.938–12.269).
- Same candidate with no-wait enabled: **9.995 s** (9.845–10.056).

No-wait saves **1.412 s / 12.4%** relative to the same-build control medians.
Paired candidate-minus-control differences are **-2.424, -0.943, -1.351 s**.
The 17.172-second previous-build outlier is retained, not excluded. These are a
small local sample, not a confidence interval or a full-thread performance claim.
No-wait remains **2.217 s / 28.5% slower than original XPU** by these medians.
It closes only part of the gap; it does not establish near-zero bridge overhead.

All final-build runs passed: 12 correctness/fault cases, three cancellation
session cases and 16 timing renders. Thirty images (including reference/control
renders) match original XPU exactly in float32 RGBA. The deliberate GPU sentinel
changes 37,760 pixels. Held-flight cancellation/replacement, both queue upload
failures, missing kernels, stale records, exhausted storage and zero flags pass;
all checked resources retire. The admission contract passes in an optimized
native build.

Both native collector wait counts are zero in every no-wait measured frame.
However, GPU work can finish after CPU takeover. In the first measured no-wait
frame the sampler accepts 1,811,917 kernel lanes but native shading consumes only
1,045,168 lanes; 114,884 submitted packets take late CPU fallback. The light queue
consumes **zero** GPU results in that frame despite 332 completed batches. This
is direct evidence for the next queue-stage work: provide useful native work
between submission and consumption, while preserving bounded ownership. Merely
submitting more work can increase wasted GPU trips.

## Next queue-stage work

The remaining deferred-path code is not a ready-made arbitrary material stage.
Its `gpuEnabled()` gate is still false, the current candidate's deferred-path
capture counters are zero, and its restore adapter has explicit supported-state
restrictions. The active bridge operates through owned material windows instead.
A GPU completion must publish to the native owner's mailbox; it cannot call
`addRayQueueEntries` on another thread's arena or pool directly.

The next stage must preserve sample identities, path/arena lifetime, bounded
in-flight ownership, cancellation epochs and single film commitment while the
native worker runs other queues. Stable sample IDs alone do not guarantee bitwise
multiworker accumulation. Film ordering and statistical/reference gates remain
separate requirements.

The earlier 671 microseconds/trip number was an instrumented serialized cost
model, not submit-to-ready latency. Lookahead sizing must use measured queue
latency and throughput. Context pinning and completion notification can be tested
separately; CUDA visibility/ordering and teardown still need synchronization.
Several GPU bounces and scene-wide residency remain later work.

## Reproduction

Use fresh output directories:

```text
python tools/xpu2_native_build.py --stage no_wait --source <primary-source> --base <reviewed-resident-build> --output <candidate-build>
python tools/xpu2_no_wait_probe.py --build <candidate-build> --previous <reviewed-resident-build> --reference <original-xpu-runtime> --scene <fixture.rdla> --ptx <resident-film.ptx> --light-ptx <direct-light.ptx> --output <results> --mode checks
```

Use `--mode cancel` for held-flight cancellation/replacement and `--mode timing`
for a warmup plus three rotated comparison rounds. Timing removes exclusive,
integration and timeline tracing and request-by-request queue logs; lifecycle
counters remain on both bridge controls. The probe refuses competing renderers.
No installation or merge is part of this experiment.
