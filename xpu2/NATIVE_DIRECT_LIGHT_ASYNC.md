# Native asynchronous direct-light replacement

The qualified 32-word direct-light unit is connected to a bounded native queue.
This opt-in candidate publishes GPU-produced unshadowed light contributions into
the native LightSample, before native clamping, lobe accumulation, shadow queries
and film updates. Original XPU and the installed runtime are unchanged.

## Submission and ownership

Within one drawLightSamples invocation, eligible light/lobe calculations are
submitted while the CPU continues sampling lights. Each job owns its copied
numeric inputs, output storage, frame revision and submitting thread identity.
Two CUDA streams and pinned staging slots allow outstanding transfers/execution;
a completion event includes the result download. No arena or scene pointer crosses
the queue. Canceled numeric jobs may finish retiring after the native owner
returns; their own buffers remain alive until completion, without retaining
native scene or arena objects.

Inputs have 32 words per lane, outputs nine (eight values and explicit acceptance).
The original 24-word sampling transport is unchanged. Jobs are at most 128 lanes;
the queue retains at most 4096 lanes, including completed unconsumed results.
Each flight combines pending jobs up to 512 lanes. All credits retire once, after
both completion and consumption/cancellation. Native consumers validate owner,
revision and count and consume jobs in original light/lobe order.

A successful GPU result replaces BsdfLobe_eval and the PDF/weighted contribution
calculation. Refused, unsupported or failed work runs that native calculation.
There is no CPU duplicate for accepted results in normal mode. Verification mode
intentionally computes both and checks material RGB, PDF and weighted RGB bits.
Native sample validity checks, clamping, LPE pointers and contribution order remain
in place. The existing GPU sampler path also remains enabled in these comparisons.

The first integration is limited to primary, fixed-sample, empty-AOV work with
at most 16 light samples and 16 lobes per invocation. Supported Lambert and
FlatDiffuse admission retains the numerical-unit restrictions. Other work stays
native. This is not arbitrary-material GPU rendering or production qualification.

## Failure and recovery

Capacity refusal returns no job. Missing PTX or a CUDA failure disables further
admission for that frame. Submitted transfers drain in the queue's own private
CUDA context before buffers can be reused; native fallback then supplies results.
The native renderer's context is not synchronized or reset. An unrecoverable CUDA
drain/cleanup failure terminates the isolated process instead of reusing unsafe
memory. Native cancellation discards results but retains their buffers until the
worker has retired them. Frame teardown joins the worker and checks all credits.

`XPU2_DIRECT_LIGHT=1` enables replacement, `verify` enables numerical comparison,
and `sentinel` deliberately halves the GPU lighting output for image-route tests.
The default is off. `XPU2_LIGHT_PTX` identifies the qualified kernel;
`XPU2_LIGHT_PROFILE` records admission, collection, cancellation, credit retirement,
GPU/CPU contributions, native comparisons and peak outstanding flights.

Test controls include `XPU2_LIGHT_CAPACITY_ZERO`, `XPU2_LIGHT_FAIL_UPLOAD`, and a
missing PTX path. `XPU2_LIGHT_HOLD_FIRST` delays the first flight to exercise active
cancellation. These are diagnostic flags, not plugin UI options.

## Reproduction

Build tools/xpu2_native_light_async_build.py from the frozen direct-light capture
build. Supply the original sampling PTX plus the qualified direct-light PTX to
tools/xpu2_native_light_async_probe.py. Checks include native reference, same-build
off/on, numerical verification, a GPU-only color sentinel, missing kernel,
zero capacity and an injected failure after upload. Rough and adaptive-bypass
fixtures are separate runs. tools/xpu2_native_light_async_cancel.py requires an
actual canceled light job, exact fresh/replacement images and balanced frame
ownership. Timing uses warmup plus three rotated rounds; verification is off.

The previous-runtime timing label leaves sample reuse at its default off; the
same-build control and enabled case both enable sample reuse, isolating the
additional direct-light path. Scene preparation and total process time are
reported separately from MCRT.

## Remaining batching limitation

The native owner currently collects before returning from drawLightSamples.
That bounds lifetime safely, but also limits how much independent work can queue.
Two active streams prove outstanding jobs, not efficient GPU occupancy. Many small
dispatches can cost more than the removed AVX arithmetic. Wider batches across
owned light/shading continuations must preserve native accumulation order and
lifetime; simply delaying collection past an arena's lifetime is unsafe.

## Rendered validation (2026-10-18)

RTX 3090, driver 591.74, native AVX1, one native render worker. The base
reflection/transmission controls have seven exact float32 RGBA images and one
intentional GPU-light sentinel. The sentinel changes 45,504 pixels while the
existing GPU sampler stays unmodified, proving that this new light result reaches
the film. Rough diffuse adds three exact images; adaptive bypass adds two and
admits no direct-light jobs. Two native verification renders compare 2,877,584
accepted contributions with zero bit differences across material RGB, PDF and
weighted RGB. This does not establish arbitrary material or multiworker parity.

Missing PTX, zero queue capacity and failure immediately after upload all preserve
the exact reference image through native fallback. Every submitted job is retired,
with zero abandoned owners or retained credits. The completed supported frame
consumes 1,438,792 GPU direct-light contributions and zero native fallback
contributions within this unit; this is not a percentage of total rendering work.

Persistent recovery adds three exact images, including a canceled frame followed
by an exact replacement. The canceled frame admits 620,616 jobs, collects 620,612,
cancels four, and retires all 620,616. The replacement starts with no retained
credits and is exact to both the original reference and a fresh persistent render.
This validates pending-job retirement, not preemption of a running CUDA kernel.

An initial cancellation attempt did not exercise pending-light cancellation:
MoonRay ignores cancellation during its first sample-per-pixel pass. That report
is retained in test-results/xpu2-light-async-cancel and excluded from qualification.
The qualified trigger waits for 5% progress in a longer frame and still requires
at least one actually canceled direct-light job; it does not relax that gate.

Frozen build: test-results/xpu2-light-async-build. Qualified reports:
xpu2-light-async-first, xpu2-light-async-rough, xpu2-light-async-adaptive, and
xpu2-light-async-cancel-after-pass under test-results. The retained evidence
records report and build hashes. Original XPU remains available, and no installed
kit or user scene was changed.

## Paired timing result

Warmup plus three rotated rounds produced 16 exact float32 RGBA images, bringing
this phase to 31 ordinary exact images plus the intentional GPU-light sentinel.
No competing MoonRay process was observed before or after the timed renders;
these snapshots cannot exclude brief intervening activity.

Median MCRT: original XPU 7.971 s; frozen predecessor 9.800 s; same-build
light off 9.933 s; light on 26.914 s. On ranges from 24.543 to 27.742 s,
versus 9.888 to 10.365 s off. The three paired added costs are 16.981,
17.377 and 14.655 s: a clear regression, not acceleration. Median process time
is 28.362 s on versus 11.388 s off; loading/output are included there.

The median paired native Integration increase is 16.783 s, close to the
16.981 s paired MCRT increase. Every completed enabled frame admits 180,680
small jobs and consumes 1,438,792 valid GPU contributions; many tens of thousands
of launches and frequent waits remain. Two outstanding flights do not imply
high occupancy or a GPU-majority share of total rendering. These measurements
locate the regression in integration but do not isolate transfer, scheduling,
allocation, context contention and packing costs individually.

The safe next boundary is a larger group of owned light/shading continuations,
with copied input storage and native-order publication. The present per-call
collection boundary is retained as a correctness baseline, not enabled as a
performance improvement. No 30-40% speed target or 75% GPU contribution is claimed.

Evidence: [native-direct-light-async-20261018.json](native-direct-light-async-20261018.json).
