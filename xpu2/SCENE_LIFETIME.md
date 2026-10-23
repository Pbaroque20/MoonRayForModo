# Scene lifetime gate with retained GPU jobs

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Status: **owned-resource lifetime prototype validated with real CUDA work**.
Native MoonRay scene/accelerator ownership is not yet integrated. No selectable
renderer, installation change or performance improvement is delivered here.

## Implemented

`SceneLeaseGate<Resource>` retains immutable, uniquely owned resources in bounded
scene snapshots. The coordinator publishes a newer revision/render attempt;
workers read batch-scoped leases. A new scene or a same-scene restart invalidates
old results without invalidating the old resource while a worker still uses it.

The diagnostic GPU queue now accepts an optional retained-resource owner on each
asynchronous request. It keeps that owner through an in-flight cancellation and
a timed-out stop. Ownership is released only on completion/collection, confirmed
cancellation before dispatch, or acknowledgement of late cancelled work. Thus
dropping the caller's copy cannot free a scene still held by a GPU job.

Retired snapshots are destroyed by the coordinator after the last lease is
returned. The registry's strong reference prevents a worker from triggering
native-resource destruction on its own thread. Publication applies backpressure
when the retained-scene limit would be exceeded; the caller keeps its candidate
and the current scene remains usable. This is a snapshot-count limit, not a byte
budget; candidate resources allocated by the caller are outside that count.

`current(lease)` checks scene and render-attempt validity, not exactly-once sample
acceptance. Native integration must combine it with the continuation/request gate
before film publication, on the coordinator without an intervening scene change.
All registry operations are coordinator-only. Read-only leases may cross threads.
A Resource must own its dependencies: wrapping borrowed native pointers does not
make their lifetime safe or prevent other owners from mutating them.

## Checks completed — 2026-10-17

Four scenarios ran three times each with real CUDA work and the established native
Lambert capture. Scene resources and light IDs were synthetic owned values:

- Replace a scene while a GPU batch is delayed. Old bindings remain readable,
  old results cannot publish, and 100 attempts to exceed the retention limit
  preserve the current scene and caller-owned candidate.
- Restart a render without changing its scene. Old attempt results are rejected;
  the new attempt retains access to the same immutable snapshot.
- Cancel, close and drop the caller's lease while the GPU job is delayed. A forced
  stop timeout retains the scene; the job releases it only after worker shutdown.
- Close while eight reader threads perform 80,000 immutable reads. Off-thread
  registry calls are rejected and final destruction occurs on the coordinator.

All twelve runs completed, all 96 GPU sample results passed the existing native
comparison and sentinel-output checks, no job resource remained retained, and
no resource was destroyed on a worker thread. The artificial delay occurs before
GPU dispatch after worker ownership; this is not a device-hang recovery test.

Six existing continuation scenarios passed, including missing-PTX fallback and
bounded capacity. The full suite initially caught a changed submit signature in
the optional window-dispatch builder. That builder now preserves its existing
held-window argument and accepts resource ownership as an additional argument.
All **287 Python regression tests** and **19 compiled dispatch/transfer guards**
then passed. These are queue/protocol checks, not new rendered-scene comparisons.

## Remaining native integration

Native source inspection confirms that FrameState borrows `mGPUAccel`, while
GeometryManager owns it through a unique pointer and resets it during accelerator
rebuild. RenderContext currently stops rendering before geometry updates. A
copied FrameState or a light-binding table cannot independently extend this
ownership graph.

The next integration must drain or retain every external XPU2 job before native
scene mutation, accelerator reset, post-frame cleanup and teardown. Start with a
bounded drain at those boundaries; concurrent scene versions require ownership
of all referenced geometry, lights and shaders, not only the accelerator pointer.
Cancellation acknowledgement alone is insufficient. Preserve native GPU shadow
visibility for XPU parity, given the previously measured CPU/GPU disagreement.

## Reproduce

Run `tools/xpu2_scene_lease_probe.py --source <read-only-native-checkout>
--ptx test-results/xpu2-ray-image-final/sampler.ptx --output <new-isolated-folder>`.
The script builds the test executable and runs the twelve cases with timeouts,
source/device hashes, GPU execution checks and cleanup validation.

Aggregate evidence is in `scene-lease-20261017.json`. Local captures, logs and
executables are under `test-results/xpu2-scene-lease-final`; no new captured binary
assets or runtime builds are published.
