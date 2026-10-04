# 0.3.28 graph preview lifetime safeguards

Metallic 0.5 is a valid DwaBaseMaterial value. No parameter limits or metal shading were changed. The native runtime remains `runtime/xpu-compatibility-0327`, including 256px scheduling buckets.

The recurring user crash produced a Python stack during widget-geometry JSON decoding in material-preview capture and a native access violation in `shiboken2.cp39-win_amd64.dll` at offset 0x1463. The instruction region matches Qt wrapper traversal, not renderer shading. JSON decoding is where the failure surfaced; it is not established as the cause. The dump did not include the heap contents needed to identify the damaged wrapper. The exact crash has not been reproduced in isolation.

## Candidate corrections

- Temporary property editors no longer capture themselves in their own `destroyed` callbacks.
- Focus commits use a delegate-owned timer and a weak reference. Closing an editor cancels its pending callback and removes event filters before emitting commit/close signals or allowing Qt destruction. Late events from old editors are ignored; destroying an old editor cannot cancel a new editor's focus commit.
- Display conversion workers retain their Qt wrappers and image buffers until `QThread.wait(0)` confirms native thread exit. Receiving `finished` alone no longer causes immediate wrapper deletion. Waiting is polled without blocking the UI, and closing the preview stops the poll.

## Validation

All **156 host tests passed with zero skips/errors/failures** in isolated Modo 16.1v9. New regressions cover single commit and wrapper release, stale editor cleanup, and delayed native-thread termination. Existing conversion-shutdown checks also passed.

The final candidate passed 30 Metallic edits cycling through 0, 1 and 0.5 after the first XPU preview image arrived. Live preview stayed enabled, garbage collection was forced after each edit, the final 0.5 render completed, 10 image updates arrived and the isolated host shut down cleanly. The test used the actual `moonray.material.nodes` modal command and the installed geometry-adapter binary.

Baseline modal and node-rebuild scenarios also passed before the corrections. Consequently these results validate the candidate's behavior but **do not prove resolution of the user's intermittent crash**. Keep the crash diagnostics enabled and verify the original workflow after installing this version.

See [validation-0328.json](validation-0328.json). Reproduction scripts: `tools/probe_metallic_modal.py`, `tools/probe_metallic_rebuild.py`, `tools/probe_metallic_stress.py` and `tools/probe_metallic_active.py`; run only through the isolated launcher. They are local development scripts, not clean-machine certification.
