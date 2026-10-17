# Native sampler reference

Status: native CPU/ISPC sampler validation only. No CUDA sampler, GPU shading,
scene render, kit installation or XPU2 engine activation.

## Result

648 IntegratorSample cases, with 47,304 float components per execution mode, were
evaluated in three standalone native executions: one worker twice and four
workers once. Every bit-pattern record repeats exactly.

Both complete-state restoration methods match uninterrupted sampling exactly:
- splitting sequences into chunks of 1, 7, 8, 9 and 31 samples;
- requesting individual sample indices in shuffled order.

The deliberately incorrect resume-only control differs in 2,916 components over
54 cases. All differences occur in the tested 2D, known-total-count distribution
paths at depths 0 and 2, with pseudo-random override disabled.

This is an important migration constraint: IntegratorSample::resume() clears the
known total count. Restoring only SequenceID and sample number can switch a
known-count 2D sequence from correlated multi-jittered sampling to a different
sampling path. Preserve total count, depth and pseudo-random mode as well.

These are synthesized native sampler inputs, not a trace of every sampler call
in a production scene. This validates the tested integrator interface and native
AVX build, not pixel/camera/lens/shutter sampling or all possible sequence states.

## Corpus and reproducibility

reference/sampler-avx8-20261016.jsonl.gz contains the native uint32 float words.
Compression has a fixed timestamp; comparisons use decoded records, not gzip
bytes. sampler-20261016.json records evidence and provenance hashes.

The input grid covers:
- 1D, 2D and 3D samplers;
- depths 0, 2 and 3, including the random fallback boundary;
- pseudo-random override on/off;
- unknown sample count and known counts 1, 16 and 64;
- seed words 0, 19 and 0xffffffff;
- BSDF, light and BSDF Russian-roulette sequence purposes;
- 65 samples for unknown-count sequences, crossing multiple AVX8 cache windows.

SequenceID is constructed using the native implementation and fixed explicit
arguments: depth, packed pixel (96,77), seed modulo 3 as lobe, purpose, zero
subpixel key and seed. The seed word is a test argument, not a replacement
implementation of MoonRay frame/global seed policy.

Each restore uses IntegratorSample(sequenceID, totalSamples, sampleNumber) and
restores setUsePseudoRandom before getSample at the original depth. The probe
uses real native ISPC calls where MoonRay dispatches them. It does not implement
a second RNG, upload random numbers to a GPU or modify shader evaluation.

Build and execute into a fresh isolated folder:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/sampler-new --reference xpu2/reference/sampler-avx8-20261016.jsonl.gz

The build argument must identify a completed isolated retained-object diagnostic
build made by xpu2_build_ray_probe.py. Current headers are preprocessed into a
frozen translation unit; retained native objects provide sampling tables and
ISPC implementations. This is not a clean rebuild or a distributable renderer.
Header preprocessing, retained object hashes and dependency runtime inventory
are checked for drift. Full commands and logs remain under the output folder.

Compiler settings retain native AVX8, Ivy Bridge, no AVX2/FMA and disabled
floating-point contraction. These results make no cross-compiler or
cross-architecture bitwise guarantee.

110 focused Python checks pass, including malformed/truncated corpus rejection,
float range validation, restoration mismatch, cross-execution drift, compressed
reference matching and the committed native corpus. Python checks are distinct
from the three native executions.

## Next boundary

The scheduler can preserve stable work identities; this corpus now specifies
tested native sampler values. The next implementation must:
- define a native path-state transfer record that preserves every active sampler;
- preserve sequence arguments/ordering and total count through resource faults,
  queues, retries and CPU/GPU transfers;
- compare a future CUDA sampler against this corpus before enabling GPU shading;
- extend coverage to camera/lens/time and production integrator call sites;
- validate shading, intersections, filtering, film order and AOVs separately.

RNG agreement does not fix the grazing shadow disagreement in ORIGINS.md, prove
RGB image parity or establish a performance gain.

## Serialized handoff follow-up

XPU remains intact and independently available. XPU2 is intended as an additional
selectable architecture after validation, not a replacement. No selector or
installed renderer is changed by these tests.

sampler_state.h now defines an experimental 60-byte little-endian state envelope
and a native SamplerCursor wrapper. The envelope records magic/version,
dimensions, sampling depth, known total (or explicit unknown sentinel), next
sample index, pseudo-random flag, six sequence words and a checksum. It rebuilds
the native sampler with the complete state. It never calls resume() as a
substitute for known-count restoration and never serializes a C++ object layout.

This schema covers the six-word SequenceID signature used in this corpus only.
It is not yet a general path-state format. A production transport still needs
attempt/resource ownership, pinned sampler/build identity, other sequence
signatures, all active samplers and shading state. The checksum detects accidental
corruption; it is not authentication. It cannot detect a semantically wrong but
otherwise valid sender-supplied value.

sampler_handoff.cc serializes after each chunk of up to seven samples and returns
the record to a shared native CPU work queue. A deferred job does not advance its
sampler. Selected jobs are recomputed from the same record to test retries; only
one copy is published. All handoff records are decoded and validated.

Three native executions (one worker twice, four workers once) matched the pinned
uninterrupted corpus exactly: 648 cases and 47,304 components per execution.
Each execution covered 3,888 simulated resource waits and 778 recomputations.
The four-worker execution recorded 2,395 actual worker-to-worker handoffs; its
four workers processed 1,138, 727, 1,172 and 851 chunks. These scheduling counts
may vary while the sample values remain fixed.

Eleven native guards rejected incomplete/corrupted envelopes, unsupported
magic/version/arity, invalid dimensions/flags/count/cursor, exhausted sampling
and a cursor/template dimension mismatch. 115 focused Python checks pass,
including evidence completeness and the requirement that multiple workers
actually participate. Evidence is in sampler-handoff-20261016.json.

Reproduce into a fresh directory:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/handoff-new --reference xpu2/reference/sampler-avx8-20261016.jsonl.gz --handoff

This is an actual native CPU handoff test; resource waits/retries are simulated.
It does not exercise CUDA, PCIe, real texture/geometry I/O, shading or rendered
images. The resume hazard is avoidable in the tested paths with full-state
restoration; it is neither a fatal test failure nor a reason to change XPU.
