# Indexed scene resources and Morton convergence checkpoints

The native scene index is implemented in `indexed_scene.h`. The diagnostic CUDA
queue can retain its immutable snapshots and shade copied packets prepared from
indexed material buffers. This is an isolated integration, **not a native MoonRay
SceneContext importer, installed XPU2 renderer, or measured scene-load speedup**.
The earlier `control.py` SceneIndex remains a separate metadata protocol model.

## Scene index

Each caller-supplied stable ID identifies geometry, an instance, material, texture,
light, environment, camera or volume. A kind lookup supports class-specific work
without assigning an entire kind permanently to a device. Inputs must use stable
host IDs, not list positions or mutable display names.

Entities hold separate topology, position, transform, shading, visibility, pixel
and parameter buffers. Edits provide only notified fields. Unchanged bytes reuse
their resource revision and prepared data; untouched buffers are shared across
scene snapshots. Dependency edges have a reverse index. A texture edit invalidates
its material and instance consumers without copying their unedited geometry.
Rebinding, removal, recreation and cycles are covered. Encoding and binding are
separate: a dependent entity's new revision tells the future adapter to refresh
its bindings even when its own byte buffers were reused.

`prepare(base, edits, removals, encoder)` validates and builds a candidate without
publishing it. The caller must acknowledge backend preparation before `commit`.
Failed encoding, missing references, budget failures, foreign candidates and stale
bases leave the active scene unchanged. A no-op returns the existing snapshot;
check revision/pointer equality before treating its historical `changes` as new.
The encoder contract is deterministic field-local preparation. Keep its encoding
rules fixed for an index's lifetime; changed formats/working spaces require a new
index, or explicit changed source fields. Dependency-sensitive native bindings
must be built by the adapter from `changes.affected`, not hidden in this callback.

Readers retain immutable snapshots while the coordinator publishes newer ones.
A material edit overlaps a deliberately delayed real CUDA job in the probe. The
old result is numerically checked, but cannot pass the current-scene publication
gate. Its snapshot survives until collection, then expires. New work reads the new
material data. Native stack pointers and CUDA handles are not stored in the index.
Exactly-once completion remains the queue/mailbox's responsibility.

Resource budgets cover logical source plus prepared bytes per snapshot, entity
count and dependency edges. They are **not process-wide peak-memory or VRAM caps**.
Multiple retained snapshots, candidates, encoding temporaries and map allocation
consume additional memory. Production integration needs bounded retained revisions
and upload/use fences. The existing `SceneLeaseGate` is the retention interface to
integrate; this new index does not replace it.

Reverse edges and byte/edge accounting update incrementally. Snapshot publication
still copies metadata maps/sets, so metadata work is O(scene size); large resource
buffers are shared. The 10,001-entity fixture is 10,000 small instances referring
to one 1 MiB synthetic geometry buffer. Moving one instance prepares one one-byte
test field and preserves that geometry allocation. The recorded timing is one
uncontrolled diagnostic, not representative Modo/native loading performance.

## Morton and convergence

`morton_schedule.py` builds Morton-ordered tiles (8x8 by default), clips edge tiles,
and issues disjoint, fixed pixel/sample ranges through the existing deterministic
Scheduler. Tile size, block size, eligible worker labels, retries and completion
order do not change sample identities or accumulated values in the checks.

`AdaptiveMortonSchedule` only exposes an immutable convergence checkpoint after
all work in its predetermined sample interval has retired. An external estimator
returns a subset of converged pixels. Those receive no further jobs; remaining
pixels advance to the next interval, with the final milestone enforcing the cap.
Weighted film sums and counts carry forward. Missing-resource work must remain
pending or retry with the same addresses, never complete using a placeholder.
A new render attempt invalidates old results and checkpoints.

This is a **scheduler/accumulation protocol model**, not a replacement adaptive
estimator. The tests use scripted convergence decisions. Native integration must
call MoonRay's estimator with its actual statistics, preserve sampler arguments,
and route reconstruction-filter contributions across tile boundaries. The model
has no reconstruction filter or native variance estimator. It does not certify
native adaptive RGB parity or make the GPU capable of full-path tile rendering.

## Validation

- 49 native C++ assertions: incremental reuse, classification, dependency changes,
  cycle handling, removals/recreation, atomic failures, budgets, foreign/stale
  publication, and 80,000 reads from eight threads across a scene update.
- Two real CUDA jobs, 16 accepted/replaced Lambert samples, zero shader errors or
  mismatches, changed material results, geometry reuse, and drained scene retention.
  This uses native-captured shader packets with synthetic indexed scene resources;
  it is **not an image render**.
- 355 XPU2 Python regression tests passed, including 12 new Morton/checkpoint tests.
- No installed renderer, Modo scene, shared checkout, native film path or shader
  kernel was changed. Previous native image timings/parity limits remain unchanged.

The compact record is `indexed-scene-20261017.json`. Full executables, preprocessed
sources, captures and logs remain under `test-results/xpu2-index-publish/`.

```powershell
python tools/xpu2_index_probe.py --source <read-only-toolchain-root> --output <new-directory> --ptx <validated-sampler.ptx>
python -m unittest discover -s tests -p "test_xpu2*.py"
```

The next integration is an owned host/native-scene adapter: feed actual stable
resources into this index, acknowledge bindings and accelerator updates, attach
bounded scene leases to production work, and compare full versus incremental
transforms/deformations/material edits. GPU residency/mip paging, BVH refit policy,
JIT geometry, native Morton dispatch, adaptive estimator integration and full
independent CPU/GPU path execution remain separate unfinished work.
