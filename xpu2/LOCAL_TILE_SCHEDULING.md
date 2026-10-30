# Neighbor-first tile scheduling experiment

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The native follow-up is documented in [native scheduling and render timing](NATIVE_TILE_SCHEDULING.md).

Status of the model below: **Python coordinator model only**. There is no native renderer or CUDA
execution in this experiment and no rendering speedup claim. The existing
region hierarchy is also a separate policy model; it does not explain the
blocking-transfer overhead of the current native shading candidate.

`local_tile_schedule.py` compares capability-filtered shared queues with local
tile queues. A worker tries its previous tile and eight neighbors, then falls
back to a shared queue. No whole-scene search or hierarchy traversal occurs per
claim. Capability/readiness decisions are immutable for this checkpoint. Jobs
with no eligible device remain pending and prevent a completed checkpoint.

A lock protects exclusive leases, retries revoke old leases, and duplicate,
forged or cancelled completions cannot publish. Keys are stable logical batch
identities. Results are returned in key order at a complete checkpoint; this
models publication, not floating-point native film reduction. Cancellation here
has no device allocations to drain. No native adaptive estimator is integrated.

Both policies also have an optional CPU-only priority queue. CPU workers first
claim jobs that the GPU cannot execute, then join shared work. This comparison
uses the same option in both baselines rather than giving local queues an
unmatched scheduling advantage.

## Checks and observations

Nine tests passed, including shuffled completion order, sparse/far fallback,
blocked work, retries, cancellation, malformed inputs and concurrent claims by
eight host threads. Seven synthetic workloads compare four policies, each with
2,048 identical batches. All 28 runs preserve the same keyed payloads. Worker
costs and transfer penalties are invented inputs; they are not measured GPU
performance. Raw results and source hashes: `local-tile-scheduling-20261018.json`.

- Mixed capability: unreserved local dispatch takes 1,632 synthetic cost units
  versus 1,372 shared, because GPU-eligible work can consume CPU attention and
  leave CPU-only work at the tail. CPU-only priority gives both policies 1,368.
- Irregular work with a tile-switch penalty: neighbor dispatch reduces switches
  from 735 to 502 and modeled completion cost from 29,261 to 28,816 units.
- Uniform work and uniform locality-sensitive work do not improve modeled
  completion. Irregular work without a locality penalty is slightly worse.
- Local queues generally inspect more entries and show greater Python claim
  overhead in this run. The shared Python lock does not model the contention
  benefit of separate native tile locks. Timing is not a statistical benchmark.

The result favors an optional locality policy with CPU-only priority and a
shared escape path, not unconditional neighbor dispatch. These finite static
checkpoints do not prove fairness under continuing work arrival, dynamic texture
availability, memory pressure or scene changes.

## Reproduce and next native gate

Run `python -m unittest discover -s tests -p test_xpu2_local_tile_schedule.py -v`
and `python tools/xpu2_local_tile_probe.py --output <new-directory>`.

Native integration must batch actual eligible shading jobs, retain revisioned
resources, publish exactly once, and measure CPU/GPU idle intervals, staging
bytes and renderer time. Priority must not change sample identities or adaptive
checkpoints. Before claiming repeatability, compare keyed native contributions
before film accumulation: deterministic reduction cannot repair differing inputs.
