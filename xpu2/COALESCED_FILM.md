# Coalescing live contribution jobs across native workers

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Status: **opt-in queue validated on a restricted fixture; native XPU remains faster**.
The larger multithread fixture is blocked by native-reference repeatability.
No installed kit or engine selector changes.

## Ownership and scheduling

With `XPU2_FILM_COALESCE=1`, each fused call copies its numeric inputs, native
reference values and masks into a job. A dedicated CPU submission thread combines
already waiting jobs into one GPU dispatch, then scatters the results back to
their owners. No artificial batching delay is added. Admission is bounded to 16
outstanding jobs; one job has at most 16 eight-lane slots, and one GPU batch has
at most 128 slots (1,024 sample lanes). Full/closing admission returns to CPU
contributions. Completion wakes the original caller once, and close drains
admitted jobs and joins the submission thread before CUDA teardown.

The kernel uses a global thread index and multiple blocks for larger batches.
Persistent staging avoids a large native-stack array. All jobs contain owned
numbers, not BSDF/scene/arena pointers. Original native workers retain their
stack and TLS while waiting; other workers can prepare and submit independent
work during GPU service. This is cross-worker coalescing, not migration of live
paths, a fully nonblocking native scheduler, or proof of simultaneous CPU/GPU
hardware arithmetic. A caller still waits before continuing its own path.

## Correctness issue exposed and fixed

The first 16-producer GPU guard failed: some accepted results belonged to other
jobs. Large uploads exposed a missing dependency in the experimental blocking
path. A pageable host-to-device copy can return after host staging while the DMA
is unfinished; a nonblocking kernel stream does not provide the required default
stream dependency. See [NVIDIA's API synchronization rules](https://docs.nvidia.com/cuda/archive/13.2.1/cuda-driver-api/api-sync-behavior.html).

The blocking path now explicitly waits for the upload's default stream before
launching its kernel. The pinned same-stream paths already sequence their upload
and kernel. The unchanged failing workload passes after this correction. Earlier
candidate timings are not used below; all accepted measurements use the corrected
build. This corrects the experimental bridge; no installed runtime was replaced.

## Corrected-build validation — 2026-10-17

Seventeen native renders ran on the i7-4930K / RTX 3090:

- Ten one-worker runs: both references and all seven ordinary/control/fallback
  comparisons match linear RGBA exactly. The sentinel changes 23,346 pixels.
  Missing PTX and deliberately corrupted shader references accept no GPU results
  and reproduce the native image through CPU fallback.
- Seven four-worker runs on the small fixture: peak RGBA error is
  **1.4901161193847656e-8**, both for native repeats and candidate comparisons.
  These pass the predeclared 1e-6 absolute/relative bound, but are **not bitwise
  equal**. Native repeats differ at 10 pixels; the two coalesced runs at 17 and 16.
  Every normal candidate accepts exactly 210,001 supported contributions.
- Native audit runs retain CPU contribution arithmetic and reject any unequal
  GPU contribution. Normal runs have zero shader/contribution mismatches, device
  errors or cleanup errors. The small four-worker case checks real rendering,
  not merely copied-data replay.

The concurrent CUDA guard submits 128 jobs from 16 producers, including unequal
colors, partial masks and deliberate unsupported/corrupt shader lanes. It reaches
128 slots per dispatch, validates 4,096 accepted fused results plus 512 plain
controls, rejects 2,048 deliberate mismatches and 4,096 unsupported results,
preserves canaries and returns all jobs with zero device/cleanup errors. Existing
pinned-stream and graph-replay guards also pass on the corrected build.

The standalone C++ queue contract checks aggregation, ordered result routing,
bounded admission, overflow fallback, close with admitted work, repeated close,
repeat-job rejection, invalid counts and callback-exception fallback. All **343**
XPU2 regression tests pass, including seven new queue-evidence checks.

## Measured cost

Same corrected binary, small fixture, four renderer workers:

- Native XPU: **0.182 / 0.129 seconds**.
- Blocking fused dispatch: **0.634 / 0.681 seconds**.
- Coalesced fused dispatch: **0.467 / 0.481 seconds**.
- Coalesced audit: **0.514 seconds**.

Coalescing reduces measured render time by about **26–29% versus the experimental
blocking path**, with equal completed contribution counts. GPU dispatches fall
from 2,919 to **1,572 / 1,668**. Batches combine at most three native requests
(27 slots); 2,797 / 2,802 requests arrive during GPU service. These counters show
host-side interleaving, not a GPU utilization percentage. Native XPU is still
roughly 2.6–3.7 times faster than the coalesced candidate.

One-worker coalescing has no requests to combine and is slower: **1.224 / 1.223
seconds**, versus blocking **0.946 / 0.937**, and native **0.356 / 0.386**.
The queue stays opt-in. Short sequential timings with uncontrolled cache warmth
and system load are diagnostic evidence, not a production benchmark.

## Larger-scene blocker and limits

Before the corrected build, the larger four-worker sphere/ground fixture stopped
at its native-reference gate, before any candidate executed. Two untouched XPU
renders differ at 22,269 pixels; 271 RGB values per channel exceed the declared
bound, with maximum red error **0.062443673610687256**. This is much larger than
the small fixture's rounding differences. The failure is retained in the evidence;
no tolerance was increased and no larger-scene parity or speedup is claimed.

Resolve that reference instability before using the larger multithread fixture
to certify this architecture. General materials, native path continuation,
device loss, production cancellation/recovery, persistent scene revisions,
texture residency and scene-loading improvements remain unvalidated here.

## Reproduce

Build with `tools/xpu2_film_build.py --source <read-only-native-checkout> --base
<retained-base> --output <fresh-build> --fused`. The retained base is
`test-results/xpu2-owned-contribution-build-v2`.

Run `tools/xpu2_coalesced_film_probe.py` with `--build`, `--base`, `--output` and
`--faults` for exact one-worker checks; use `--threads 4` for the small concurrent
fixture. `--showcase` selects the currently blocked larger fixture. The runner
stops on image-bound failure and records exact comparisons separately.

Run `tools/xpu2_coalesced_guard_probe.py --build <candidate> --output <fresh>`
for the 16-producer CUDA check. Build `xpu2/film_batch_queue_test.cc` with the
retained GCC toolchain, C++17, `-mavx -mno-avx2 -mno-fma -ffp-contract=off`, then
run the executable for the queue contract. The existing fused guard probe accepts
`--streamed` and `--streamed --graphs` for transfer-path regression checks.

Final local folders under `test-results` are `xpu2-film-coalesced-build-v2`,
`xpu2-film-coalesced-one-v2`, `xpu2-film-coalesced-four-small-v2`,
`xpu2-film-coalesced-guards-v2`, `xpu2-film-coalesced-stream-guards` and
`xpu2-film-coalesced-graph-guards`. This links retained native objects rather than
providing a clean-source distributable runtime. [Aggregate evidence](coalesced-film-20261017.json)
contains hashes and counters; binaries, numeric captures and rendered assets stay
local. No merge, installation or release was performed.
