# CUDA cache-boundary validation

XPU2 remains an additional experimental architecture. Original XPU and installed
runtimes are unchanged. The version-1 CUDA sampler is unchanged; the new kernel
is a separate version-2 diagnostic entry point.

## Results on the RTX 3090

The CUDA boundary sampler matches all 27,108 native baseline components exactly
across 324 cases. It also matches all 27,108 native index-only negative-control
components. The negative control reproduces the 2,268 differences previously
measured between correct and index-only restoration; it is not an accepted
replacement for cache-aware continuation.

Three shuffled dispatches use block sizes 64/128/256 and two CUDA streams. Each
checks both modes, all returned state bytes, sequence hashes and statuses:
54,216 component comparisons, zero differences. Each also declines five valid
unsupported states without advancing them and rejects twelve invalid packets.
These repeated/mode counts are not unique production-path coverage.

A separate continuation test starts each of the 324 cases from its first native
snapshot. It then feeds the actual returned GPU state into the next GPU launch,
reshuffling cases and cycling block sizes. Across 48 rounds, 13,554 samples and
27,108 components match the uninterrupted native reference exactly. This tests
real GPU state progression, not merely separately initialized samples.

With all table pointers absent, CUDA declines all 27,113 valid packets and rejects
the twelve invalid packets. Every byte of input state is retained. This verifies
a fallback signal and state preservation; the harness does not execute native
CPU fallback after that signal.

The earlier version-1 table and CMJ GPU suites were rerun after the harness
changes. All 47,304 and 18,792 components respectively still match in each of
three dispatches. 145 focused Python checks pass. Evidence and source/compiler/
reference/table hashes are recorded in cuda-window-20261017.json.

## Implementation and boundaries

sampler_window_cuda.cu computes native R1/R2 distributions, hash functions,
Cranley-Patterson rotations and cache-window updates. Native unsigned wraparound
before index 1024 and float operation ordering are preserved. Contraction and
fast-math approximations are disabled. Expected CPU sample values are never
uploaded to CUDA.

The native window probe exports the original 16,384-entry Moebius constant table
(64 KiB), with a successful native reference comparison and hashed provenance.
The CUDA runner validates this export alongside the original 1D/2D tables before
uploading them. These are sampler constants, not scene textures. They remain in
ignored diagnostic directories rather than the distributed kit.

The new kernel accepts only the tested unknown-count boundary interval
1000-1047, dimensions 1/2/3, depths 0/2 and pseudo-random override off, using the
six-word sequence signature and AVX8 window contract. Inputs outside that domain
remain declined. The original version-1 table gate remains 0-64: this does not
silently enable the untested interval 65-999 or all later indices.

The checks cover this device/toolchain and finite corpus. They do not establish
universal CPU/GPU bitwise equivalence, GPU shading, rendered RGB/AOV parity,
real texture/geometry paging or speedup. Uploads/downloads are synchronous and
GPU work completes between continuation rounds. Interleaved native CPU/GPU sampler handoffs now pass in the separate
[EXCHANGE.md](EXCHANGE.md) experiment. Complete path-state migration and a narrow
shading implementation remain future work.
The native export uses frozen headers and retained objects, not a clean runtime
rebuild.

## Reproduce

Use fresh output directories. First retain the validated native table export as
described in DISTRIBUTIONS.md, then:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/window-export-new --window --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz --tables <validated-native-table-export> --window test-results/window-export-new --output test-results/cuda-window-new
    python -m unittest discover -s tests -p "test_xpu2*.py" -q
