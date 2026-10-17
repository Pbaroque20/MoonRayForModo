# Native scene lifetime: delayed OptiX work and drains

Status: **tested inside the native renderer's persistent lifecycle**. This is an
isolated diagnostic build. It does not enable an installed XPU2 renderer or add
worker-produced contributions to the image.

The follow-up [dedicated queue validation](DEDICATED_QUEUE.md) adds an optional
independent slot for active-render work. The delayed-slot results below remain
the evidence for the preceding milestone.

## What is now connected

The build helper instruments copies of XPURayHandlers, RenderContext and
GeometryManager; shared primary sources and the installed kit remain untouched.
The first native GPU shadow batch in each frame is copied into independent
storage, including ray coordinates, bounds, time, mask, receiver and native light
identity. Its original visibility answers are retained as the reference.

A separate worker waits while the native renderer runs. After the native driver
stops, the drain releases that worker, which pushes the captured CUDA context,
performs actual OptiX visibility queries on the same live accelerator, checks the
answers, and pops its CUDA context. Only then may the caller proceed to post-frame
cleanup, scene update, accelerator rebuild or RenderContext destruction.

The worker uses the existing queue slot only after native workers stop; there is
no concurrent reuse of its buffers. This tests asynchronous work surviving its
originating handler, not GPU traversal overlap with active native workers. The
shared native scene remains borrowed, protected by draining at the tested
boundaries rather than by pretending its pointers are independent owners.

Hooks cover native frame start/stop, both updateScene overloads, updateGeometry,
accelerator rebuild and context teardown. The file-based updateScene path,
geometry rebuild, full context reload and teardown were executed. Binary updates
and direct updateGeometry calls have hooks but were not separately exercised.

## Rendered checks — 2026-10-17

Three persistent sessions each completed the initial scene, a mesh transform
update and a full reload: the retained reference runtime, the diagnostic build
with hooks disabled, and the build with hooks enabled. A fourth diagnostic session
was cancelled after capturing real native GPU work.

- All six control/probe-to-reference float32 RGBA comparisons matched exactly.
- The geometry delta changed **26,087 pixels**; full reload restored the initial
  image exactly. The update was not a no-op.
- The enabled completed session replayed **10,805 native shadow queries** across
  three frames, with two occluded queries and zero visibility disagreements.
- Cancellation replayed **3,607 queries**, including one occluded query, and drained
  before teardown. The session reported CANCELED, not DONE, and exited cleanly.
- Event ordering proved capture, drain request, worker completion and join all
  preceded post-frame cleanup. Three rebuilds, one scene update and two context
  teardowns occurred in the completed session.

Cancelled frames do not emit all completed-frame statistics. The first runner
incorrectly required those statistics and rejected the cancellation case. Its
separate cancellation gate now requires a clean process exit, the explicit
CANCELED event, no DONE event, one native renderer thread, GPU setup without
fallback/error, and successfully completed native OptiX replay. Completed renders
retain the original strict execution and image checks.

All **295 XPU2 regression tests passed**, including eight new native lifecycle
evidence checks.

## Limits and next integration

This test uses one native renderer thread, one RTX 3090, one pending diagnostic
batch per frame and a 20 ms delay before the replay. It is not a throughput test.
The borrowed scene cannot be mutated outside the guarded entry points while work
is pending. Multiple concurrent RenderContexts and independent queue slots are
not validated. This does not certify all native scene lifetime dependencies.

A ten-second drain deadline fails closed by aborting the disposable test process;
that path was not injected in this run and is not production recovery behavior.
The experimental owner-retention gate remains the foundation for a recoverable
production timeout. A user-facing integration must retain resources and surface
an error instead of continuing unsafe teardown.

Next, connect the owned GPU shading/light results to native visibility and
contribution acceptance. Overlap during active rendering requires a separately
owned accelerator queue slot or another serialized service; the current replay
must not be moved earlier using an active native worker's slot.

## Reproduce

Build with `tools/xpu2_native_drain_build.py --source <read-only-native-checkout>
--frozen-build test-results/xpu2-origin-build --output <new-build-folder>`.
Run `tools/xpu2_native_drain_probe.py --build <new-build-folder> --reference
test-results/xpu2-origin-build/control --output <new-results-folder>`.

The build uses frozen native link inputs and new preprocessed hook objects. It is
not a clean source rebuild or a distributable runtime. Aggregate evidence and
hashes are in `native-scene-drain-20261017.json`; captured scenes, images and binary
builds remain local under `test-results/xpu2-native-scene-drain-final` and
`test-results/xpu2-native-scene-drain-build`.
