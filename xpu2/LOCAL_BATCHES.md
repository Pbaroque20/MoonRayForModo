# Local coordination and larger GPU batches

Standalone stage test; **not a native path scheduler or a rendering-speed claim**.
The installed renderer and original XPU remain unchanged.

## Implementation

A coordinator assigns disjoint numeric sample ranges through one atomic counter.
Persistent workers claim a chunk, compute it locally, and retain that range until
completion. There is no per-ray cross-device handshake. Six CPU workers can claim
512 samples at once instead of eight, while still invoking original AVX8 Lambert
sampling. A dedicated GPU worker packs owned numeric inputs and invokes a bulk
CUDA endpoint directly, without allocating one queue ticket per eight samples.

The isolated endpoint has bounded capacity for 16,384 samples, persistent pinned
transfer buffers and heap scratch for audit results. Its allocation sizes and
input guard increase together through strict patch anchors. The native queue's
production/default capacity is not changed. CUDA resources are explicitly closed
on the GPU worker before its pool is destroyed.

A claimed range cannot be reassigned while in flight. After timing, completion
ranges are sorted and checked for exact contiguous coverage, without overlaps or
holes, and every output is compared against the captured native reference. This
models ownership of independent shading jobs, not native path continuation,
scene revisions, adaptive sampling, or cancellation during a render.

## Experiment

Each measured run processes the same 262,144 samples. Inputs replay the existing
native Lambert capture; each eight-lane packet replicates a captured record so
its reflection mode is uniform. These are real native CPU and CUDA calculations,
but a narrow fixture without general materials or lane divergence.

CPU chunk sizes: 8 and 512 samples. GPU batch sizes: 128, 512, 2,048, 8,192 and
16,384 samples. CPU pools: one and six workers. CPU-only and shared runs cover
both pool sizes; GPU-only controls use the same six-worker pool with CPU workers
inactive. Three rotated repetitions produce 87 runs. Warmup/initialization and
post-run comparisons are excluded from wall time. Packing, transfer, full GPU
input echo and numerical audit, allocation of per-run GPU packing scratch, and
local scheduling are included. This is one in-flight GPU batch, not multiple
streams or a saturated GPU shading architecture.

All 87 runs passed exact output checks for direction, RGB, PDF and validity;
canonical hashes matched across every workload and schedule. Each run covered
its complete sample range once. Counters confirm 5,069,120 actual GPU samples
accepted/replaced across 8,848 batches, including warmup, with no unsupported
samples, invalid results, mismatches or hidden fallback. Resources were released.

## Measured result

On the i7-4930K / RTX 3090, six-worker CPU-only medians were:

- Claim eight samples at a time: **2.2375 ms**.
- Claim 512 samples at a time: **1.1880 ms**.

Central claim operations fell from 32,768 to 512. This is approximately 1.88x
faster for this standalone CPU stage workload. It does not establish that a
complete renderer becomes 1.88x faster.

GPU-only medians for the same 262,144 samples were 383.0263, 110.0535, 44.6177,
30.9219 and 28.9260 ms at batch sizes 128, 512, 2,048, 8,192 and 16,384. Larger
batches reduce transfers/launches from 2,048 to 16, improving this audited endpoint
by approximately 13.24x. It remains much slower than the CPU for cheap Lambert
work. The GPU path still performs substantial host-side packing and correctness
auditing; these measurements are not pure GPU arithmetic throughput.

With six CPU workers claiming 512 samples, shared medians were 1.3968, 1.4570,
1.4653, 1.5741 and 2.7531 ms for those GPU sizes. All are slower than the 1.1880 ms
CPU-only control. The largest GPU claim can extend the final tail even while the
CPU completes its share. One-thread comparisons sometimes overlap in timing;
three repeats do not establish a small reliable speed advantage.

## Next boundary

Local chunk claiming is worthwhile; forcing GPU utilization is not. Before
production integration, give the GPU a larger supported sequence of useful work
per transfer and choose GPU admission from measured completion cost, including
the remaining tail. CPU-only execution must remain available for work that is
cheaper locally. General GPU shading, whole-path ownership and accumulation,
texture residency and faster scene loading remain separate unfinished work.

`local-batches-20261017.json` contains all timings, source/compiler/native-object/
PTX/device hashes and aggregate counters. Local build and logs are under
`test-results/xpu2-local-batches`. No new scene-derived binary is published.

Reproduce with `tools/xpu2_local_batches_probe.py`, passing `--source`, `--native`,
`--runtime`, `--capture`, `--ptx` and a new `--output` directory, as for the
alternating-worker experiment. The script refuses output inside the shared
source checkout and rejects source/device drift or incomplete evidence.

All 253 XPU2 regression tests pass, including eight new tests for bulk capacity, patch drift and invalid measurement evidence.
