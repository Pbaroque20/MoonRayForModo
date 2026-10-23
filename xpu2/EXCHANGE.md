# Native CPU / CUDA sampler handoffs

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This milestone validates movement of sampler state between the real native AVX8
sampler and the CUDA boundary kernel. Original XPU, installed runtimes and Modo
engine selection are unchanged. XPU2 remains experimental.

## Measured result

Each of three schedules processes the same 324 cases, 13,554 samples and 27,108
components from the pinned boundary reference. Every case executes on both CPU
and GPU. Each returned packet is the actual input to that case's next draw;
neither processor receives expected sample values.

- Alternating individual samples: 6,210 CPU-to-GPU and 6,156 GPU-to-CPU changes;
  7,182 samples execute on CPU and 6,372 on GPU.
- Seven-sample chunks: 1,080 CPU-to-GPU and 1,134 GPU-to-CPU changes;
  7,344 samples execute on CPU and 6,210 on GPU.
- Seeded shuffled assignments: 3,267 CPU-to-GPU and 3,263 GPU-to-CPU changes;
  7,183 samples execute on CPU and 6,371 on GPU.

All samples and returned state bytes match the uninterrupted native reference.
The canonical output hash is identical across all three schedules. Counts above
include forced fallback, which changes the processor actually used. The cases
repeat across schedules; these are not three separate production-scene corpora.

At selected rounds, the GPU receives no table pointers. It declines the draw
without advancing state, and the CPU then computes from that actual returned
packet. The schedules complete 432, 432 and 420 such fallback draws respectively.
Each schedule also recomputes 88 draws on the other processor from the same input;
all results agree and the diagnostic publishes only one result. This does not
implement production lease ownership or concurrent duplicate-result arbitration.

The native endpoint rejects all twelve invalid state packets without changing
their bytes. Six malformed batch cases (bad magic, zero/oversized count, truncated
header/state and trailing data) are rejected; a valid batch control passes.
153 focused Python checks pass, including deliberately corrupted results,
incorrect fallback advancement and retry mismatches.

The prior CUDA boundary/continuation and version-1 table/CMJ checks also pass.
Evidence is in exchange-20261017.json; native input/output files and full reports
remain in ignored test-results directories. Source, executable, reference,
compiler and runtime identities are recorded.

## Implementation and limits

sampler_exchange.h provides a bounded diagnostic batch endpoint in the isolated
native sampler executable. XWB2 input contains a record count, declared packet
lengths and version-2 64-byte states. XWO2 output contains states and status/hash/
float-bit results. Both formats use explicit little-endian words. The endpoint
receives no reference samples. Native sampling uses the unchanged WindowCursor
and original sampler arithmetic; CPU worker requests are one for the alternating
schedule and four for the others. Worker utilization is not measured.

exchange.py coordinates processor assignments, tracks actual device changes,
validates every result and hashes published outputs in canonical order. The
CUDA runner verifies the native executable and isolated runtime before use and
checks their identities again after the experiment. The native endpoint runs in
separate hidden processes, never inside Modo.

Transport is intentionally synchronous and uses files for native batches.
Processors do not execute concurrently in this experiment. Startup, transfers
and diagnostic bookkeeping make these timings unsuitable for benchmarking.
This validates the tested sampler handoff, not complete rendering-path state,
shading, RGB/AOV parity, texture/geometry paging or acceleration. Coverage remains
the finite AVX8 unknown-count boundary corpus on the tested CPU/RTX 3090 setup.
Native builds use frozen headers with retained objects, not a clean runtime build.

The next integration step is a narrow CPU/GPU shading path with preserved sample
identities, followed by asynchronous queues and end-to-end image comparisons.
Additional pixel/lens/shutter samplers and general path-state ownership still
need coverage before broad production migration can be enabled.

## Reproduce

Use fresh output directories and the validated native tables from DISTRIBUTIONS.md:

    python tools/xpu2_sampler_probe.py --build test-results/xpu2-origin-build --output test-results/native-exchange-new --window --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz
    python tools/xpu2_cuda_sampler_probe.py --source <shared-source-read-only> --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz --tables <validated-native-tables> --window test-results/native-exchange-new --handoff-runtime test-results/xpu2-origin-build/control --output test-results/handoffs-new
    python tools/xpu2_exchange_framing_probe.py --source <shared-source-read-only> --native test-results/native-exchange-new --runtime test-results/xpu2-origin-build/control --reference xpu2/reference/sampler-window-avx8-20261017.jsonl.gz --output test-results/framing-new
    python -m unittest discover -s tests -p "test_xpu2*.py" -q
