# Lambert direction sampling: C++ agreement, AVX8 parity blocked

Follow-up: [LAMBERT_VECTOR.md](LAMBERT_VECTOR.md) resolves the measured AVX8
mismatch in a separate GPU math profile and broadens validation. This document
retains the original scalar-profile investigation and its limits.

The experimental CUDA sampler now matches the original C++ Lambert sample
operation exactly for the pinned 7,680-case corpus: direction, RGB, PDF and
geometric-validity flag. This is a component result, not rendered image parity.
The original AVX8 ISPC implementation differs from both. XPU2 remains disabled;
this experiment does not permit moving XPU shading work to this GPU kernel.

## What was measured

The native oracle calls the original C++ LambertBsdfLobe::sample and the original
retained AVX8 ISPC LambertBsdfLobe_sample. It does not replace either formula with
a Python reference. A thin ISPC wrapper passes varying records to the retained
function, using the original AVX1 i32x8 target. The packet wrapper does not enable
force-aligned-memory: packet fields are not aligned native SoA arrays. The first
isolated wrapper did promise that alignment and crashed on an aligned load; the
corrected wrapper no longer makes that invalid assumption. No installed binary
was changed.

The matrix includes five normals, two geometric-normal choices, two eye
vectors, three colors (including black and HDR), two scales, reflection and
transmission, cosine enabled/disabled, and 16 random pairs. Ten pairs cover
hemisphere endpoints/quadrants/near-endpoints; six come from the original native
IntegratorSample<2>. This is a small deterministic corpus, not exhaustive random
coverage. Both native implementations repeated exactly across three executions.
C++ uses 1, 1 and 4 workers; the ISPC wrapper always processes eight-lane gangs
on its calling thread. A second isolated build matches the pinned corpus.

CUDA on the RTX 3090 processes the same inputs under three shuffled orders,
block sizes 64/128/256 and two streams. All 53,760 floating-point components
and 7,680 validity flags match C++ bitwise in each execution. Input packets are
unchanged. Four unsupported cases and thirteen malformed cases return their
expected statuses. Canonical result hashes match across dispatch schedules.
Native expected values are used only by the host-side checker, never uploaded.

The sampling test exposed a dot-product association mistake in the earlier
CUDA evaluation helper: native C++ uses x + (y + z), not (x + y) + z. Correcting
that operation order removes 464 RGB and 480 PDF component differences in this
corpus. The earlier 11,520-case evaluation regression still passes unchanged.
No tolerance or reference output was adjusted to get that result.

## The remaining migration hazard

Native C++ versus original AVX8 has:

- 5,472 differing direction components, maximum absolute difference 1.74846e-7.
- 560 differing RGB components, maximum absolute difference 4.76837e-7 (2 ULP).
- 576 differing PDF components, maximum absolute difference 2.98023e-8 (2 ULP).
- **96 different geometric-validity decisions.**

The decision differences occur with r1=0.5 and r2=0.25 or 0.5, where the sampled
direction is tangent to the geometric normal. One implementation returns an
exact zero component while the other retains a small trigonometric residual.
These are 48 configurations per random pair, not 96 distinct random directions.
For example, case 1156 has geometric-normal Z; C++ produces a positive Z residue,
while ISPC produces zero. The strict sign-product validity test then differs.
Large reported direction ULP distances near zero must be read alongside absolute
error; a small component discrepancy can still change a path decision.

Therefore close lobe RGB values alone do not establish image parity. The next
step is to isolate and match the AVX8 trigonometric/frame/reduction behavior, or
retain native CPU sampling for that path. Changing the validity predicate,
adding a bias, or globally replacing XPU math is not justified by this result.
A numerical image contract would also need rendered visibility, alpha and AOV
checks before accepting non-bitwise paths.

The native report's status describes repeatability. The CUDA report's status
describes strict C++ agreement plus packet guards; its separate
xpu_vector_compatibility_gate is **blocked** and renderer_migration_enabled is
false. Neither passed status is permission to enable a rendering backend.

## Limits and reproduction

Fresnel and shadow-terminator corrections are declined, as are albedo above 8
or scale above 2. Inputs must be finite, unit directions and random values in
[0,1]. The diagnostic does not include texture fetches, differentials,
multiple-lobe selection, full path-state handoff, asynchronous CPU/GPU rendering,
scene loading, throughput measurements or an installed XPU2 selector. Native
builds use frozen headers with retained native objects, not a clean runtime
rebuild. The existing XPU engine remains unchanged.

Evidence: lambert-sample-20261017.json. Pinned native data:
reference/lambert-sample-avx8-20261017.jsonl.gz. Local raw results/logs are retained
in the test-results/xpu2-*-lambert-sample* directories, including the failed
alignment and initial dot-order attempts.

Use fresh output folders:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/sample-native-new --lambert-sample --reference xpu2/reference/lambert-sample-avx8-20261017.jsonl.gz
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/lambert-sample-avx8-20261017.jsonl.gz --output test-results/sample-cuda-new --lambert-sample
    python -m unittest discover -s tests -p "test_xpu2*.py" -q
