# Split native material sampling stage

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This experimental runtime moves supported GPU sample dispatch out of the native
BSDF-consumption loop. XPU remains unchanged and the candidate is not installed.
This is a step toward asynchronous material shading, not full arbitrary-material
GPU execution or a native worker that can suspend and resume unrelated paths.

## Native integration

After constructing the BSDF sampler, the integrator copies numerical inputs and
sample identities for every eligible lobe (up to 16 lobes, 16 packets per lobe).
The existing queue capacity bounds accepted work, including completed results
awaiting consumption. Refused packets use native CPU shading when consumed.

Two separately selectable modes expose the dependency boundary:

- `XPU2_MATERIAL_STAGE=setup`: submit before light-set initialization and adaptive
  light selection, then resume in the original BSDF-draw position.
- `XPU2_MATERIAL_STAGE=lights`: additionally compute direct-light samples and
  prepare their shadow requests before resuming the BSDF samples. Publication of
  child rays, shadow queues and film stays in native order.

The second mode is admitted only by the fixed-sample, empty-AOV, first-scattering
stage. Russian roulette and material-AOV consumers therefore cannot read unfinished
BSDF samples. The submission sampler is an independent copy; each native lane's
active-lobe seed and the original sample ordering are retained. The resume path
advances the native sampler and consumes each GPU ticket once. Supported GPU work
is not duplicated by CPU BSDF sampling; rejected or unavailable outputs fall back.

The CPU can run useful light calculations while the numerical GPU jobs are in
flight. The first unresolved result can still wait. Arena-backed BSDFs, light
sets and the parent native call remain alive on their owning CPU thread. They
are never passed to CUDA, migrated, or retained after the native call returns.
This does not yet let that CPU worker switch to another independent native path.

## Coverage and limits

The existing kernels handle ordinary Lambert reflection/transmission and the
supported Dwa rough-diffuse subset. Texture/map evaluation, material construction,
Fresnel and unsupported lobes, direct-light BSDF evaluations, MIS, and native film
remain CPU responsibilities. Adaptive image sampling and AOV-bearing frames retain
the existing native route. The CUDA math and validation are unchanged.

`XPU2_MATERIAL_PROFILE` records staged calls/resumes, admitted packets, and whether
each packet was complete when native consumption resumed. Ready/pending counts
are snapshots, not GPU utilization, hardware overlap duration, or wait duration.
The existing early/flight profiles record subsequent waits and retirement.

## Required validation

The isolated builder compiles both the utility and multisampler ISPC objects,
plus the prior native lifetime adapters, against frozen retained link inputs.
Source, preprocessed/object and runtime hashes are recorded. It is not a complete
rebuild of the renderer dependency graph.

Native controls compare original XPU, the disabled candidate, the preceding
lookahead runtime, stage-disabled lookahead, setup overlap, direct-light overlap,
an intentional GPU color sentinel, missing PTX, zero capacity and upload failure.
Normal image comparisons retain the 1e-6 absolute/relative gate and separately
record exact float RGBA equality. The sentinel must visibly affect the image.
Persistent cancellation/reload and unsupported adaptive-frame bypass are separate
checks. No multiworker repeatability or general material parity is implied.

Full asynchronous material shading still requires owned pre-shading native
continuations, independent-path scheduling, complete supported material/texture
program execution, and broader image/AOV/multiworker validation. A shallow copy of
native BSDF or intersection pointers is not a safe substitute for that work.

## Rejected cross-path helping diagnostic

A separate `native_material_help` build tries one bounded native queue flush at
an unresolved GPU dependency, with a thread-local guard against recursive helping.
It invokes native local and XPU queues, keeping the suspended caller on its own
stack. It is not linked into the accepted split-stage build.

**This diagnostic fails image parity and must not be enabled as a renderer path.**
It performed 25,714 help calls and reported 16,052,440 processed queue entries
(including multiple stages of paths; not unique samples). The enabled image has
40,538 non-bit-identical pixels; 242 red channel values exceed the unchanged
1e-6 gate. Maximum red error is 0.05917731; alpha is exact. Disabled controls match
exactly. A single-run timing of 14.635 s versus 18.093 s for its no-help control is
not an accepted speed result because the output is incorrect.

The experiment changes native queue ordering. It also exposes a thread-local
state hazard: nested shade handlers clear the primitive-attribute offset table,
so merely keeping the parent's arena alive does not isolate its complete context.
The precise source of the observed image error is not established by this test.
No tolerance is widened and no result from this failed path is promoted.

The next native continuation must explicitly own/isolate shading context and
preserve path/sample decisions before allowing unrelated paths to execute. This
cannot be replaced by arbitrary recursive queue flushing or raw pointer copies.

## Completed validation (2026-10-18)

The split-stage candidate passes both ten-case reflection/transmission and mixed
rough-material control matrices. All eighteen normal/fallback images match native
XPU float32 RGBA exactly; both intentional GPU-color sentinels visibly differ.
The reflection/transmission normal modes consume 3,250,134 GPU lanes each, without
duplicate late-path dispatch or retained queue credits.

Persistent fresh and cancel/reload renders match native reference and each other
exactly. All staged calls resume, including the cancelled frame. Adaptive bypass
also matches exactly and records zero stage calls or GPU submissions. An initial
adaptive fixture used invalid sampling enum 1 and was rejected by native XPU; it
is retained as a fixture failure. The corrected enum-2 fixture passes. These are
correctness runs, not a repeated timing sweep or a speedup claim.

Readiness remains a limitation: in the reflection/transmission controls, setup
mode had zero of 406,530 admitted packets ready at resumption; direct-light mode
had nine ready. These measure host-visible completion, not kernel occupancy.
Most first dependencies still wait, so this boundary alone is not full scheduling.

A second helping diagnostic explicitly saves, clears and restores the shading
attribute table around nested native work. It still fails with the same maximum
red error 0.05917731 and 242 red values outside the gate. It balances 22,675 staged
calls/resumes and performs 24,881 helping calls, but the image remains incorrect.
Attribute preservation alone therefore does not fix the failure. Queue grouping,
path decisions and other native context dependencies still require investigation.
Both helping builds remain rejected, separate diagnostics.

Complete reports and identities: [native-material-stage-20261018.json](native-material-stage-20261018.json).

## Queue-family follow-up

[Scoped shadow work](NATIVE_SHADOW_WORK.md) separates the native queue families.
The major error remains when all traversal stays on GPU and follows early
intersection/shading queue work. A separate shadow-only helper preserves the RGB
tolerance on the reflection/transmission controls. This does not rehabilitate
the rejected intersection helpers or complete native asynchronous shading.
