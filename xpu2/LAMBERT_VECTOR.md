# AVX8-compatible Lambert sampling

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The separate experimental CUDA vector-math profile reproduces the original
retained AVX8 Lambert sampler exactly on the expanded 67,584-case corpus. All
473,088 direction/RGB/PDF components and 67,584 geometric-validity flags match
in each of three shuffled GPU dispatches. The earlier 96 grazing mismatches are
resolved for this profile without changing native XPU math or adding a bias.
This is still component validation, not rendered image parity or a production
migration implementation.

## Why the first profile differed

The C++ and vector implementations have different arithmetic contracts. Native
C++ Vec3 dot uses x + (y + z); the ISPC Vec3 dot uses (x + y) + z. The default
ISPC varying sincos also uses its own range reduction and polynomial, rather
than the scalar system-library sincos used by the C++ implementation. At
quadrant boundaries this can produce exact zero where the scalar implementation
retains a small residual, affecting strict geometric-validity decisions.

The new profile ports the varying sincos branch from the pinned
[ISPC v1.31.0 source](https://github.com/ispc/ispc/blob/v1.31.0/stdlib/stdlib.ispc)
and preserves its operation order and coefficients, with CUDA contraction and
fast math disabled. The source hash and BSD-3-Clause license are recorded in
lambert-vector-20261017.json and ISPC_MATH_LICENSE.txt. This helper is used only
for Lambert angles in [0, 2*pi]; it is not a replacement for general sincos.

Two separately named diagnostic entry points now select the math contract:
lambert_sample retains the previous C++ profile, and lambert_sample_vector uses
the AVX8 profile. The host requires --lambert-sample --vector-math to request the
latter; --vector-math alone is rejected. The checker compares against the
selected original native outputs, while reporting both C++ and vector errors.
Expected results never go to the GPU. No corpus values are hardcoded into the
kernel. The comparison remains strict, including signed zero and validity bits.

## Expanded coverage and results

The expanded native corpus combines eleven normals, two geometric-normal
choices, two eye vectors, three colors, two scales, reflection/transmission,
cosine on/off and 64 random pairs. It includes negative and nearly polar
normals, arbitrary oblique normals, both adjacent float32 values around each
quarter turn, and the smallest positive float32 sample. Additional pairs come
from the original native IntegratorSample<2> sequence. All original 7,680 rows
are present unchanged, verified by input and output bits.

Both native implementations repeat across three executions (C++ worker counts
1, 1, 4; ISPC remains on its calling thread in eight-lane gangs). A separate
native build with the extended probe reproduces the original pinned corpus.
CUDA uses block sizes 64/128/256 and two streams with three independent shuffled
orders. The vector profile's canonical output hash is identical in all three:
959a0dfce6a6b041bf8609d1825352181f3c49065db2b069d4426482e8473886.
Four unsupported controls/ranges and thirteen invalid packets also behave as
expected. GPU input packets are preserved on all paths.

The scalar CUDA profile still matches the original C++ corpus exactly, with
its earlier canonical hash unchanged. The expanded corpus itself has 336
C++/AVX8 validity disagreements. That is a useful negative control: matching
one native profile must not be silently treated as matching the other.

The diagnostic xpu_vector_compatibility_gate now passes for this vector corpus;
renderer_migration_enabled remains false. A passed gate requires repeatable
outputs, matching vector bits, finite results and intact packet/status handling.
It does not certify arbitrary parameters, another compiler/ISA, or a renderer.

## Remaining work

A future migratable path must carry a negotiated math-profile identity. An
AVX8-compatible path must fall back to the original vector implementation, not
a scalar implementation merely because both execute on the CPU. The current
experiment selects the profile for an entire diagnostic batch; it does not yet
serialize or negotiate that identity in a full renderer path envelope.

Next is a combined native AVX8/CUDA sampling-and-shading handoff using actual
returned path state, including retries and fallback, then a small rendered
comparison. Fresnel, shadow-terminator fixes, multi-lobe BSDFs, texture fetches,
derivatives and general materials remain outside this component. Transfers are
synchronous. No GPU utilization, render-time or scene-load improvement is
claimed. Original XPU and installed kits/runtimes are unchanged.

Native builds use current frozen headers with retained native objects, not a
clean rebuild. Evidence is lambert-vector-20261017.json; the expanded pinned
corpus is reference/lambert-stress-avx8-20261017.jsonl.gz.

## Reproduce

Use fresh output folders:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/vector-native-new --lambert-sample --lambert-stress --reference xpu2/reference/lambert-stress-avx8-20261017.jsonl.gz
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/lambert-stress-avx8-20261017.jsonl.gz --output test-results/vector-cuda-new --lambert-sample --vector-math
    python -m unittest discover -s tests -p "test_xpu2*.py" -q

Follow-up: [SHADING_EXCHANGE.md](SHADING_EXCHANGE.md) now combines the sampler
and this shading profile in actual native CPU/GPU state handoffs. It remains
a synchronous component diagnostic without intersections or image output.
