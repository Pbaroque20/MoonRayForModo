# CUDA sampler subset: first real GPU validation

XPU remains unchanged and independently available. XPU2 is an additional
architecture being developed in isolation, not a replacement. Nothing in this
experiment installs or enables an XPU2 rendering mode.

## Measured result

On the RTX 3090 (compute capability 8.6), CUDA generated the pseudo-random
IntegratorSample subset and matched 31,536 native float components exactly in
each of three shuffled dispatches. Each dispatch used two CUDA streams; block
sizes were 64, 128 and 256.

There were 23,663 input records per dispatch:
- 15,768 supported sample records, generating 31,536 tested components;
- 7,884 valid but unsupported distribution records, explicitly declined;
- 11 invalid state records, rejected before sampling.

Every returned state and every status/hash/sample record matched its expectation.
Supported states advance exactly one sample and update their checksum.
Unsupported and invalid states are returned unchanged; they produce no sample.
CPU reference sample values are never uploaded to the device. The CUDA kernel
computes sequence hashes, Threefry values and float conversion itself.

These are three dispatch configurations in one process/device context, not
independent cold GPU starts or rendered frames. Output hashes differ because the
inputs are shuffled differently; results are checked against their original
reference identities.

122 focused Python checks pass. These validate evidence handling and invariants;
the separate GPU experiment is recorded in cuda-sampler-20261016.json.

## Implemented scope

sampler_cuda.cu decodes the experimental six-word SequenceID state envelope,
checks metadata/checksum, computes the native sequence hash and implements
MoonRay's StatelessRandomEngine path: Threefry4x32 with 20 rounds, followed by the
same float-bit conversion. It handles pseudo-random override or sampling depth
at/above the tested native threshold of 3.

The native corpus covers dimensions 1/2/3, depths 0/2/3, known and unknown counts,
three seeds and three sequence purposes. The table-based distribution cases at
depth 0/2 without pseudo-random override are unsupported. Returning status 1
preserves them for future validated CPU handling; this diagnostic does not yet
implement an integrated CPU/GPU fallback scheduler.

The state layout is 60 explicit little-endian bytes, not a host struct dump.
Header/cursor rejection covers wrong length, magic, version, dimensions, total,
index, flag, sequence arity, checksum and near-wrap cursor. The checksum is for
accidental corruption detection, not authentication.

The adapted algorithms retain upstream attribution and license text in
CUDA_SAMPLER_LICENSES.md.

## Reproduce

    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/sampler-avx8-20261016.jsonl.gz --output test-results/cuda-sampler-new

Use a fresh isolated output folder. The tool reads the existing NVRTC toolchain,
compiles only this diagnostic into local PTX, creates a private CUDA context,
uploads sampler records, dispatches kernels, downloads states/results and destroys
the test context. It never patches a runtime DLL, original XPU PTX or Modo kit.
Source/reference/compiler hashes are checked for drift.

Compilation uses the detected compute capability, disabled FMA contraction,
disabled flush-to-zero and precise divide/square root settings. The local report
records GPU identity, CUDA driver API version, NVRTC hashes, PTX hash and flags.

Uploads and downloads are synchronous here. Using two streams exercises
dispatch without establishing useful overlap or asynchronous transfer speed.
The tiny sampler kernel is not a performance benchmark.

## Remaining boundary

- Table-based and known-count distribution sampling on CUDA.
- Full production path-state schemas, camera/lens/shutter sampling, resource
  ownership and actual CPU/GPU path handoff.
- Faithful GPU shading, texture filtering/mip paging and conservative geometry
  streaming.
- Rendered linear-HDR RGB, alpha and AOV parity, plus real scene-loading and
  equivalent-quality rendering benchmarks.

The successful GPU subset is a prerequisite, not evidence of complete sampling
coverage, rendered parity or a faster XPU2 renderer.

## Distribution follow-up

The first milestone above is preserved as historical evidence. CUDA distribution
support has since expanded; see [DISTRIBUTIONS.md](DISTRIBUTIONS.md) for the current
validated scope and explicit remaining gates.
