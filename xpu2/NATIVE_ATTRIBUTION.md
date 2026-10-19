# Native chunk and offload attribution

This test reuses the qualified isolated timeline-v3 runtime without rebuilding it.
Tracing and fine integration timers stay off. The experiment changes only explicit
flags, never the original runtime, installed kit, input scene or shading PTX.

Five configurations share the fixed sample/seed/image and one native worker:

- `reference`: frozen original XPU, default 32-ray native chunks.
- `disabled`: candidate binary, XPU2 disabled, 32-ray native chunks.
- `native_chunk`: same candidate with XPU2 disabled and 64-ray chunks.
- `capacity0`: 64-ray XPU2 preparation/replay and four owned chunks, with queue
  capacity zero. No GPU shading dispatch is accepted; native CPU fallback remains.
- `control`: same 64-ray, four-owned-chunk pipeline with normal GPU admission.

The enabled variants both use FIFO selection, two GPU flight slots, the same
coordination options and original sample/film order. Native XPU intersections
remain enabled in every configuration. GPU shading is the operation being varied,
not all GPU work.

The disabled32/original comparison includes compiled adapter scaffolding and
prior native source changes. Disabled64/disabled32 tests the chunk-size effect
in the same binary. Capacity-zero measures preparation plus fallback, not a pure
CPU version of the offloaded kernel. It changes synchronization and execution too;
subtracting its time from full GPU execution does not isolate PCIe transfer cost.

`tools/xpu2_native_attribution_probe.py` preserves exact RGBA checks, GPU/queue
lifetime assertions and before/after competing-renderer checks. It runs a warmup
and three rotated rounds. Timings include original XPU and both disabled controls
in each round. Source/runtime identities are checked before and after the suite.
The disabled controls must not emit the shading adapter's profile files; capacity
zero must dispatch no shading flights while exercising CPU fallback.

`tools/xpu2_native_attribution_evidence.py` validates the complete run matrix,
configuration, exact images and stage CSVs, then records raw timings, paired
same-round differences and median native stage times. These are configuration
comparisons; phase deltas must not be added as if they were exclusive work.

No new renderer code is introduced, so the previous cancellation/replacement gates
remain applicable to the unchanged runtime. This experiment does not qualify new
materials, multiple native workers or general scene acceleration.

## Recorded result (2026-10-18)

All 20 ordinary renders (five warmups plus three rotated five-case rounds) match
original XPU float32 RGBA exactly. The frozen runtime and sources did not change;
no new runtime, kit installation or Modo launch was needed. Before/after process
checks recorded no competing MoonRay renderer. The evidence is retained in
`native-attribution-20261018.json` with the source report hash and each stage CSV hash.

MCRT medians: original XPU 7.812 s (7.789–8.234), disabled32 8.409 s
(8.310–8.410), disabled64 8.052 s (7.778–8.179), forced CPU fallback64
9.269 s (9.084–9.645), and GPU-enabled64 10.010 s (9.871–10.066).
End-to-end process wall medians are 9.227, 9.792, 9.495, 10.762 and 11.498 s,
respectively; MCRT figures must not be presented as scene-load/end-to-end time.

Using paired same-round differences:

- Disabled32 costs 0.175–0.621 s more than original. Compiled adapter/native patch
  differences still impose some cost even when GPU shading is off.
- Disabled64 is 0.131–0.632 s faster than disabled32. Against original, its
  difference changes sign (-0.182 to +0.367 s); the median paired difference
  is -0.011 s. Larger chunks are not the main regression in this fixture.
- Forced CPU fallback adds 1.090–1.593 s over disabled64, with a paired median
  of 1.306 s. Integration accounts for a median 1.17622 s of this change.
- Full GPU shading adds another 0.365–0.797 s over forced fallback (paired median
  0.787 s). This is a net configuration difference, not isolated PCIe/GPU cost.
- Full GPU shading versus disabled64 costs a paired median 1.958 s; Integration
  increases by a paired median 1.73949 s.

Medians of paired differences need not equal differences of medians or sum across
comparisons. With only three rounds and one fixture, these numbers locate an
experimental bottleneck rather than establish broad performance guarantees.

The added preparation/replay/fallback path already carries substantial overhead
without dispatching GPU shading. The next optimization target is repeated native
setup, sample preparation and replay bookkeeping; a useful test should retain
owner/revision checks, immutable inputs and exact-image/failure gates. This test
does not yet identify one dominant function or prove how much duplicate work can
be removed safely. Wider material offload remains necessary for the eventual
30–40% improvement target; no speed improvement over original XPU is claimed here.
