# CUDA distribution sampler validation

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

XPU2 remains an additional experimental architecture. Original XPU, its runtime
and Modo's installed engine selection are unchanged.

## Current result

The CUDA kernel now matches every sample component in the original native
integrator corpus when the original native sample tables are supplied:
648 cases, 23,652 samples and 47,304 components. This includes the earlier random
subset plus 1D/2D/3D table distributions and the tested known-count 2D path.

A second native corpus broadens known-count 2D correlated multi-jittered (CMJ)
sampling: 234 cases, 9,396 samples and 18,792 components. Counts are
1, 2, 3, 4, 7, 8, 15, 16, 17, 63, 64, 65 and 257, at depths 0/2, three seeds and
three sequence purposes. CUDA matches all components exactly. The original and
expanded corpora overlap; their component counts are not a count of unique
production paths.

Each final CUDA corpus was dispatched three ways, using shuffled input order,
two streams and block sizes 64/128/256. All output state bytes, sequence hashes,
sample words and status values match. Each dispatch additionally preserves and
declines eight valid but unsupported boundary records and rejects eleven invalid
records. Native CMJ generation and original-corpus verification each ran with one
worker twice and four workers once. 126 focused Python checks pass.

Evidence: distributions-20261017.json. The original compressed reference remains
unchanged; reference/sampler-cmj-avx8-20261017.jsonl.gz is the added corpus.

## What was implemented

- Known-count 2D CMJ permutation and jitter, preserving native arithmetic and
  float conversion. Total=1 uses the C++ high-bit conversion; multi-sample CMJ
  uses the ISPC low-bit conversion. Conflating them would change sample values.
- Export of original native k1DSampleTable/k2DSampleTable from frozen retained
  objects. There are 4096 sequences of 1024 entries each: 16 MiB for 1D and
  32 MiB for 2D. Exports stay in ignored diagnostic output folders, not the kit.
- CUDA table indexing and Cranley-Patterson rotations using those original
  backing tables. These are integrator sampling tables, not scene textures.
- Hash/size checks before table upload and dependency drift checks afterward.
- Explicit support gates for measured sample counts and table index range.

The first table GPU execution passed its comparisons but failed while assembling
the report because a local variable shadowed the GPU name. That tooling error was
fixed and the experiment rerun. Its raw outputs and correction record remain;
only the final guarded reports are used here.

## Deliberate boundaries

Table support is limited to indices 0 through 64. Near the native table's end,
partitioned1D/2D choose table versus R-sequence fallback based on cache-fill
start plus SIMD window size. Restoring just the next sample number may select a
different fallback than a previously filled window. This is now confirmed by
the native boundary experiment in
[WINDOW.md](WINDOW.md); cache-aware restoration matches all measured values.
A separate version-2 GPU boundary diagnostic now passes (CUDA_WINDOW.md).
The version-1 tests still explicitly decline
indices 65 and 1016 for each dimension; they do not approximate that region.

The 2D known-count path accepts only the thirteen tested totals above. The tests
explicitly decline totals 5 and 256, which are valid native inputs but not yet
part of this reference set. Missing table buffers also leave table paths declined.
These gates are diagnostic capability boundaries, not changes to XPU.

No GPU shading, pixel/camera/lens/shutter sampling, production path-state transfer,
resource paging, rendered RGB/AOV parity or speed gain is certified. Six-word
SequenceID envelopes remain specialized to this test corpus. The native cache
window state is now measured and preserved in a separate
diagnostic envelope (WINDOW.md) and validated in the separate CUDA boundary
kernel (CUDA_WINDOW.md). The existing version-1 gate remains unchanged.

## Reproduce

Use fresh output directories:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/native-tables-new --tables --reference xpu2/reference/sampler-avx8-20261016.jsonl.gz
    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/native-cmj-new --cmj --reference xpu2/reference/sampler-cmj-avx8-20261017.jsonl.gz
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/sampler-avx8-20261016.jsonl.gz --tables test-results/native-tables-new --output test-results/cuda-tables-new
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/sampler-cmj-avx8-20261017.jsonl.gz --output test-results/cuda-cmj-new

The native build uses frozen current headers with retained objects, not a clean
source/runtime rebuild. GPU uploads/downloads are synchronous. Timings here are
not performance measurements.
