# Alternating device preferences and untouched-work stealing

This opt-in XPU2 experiment assigns supported direct-light work a stable CPU or
GPU preference using a 16x16-pixel checkerboard. `XPU2_LIGHT_TILES=alternate`
respects those preferences; `XPU2_LIGHT_TILES=steal` lets either device claim
pending work preferred for the other device. The default remains off.

## What is actually scheduled

The native integration boundary is one `drawLightSamples` call. A task contains
one light sample's lobe/lane inputs for one device preference. Its numeric packet
has at most 128 lanes; the admitted call has at most 16 samples and 512 combined
sample/lobe lanes, producing at most 32 tasks. Existing support restrictions
remain: one native worker, fixed sampling, empty AOVs and supported primary
Lambert/rough-diffuse light calculations. Unsupported shading stays native.

These are tasks selected by tile preference, not complete independently rendered
image tiles. Sampling, shadow rays, native clamping, unsupported BSDFs and film
publication retain their existing implementation. This does not add arbitrary
GPU material support or migrate active paths between devices.

## Ownership and result lifetime

The native owner packs immutable numeric inputs and publishes the whole window
under one queue mutex. Both devices use that mutex to claim an unstarted task.
The CPU tries its preferred tasks first and, in steal mode, pending GPU tasks.
The GPU fills a flight with GPU-preferred tasks before considering CPU-preferred
tasks. A GPU claim prevents CPU execution of that task; a CPU claim removes its
pending payload before returning queue credit. Claimed or completed work is never
stolen. CUDA buffers are not reusable until their flight completes or drains.

The GPU owns only copied numbers, never native scene or arena pointers. The CPU
can evaluate other disjoint sample/lane tasks while CUDA processes its claims.
The original native owner integrates returned GPU values and CPU results into
separate lane/sample slots before returning. Subsequent shadow/film consumption
and each lane's lobe summation order stay unchanged. Task device assignment may
vary with timing; sample identities and arithmetic do not depend on that race.
Exact-image checks are evidence for tested scenes, not a proof of general
multiworker bitwise repeatability.

The queue retains its 4096-lane credit limit and two 512-lane CUDA buffers. A
failed/refused submission returns to CPU evaluation. Cancellation drains GPU
ownership before the next frame can reuse state. The test-only CPU/GPU delays
exercise both steal directions; the held-flight marker exercises cancellation
while a submitted packet is pending. These delays are absent from timings.

## Reproduction and limits

Build with `tools/xpu2_native_light_tiles_build.py` using the frozen qualified
light-group-v2 build. `tools/xpu2_native_light_tiles_probe.py` checks reference
images, same-build policy controls, numerical verification, GPU-result sentinel,
both steal directions, capacity exhaustion and CUDA setup/upload failures.
`tools/xpu2_native_light_tiles_cancel.py` checks active cancellation and exact
same-process recovery. `tools/xpu2_native_light_tiles_evidence.py` rejects mixed
build identities and retains paired timing and image evidence.

The initial build used an ISPC-reserved identifier and failed compilation. The
v2 smoke run passed its controls, but its CPU-resolved packets remained in the
pending deque until the GPU worker next visited it. V3 removes those entries
before releasing credit to keep retained payload memory bounded even when the
GPU worker is delayed. Final qualification uses V3 exclusively.

Further speed work needs larger independent native shading groups, lower packing
and allocation costs, and a GPU eligibility policy that amortizes handoff costs.
This experiment does not guarantee a GPU contribution percentage. Original XPU
remains selectable and unchanged; this candidate does not update installed kits.

## Final V3 qualification (2026-10-18)

All retained qualification reports pass on RTX 3090 / driver 591.74 / AVX1 with
one native render worker. There are 34 non-reference ordinary image comparisons,
all exact float32 RGBA, plus ten reference rows and one deliberate GPU-light
sentinel. The sentinel changes 1,806 pixels. Four verification renders compare
62,574 accepted GPU contributions against native RGB, PDF and weighted RGB with
zero bit mismatches. This is fixture coverage, not exhaustive material coverage.

Both steal directions and exclusive claim accounting pass. Rough diffuse,
adaptive bypass, one/sixteen light samples, missing PTX, zero capacity and an
injected upload failure retain the exact reference image. Active cancellation
retires all 8,304 tasks: 8,300 resolved and four canceled. The replacement frame
is exact to fresh and reference images, with no retained credits or abandoned
owners. The diagnostic hold covers pending submission, not kernel preemption.

After warmup and three rotated rounds, median MCRT is 8.203 s original XPU,
27.611 s same-build all-GPU light offload, 22.739 s fixed alternation and
11.315 s alternation with stealing. Stealing ranges from 11.206 to 11.693 s.
Paired savings versus fixed alternation are 11.780, 11.313 and 11.046 s; paired
regressions versus original XPU are 2.775, 3.003 and 3.494 s. Thus stealing cuts
this experimental fixed-alternation time about in half but remains slower than
original XPU. The user's reduction target against XPU has not been achieved.
Median process time is 12.749 s for stealing versus 9.659 s original XPU.

The difference is mainly in native Integration: the median paired increase
versus original XPU is 2.953 s. These aggregate timings do not isolate packing,
allocation, mutex contention, kernel execution, transfer or context costs. No
competing MoonRay process was observed before/after timed renders; this does not
exclude other applications or brief intervening activity.

Each measured frame publishes 253,544 tasks across 45,170 windows. The CPU claims
250,962-251,849 tasks and the GPU 1,695-2,582; GPU steals of CPU-preferred tasks
number 129-152. GPU accepted contributions are 7,246-10,425 of 1,438,792 total
direct-light contributions. GPU flights/waits fall to 799-1,201 versus 45,170 in
the all-GPU control. These are direct-light counts, not the GPU's share of total
render work; GPU intersection processing remains active separately. The benefit
comes chiefly from avoiding small GPU handoffs, not from increased GPU shading.

A useful next ablation is same-build direct-light offload disabled, to distinguish
this policy's cost from prior XPU2 overhead. Then avoid allocating/copying GPU
packets for tasks that stay on CPU, using bounded local descriptors and payload
creation only for admitted GPU batches. Larger independently owned shading groups
are still required for the GPU to amortize its work. None of these proposed changes
is credited with the measured improvement above.

Evidence: [native-light-tile-claims-20261018.json](native-light-tile-claims-20261018.json).
