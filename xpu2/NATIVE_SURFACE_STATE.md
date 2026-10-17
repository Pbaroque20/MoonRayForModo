# Native numeric surface-state capture

The next continuation prerequisite now uses real native scene data. An isolated
ShadeBundleHandler captures selected numeric parent-ray and intersection fields
before integration. It publishes the owned copies after freeRayStates, without
dereferencing the released parent rays. It does not suspend integration, restore
native ray states or route final samples through the new mailbox.

## Captured fields and ownership

The versioned XNS1 diagnostic format contains explicit little-endian fields:
24 unsigned words and 64 float32 words per record. It is not a dump of C++ object
memory. Reserved words and inactive derivatives are zeroed.

It preserves pixel/subpixel, sequence ID, tile/pass, depth and visibility mask;
geometry/primitive/instance and assignment IDs; path depth counters and LPE/lobe
IDs; ray origin/direction/range/time and active ray differentials; evaluated
position, normals, UV and available geometric derivatives; throughput, weights,
distance, roughness, presence/opacity and subpixel/texture scale values.

Deep, Cryptomatte, deferred-node, inherited light-set and volume dependencies are
recorded as presence flags. Their pointers or handles are not serialized.
A zero dependency mask is **not GPU eligibility**: BSDF/lobe/light state,
attribute storage, active sampler windows, native handle ownership and other
integrator dependencies are still absent. A sequence ID is not a complete
restorable sampler cursor.

The current capture selects two fixed diagnostic pixels and allows at most
1,024 records. It is not a production scene export. The writer is synchronized;
only single-worker native capture was validated here. It checks output errors
and flushes its bounded records. This process-lifetime diagnostic is not a Modo
DLL-unload lifecycle implementation.

## Recorded validation

[Evidence](native-surface-state-20261017.json) contains the frozen link-input
manifest, source/compiler/preprocessed-code/DLL hashes, render results, numeric
snapshots and continuation transport checks.

Four native XPU renders completed with GPU work confirmed: retained-object
control, capture disabled, capture enabled, and capture repeated. Disabled,
enabled and repeated RGBA images match the control bit for bit. The two captures
also match each other bit for bit. This scene produced exactly two selected
primary-ray snapshots with no flagged external dependencies. Indirect,
pointer-bearing and volume state capture has not been validated by this fixture.

The captured words were then included in the real GPU queue's owned-resume
payloads. All six continuation cases passed: held-GPU submissions and reverse
collection, four CPU readers, caller-buffer reuse, missing-PTX fallback,
cancellation/restart at different stages, bounded revoked CPU leases and cleanup.
The words survived these transfers exactly.

Those numeric snapshots and the pinned Lambert packets come from independent
captures. Pairing them in the transport harness tests ownership, not the
correctness of a resumed native path. No native ray was reconstructed or emitted
from this payload. The mailbox, GPU shader and queue implementations are unchanged.

Six new parser checks passed, covering identity/float-bit preservation, malformed
framing, excessive record counts, nonfinite/reserved values, unknown flags and
inactive derivative data. The previous full unit suite and 15-render shading
matrix were not rerun; their recorded results remain scoped to their candidates.
The unresolved multithread bitwise-image gate remains unchanged.

## Remaining native handoff

The first restricted Lambert adapter still needs correlated capture of native
sample/path identity, live sampler window state and supported BSDF/light data at
the exact suspension point. It must define the resumption operation, reconstruct
its own valid CPU/TLS/arena state, and preserve contribution/AOV accounting.
Only then can the owned mailbox resume native work instead of test snapshots.

Unsupported dependencies must keep using the existing XPU path. No tolerance was
relaxed, no installed kit/runtime changed, and no speedup is claimed.

## Reproduce

Use new output directories and the existing pinned fixture/runtime:

    python tools/xpu2_build_surface_capture.py --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --output test-results/surface-build-new
    python tools/xpu2_surface_capture_probe.py --build test-results/surface-build-new --scene-reference test-results/xpu2-primary-state --output test-results/surface-new
    python tools/xpu2_continuation_probe.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --surface-capture test-results/surface-new/capture/surface.bin --output test-results/native-payload-new
    python -m unittest discover -s tests -p test_xpu2_surface_state.py -v

## Correlated sampler follow-up

[CORRELATED_STATE.md](CORRELATED_STATE.md) records the next validation: eight
same-call ISPC sampler/Lambert events matched to this surface fixture, then
transported through the GPU mailbox. Native path restoration remains incomplete.
