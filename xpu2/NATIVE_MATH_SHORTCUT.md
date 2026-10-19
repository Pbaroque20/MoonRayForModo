# Rough-diffuse algebra experiment

This is an isolated PTX experiment, not a renderer/default change. It tests whether
an expensive mathematical representation is a meaningful cause of the current
XPU2 slowdown. Original XPU, native binaries, installed kits, sample directions,
scheduling, transport and film integration are unchanged.

## Change

The existing rough-diffuse GPU sampler computes a normalized-normal dot product,
clamps it, applies native inverse cosine, clamps the angle to pi/2, then applies
ISPC-compatible cosine. The candidate replaces only that round trip with the dot
product clamped to [0, 1]. Normalization, roughness coefficients and the rest of
the shader remain unchanged. Generated CUDA files differ by exactly this
substitution. Compiler flags retain non-fused arithmetic and precise division and
square roots; there is no blanket fast-math change.

The expressions are equivalent over real numbers for this domain. They are not
bitwise equivalent to the native polynomial approximations and float32 rounding.
This is a test of representation choice, not a general inverse mapping system.

## Results, 2026-10-19

Fifteen standalone renders completed on RTX 3090 / driver 591.74: one correctness
triplet, followed by a warmup triplet and three rotated timing triplets. Each
triplet contains original XPU, unchanged XPU2 math, and the shortcut. The fixture
is 384 x 216 with rough diffuse (roughness 0.6) and diffuse transmission, fixed
sampling and one native worker. Prepared host records are enabled and GPU resident
record tables are disabled in both XPU2 variants.

- All five unchanged XPU2 images match the original XPU RGBA values exactly.
- All five shortcut images differ at 3,803 pixels. Maximum absolute RGB error is
  5.960464477539063e-08; alpha is unchanged. All pass the predeclared
  1e-6 absolute plus 1e-6 relative channel tolerance. Exact parity fails and is
  retained as `image_differences`, never relabeled as an exact pass.
- Each XPU2 image consumes 1,625,067 GPU rough-diffuse samples and 1,625,067
  transmission samples. GPU accounting and queue/flight teardown checks pass;
  the comparison is not explained by silently falling back to native shading.
- All before/after timing snapshots contain no competing MoonRay process.

Measured MCRT medians and ranges, excluding warmup:

- Original XPU: 7.756 s (7.745-8.088).
- Unchanged XPU2 math: 11.293 s (11.009-11.539).
- Shortcut: 11.125 s (11.008-11.183).

Paired shortcut-minus-unchanged differences are -0.285, +0.116 and -0.356 s.
The 0.168 s difference of medians is about 1.5%, with overlapping ranges and an
inconsistent sign. This does not establish a reliable end-to-end speedup or close
the gap to original XPU. CUDA event intervals are retained as diagnostics but can
include device scheduling contention; they do not isolate the cost of the removed
arithmetic. No claim about a faster standalone math kernel is made.

## Reproduction and evidence

`tools/xpu2_math_shortcut_ptx.py` produces isolated exact and `--shortcut` PTX
variants from unchanged sources. `tools/xpu2_math_shortcut_probe.py` uses the frozen
resident-v2 native build with record residency disabled, verifies binary/source
hashes, checks rough-diffuse GPU coverage, compares raw float32 RGBA, and retains
numerical differences while completing the diagnostic. `--repeats 3` runs the
warmup and rotated rounds; the default is a correctness-only triplet. A numerical
difference returns a nonzero diagnostic exit code even when tolerance passes.

Reports remain under `test-results/xpu2-math-rough-checks` and
`test-results/xpu2-math-rough-timing`. Generate the compact checked-in
[evidence](math-shortcut-20261019.json) with
`tools/xpu2_math_shortcut_evidence.py`. It preserves report hashes, compiler flags,
PTX provenance, image errors, coverage and timings. Neither test changes image
error limits after seeing results.

## Decision and next direction

Keep native arithmetic as the default. This narrow math shortcut is not a
sufficient explanation or solution for the current slowdown. It does not rule out
other useful algebraic simplifications, but a generic conversion framework would
add complexity before a speed benefit has been demonstrated.

A future representation-aware operation needs a canonical meaning, an input
domain, exact versus tolerance-based equivalence, conversion cost, and a safe
native fallback. Clamps and rounding cannot generally be inverted. Moving a
calculation to another device need not require converting it back if the next
operation can consume that representation directly.

The earlier material-value/texture reuse investigation remains pending. Prioritize
reusing stable computations and removing host reconstruction/coordination work,
then larger independently useful GPU shading jobs. This experiment does not
qualify arbitrary materials, multiple native workers, adaptive rendering,
production scenes, or the proposed representation infrastructure.
