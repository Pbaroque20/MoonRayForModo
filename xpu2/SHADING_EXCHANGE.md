# Combined sampling and shading handoff

This experiment connects the original native sampler and AVX8 Lambert lobe to
the validated CUDA equivalents through a diagnostic state envelope. It tests
whether the next operation can move between CPU and GPU without changing the
random stream, material result or geometric-validity decision. It is not a
renderer integration or asynchronous execution benchmark.

## State and atomic completion

The 208-byte XSH1 envelope contains a version, an explicit native-AVX8 math
profile ID, the 64-byte cache-aware sampler state, the 96-byte Lambert parameter
packet, and the previous eight-word shading result. The next operation obtains
two samples from the native or GPU sampler, uses them as the Lambert random
inputs, and feeds its actual returned direction into the next operation's eye
vector. It preserves the math-profile ID. Native-only reference trajectories
are generated before mixed execution; expected results are never uploaded to
the GPU.

The host commits a new envelope only when both stages succeed. Missing GPU
sample tables decline the operation unchanged. The test also simulates an
unavailable GPU shading stage *after* sampling succeeds: the advanced sampler
state is discarded, and CPU fallback starts from the original envelope. Unsupported/invalid shader-result rollback is covered by fault-injection unit
checks. This prevents skipped samples or mismatched material state during a
partial operation. Unsupported profile IDs are declined, never reinterpreted
as the scalar math contract.

Native transport uses bounded XHB1 request / XHO1 response frames. Record
lengths, magic/version, reserved controls, sampler checksum and shader inputs
are checked. Malformed batches fail before creating an output frame. Native
code invokes the original WindowCursor<2>/IntegratorSample and original AVX8
Lambert sample function. Each worker groups up to eight records by the native
constructor's uniform reflection flag and invokes the corresponding varying
ISPC function. The GPU performs actual sampler and vector-profile shading
kernels, with synchronous host packing between them.

## Coverage

All 108 two-dimensional sequences in the pinned boundary corpus are included,
covering native sample-table to procedural-sequence transitions through index
1047. Materials are selected deterministically from the expanded Lambert
corpus. Each trajectory carries its real returned sampler, direction and
shading state into the following operation; it is not reconstructed from the
expected next state. Three schedules exercise single-step alternation,
seven-step chunks and seeded shuffled assignments. CPU workers are requested
as 1, 4 and 4 respectively. Cross-device retries must reproduce the same state
and result, and the diagnostic publishes each operation address once.

The tests compare every envelope byte, both random values, sequence hash,
direction, RGB, PDF and geometric-validity flag against the native-only
trajectory. Separate guards cover profile/header/control rejection, corrupt
sampler state, unsupported shader settings and invalid parameter packets.
The framing probe includes one successful control plus bad magic, empty and
oversized counts, truncated header/state and trailing-byte cases.

The first combined endpoint failed because its second reflection group
revisited a record already committed by the first group, after that record's
pending storage had been moved. Clearing the active marker at commit fixes
that isolated endpoint bug. The failed attempt and input are retained under
test-results/xpu2-shading-handoff; no installed renderer was changed.

## Measured result

All three schedules pass with 4,518 unique operations each; every one of the
108 sequences executes on both processors. Each schedule compares 40,662 float
components, 4,518 sequence hashes and 4,518 validity flags, plus every state byte.
The canonical result hash is identical:
bd765be318405a53f842e08b19d4699376cb1a2b7f3263bd2cb7636066c373ce.

Single-step alternation executes 2,538 operations on CPU and 1,980 on GPU;
seven-step chunks execute 2,574 / 1,944; shuffled assignment executes
2,477 / 2,041. Missing-table fallback occurs 144 / 144 / 137 times;
post-sampling shader-unavailability fallback occurs 144 / 126 / 135 times.
Each schedule verifies 56 cross-device retries without duplicate publication.
Twelve envelope guards pass on both backends, six malformed batch frames are
rejected, and the valid framing control passes. All 186 Python checks pass.
The original sampler/48-round continuation and standalone vector-shading
regressions also pass.

Evidence is shading-exchange-20261017.json. The native reference trajectory is
pinned as reference/shading-handoff-avx8-20261017.bin.gz. After decompression it
has an XHT1 header (four-byte magic, uint32 record count), then 472-byte records:
uint32 case and step, 208-byte incoming envelope, 208-byte returned envelope,
and twelve uint32 result words. The result is status, sequence hash, two sample
float bits, direction XYZ bits, RGB bits, PDF bits and a validity flag. Its raw
SHA-256 is recorded in the evidence. All native requests/responses and the
complete raw reports remain under test-results/xpu2-shading-handoff-fixed.

## Limits and next step

This is a sequence of sampler/shader operations, not a ray-traced bounce chain:
there are no surface intersections, ray origins, throughput updates, radiance
accumulation, light selection, textures or image output. The validity decision
is preserved and compared, but the diagnostic deliberately continues after
invalid samples to test further operations; a real integrator must honor the
flag before tracing or accumulating. Fresnel, shadow-terminator correction,
multiple lobes and unmeasured shader domains remain declined or unimplemented.

The explicit profile ID identifies the pinned native AVX8 contract in this
experiment; a production protocol needs negotiation tied to runtime/compiler
capabilities and full path-state ownership. Native builds use frozen headers
and retained objects, not a clean runtime rebuild. Files, hidden process launches
and synchronous GPU transfers are diagnostic overhead. There is no performance,
concurrent CPU/GPU shading or rendered RGB/AOV parity claim. Original XPU and
installed kits/runtimes remain unchanged.

Next is integrating this component operation into a small ray-traced path test,
including geometric validity, throughput and contribution accumulation, before
measuring asynchronous execution or enabling XPU2.

## Reproduce

Use fresh output directories. The retained native runtime and original sampler
table exports must match their verified manifests.

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/shading-native-new --lambert-sample --reference xpu2/reference/lambert-sample-avx8-20261017.jsonl.gz
    python tools/xpu2_shading_framing_probe.py --native test-results/shading-native-new --runtime test-results/xpu2-origin-build/control --source <shared-source-read-only> --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz --materials xpu2/reference/lambert-sample-avx8-20261017.jsonl.gz --output test-results/shading-framing-new
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz --tables test-results/xpu2-native-tables --window test-results/xpu2-native-window-tables --shading-native test-results/shading-native-new --shading-runtime test-results/xpu2-origin-build/control --shading-materials xpu2/reference/lambert-stress-avx8-20261017.jsonl.gz --output test-results/shading-handoff-new
    python -m unittest discover -s tests -p "test_xpu2*.py" -q
