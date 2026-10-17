# Owned native contribution arithmetic

This milestone validates one native numerical resumption stage after all original
render memory is gone. It is not whole-path suspension, CPU/GPU path ownership,
alternating image patterns, or a renderer acceleration result.

## Boundary and representation

The isolated capture build records selected calls around `integrateBsdfSample`
after GPU shader collection and before selective clamping. It records the exact
native inputs and native distance/direct/indirect outputs without substituting
its own contribution calculation into the renderer.

XCR1 records contain eight identity words, 24 float input slots and eight float
output slots. Identity preserves pixel, subpixel, sequence, nonmirror depth,
lobe index, sample index, native SIMD lane and sample-array index. The local
capture record index identifies replay jobs; these fields are not a complete
global path address. No pointer or native handle is serialized.

Inputs own lobe/light sample counts, indirect/mirror/light-validity flags, light
distance/PDF/radiance, BSDF PDF/RGB and path throughput. Unused slots are zero.
Unused invalid-light fields are zeroed rather than reading undefined values.
Invalid native contribution outputs are excluded from capture; early-return
state is not represented. Only two diagnostic pixels at subpixel zero are
selected, with a hard limit of 4,096 records.

The replay generator extracts the native ISPC contribution function and replaces
its sampler/lobe getters with these owned values. The native arithmetic, MIS
heuristic and math/compiler flags remain. The exported replay kernel reconstructs
only the fields that this arithmetic reads. It requires no native TLS, arena,
BSDF object, light object or scene pointer. It does not reconstruct such objects.

## Validation

`owned-contribution-20261017.json` retains source/build/runtime/compiler/PTX/GPU
identities and the results. Local artifacts are under
`test-results/xpu2-owned-contribution-build-v2` and
`test-results/xpu2-owned-contribution-validation`.

Four native renders passed: relinked control, capture-disabled, capture-enabled
with audited native GPU lighting overlap, and repeat. Their float32 RGBA images
match bit-for-bit. Captures repeat byte-for-byte; GPU replacement and overlap
counters are checked on enabled renders. This matrix checks images and captured
contributions, not a new selected-ray/shadow trace comparison.

The captured payload remains local in the validation output directory. Only its
hash and aggregate coverage are published; the scene-derived binary is not included.

The fixture yields 18 records: two primary diffuse surfaces, nine lobe samples,
four light samples, indirect enabled, valid direct-light hits, non-mirror lobes,
and original SIMD lanes 1 and 3. Every record has nonzero direct and indirect
contributions, so the replay exercises the native MIS arithmetic. Other paths,
mirror/invalid-light branches and secondary bounces remain unvalidated here.

After the capturing render process exits, a separate executable copies records
into owned values and overwrites/releases its serialized source buffer. It
replays each record 64 times using one/four CPU workers and forward/reverse job
ordering. All four normal runs pass exact output-word comparisons: 4,608 jobs,
no mismatches, no missing/duplicate jobs, and no writes to inactive SIMD lanes.
Each worker owns its scratch arrays and reuses them between jobs. Ordered output
files are identical across schedules.

Four additional sentinel runs halve BSDF RGB. All 1,152 jobs in each sentinel
run change, with identical sentinel output across worker schedules. Six malformed
payloads are rejected before output: bad header, truncated record, nonfinite
input, zero BSDF PDF, invalid boolean flag and nonzero reserved input. The existing
238-test XPU2 regression suite also passes.

An initial capture build failed because an ISPC declaration preceded its uint32_t
typedef. The declaration now uses the built-in unsigned integer type; the retained
v2 build compiled successfully. No failed-build artifact is treated as validation.

## What remains

This is an owned arithmetic stage, not a resumed whole path. It does not enqueue
secondary rays, restore sampler windows, retain light/material identifiers for
LPEs, accumulate film/AOVs, or migrate TLS/arena-backed state. Replayed results do
not feed the native renderer. No CPU shading duplication has been removed and
no render speedup is claimed. Four-worker arithmetic parity does not resolve
the existing multi-worker bitwise film gate.

The proposed CPU/GPU alternating pattern policy can be tested once workers can
complete independent native batches. Ownership must switch only at completed
batch boundaries. Completed contributions stay in the image; the next owner
gets the next unclaimed sample range. An in-flight batch retains its owner, and
each logical pixel/sample is accepted once. Compare fixed alternation with a
shared ready-work queue; a whole-round barrier may leave the faster device idle.
This policy is a design direction, not an implementation delivered here.

## Reproduce

Use new isolated output directories:

    python tools/xpu2_build_batched_shading.py --profile --window-dispatch --async-transfers --packed-readback --native-overlap --contribution-capture --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/contribution-build-new
    python tools/xpu2_owned_contribution_probe.py --source <shared-source-read-only> --build test-results/contribution-build-new --scene-reference test-results/xpu2-primary-state --ptx-reference test-results/xpu2-ray-image-final --output test-results/contribution-validation-new

No Modo launch, kit installation, shared-source edit or user-scene modification
is required. Existing XPU and the installed selector remain unchanged.
