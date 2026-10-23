# Combined readback and shader-audit controls

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The optional `--profile --window-dispatch --async-transfers --packed-readback`
build adds a combined readback path. `XPU2_PACKED_READBACK=1` selects it at runtime.
The same build can retain two separate downloads for A/B comparison. No installed
kit, normal XPU selector or default diagnostic path changes.

The kernel writes its existing 96-byte input echo and 36-byte result for each
sample into adjacent regions of one allocation. The result region starts at
`count * 96`, so a full audit downloads exactly `count * 132` bytes in one call.
Allocation-base pointers remain unchanged for cleanup. The original pinned PTX
and numerical shader code are unchanged.

`XPU2_SHADER_AUDIT=0` selects the experimental performance mode. It requires
combined asynchronous readback. This mode downloads only the result region,
`count * 36` bytes. The GPU still writes the echo; it is neither transferred nor
checked on the CPU. RGB comparison against the native answer is skipped.

## Checks that remain

CPU reference shading is still executed. Native lighting has already consumed
its direction/PDF/validity, so those words must still match the GPU answer before
publication. Performance mode therefore retains those routing comparisons. Both
modes reject malformed/non-finite results and invalid PDF/validity encoding,
respect the kernel's unsupported/invalid status, and preserve all queue, revision,
lane, cancellation and post-sampler guards. This is not removal of all per-sample
comparison or removal of CPU shading.

An RGB-only corruption is deliberately accepted in performance mode and rejected
in audit mode. This is an explicit tradeoff, not a new claim of automatic parity
protection. Exact final-image and selected-contribution comparisons still run in
the native validation harness. Supported-corpus validation must precede broader
use, and production XPU2 remains unavailable. Audit mode remains the default.

The candidate still has one stream and one GPU batch in flight. This experiment
measures fewer readback calls and less diagnostic data; it does not implement
independent path scheduling or cross-batch overlap.

## Evidence requirements

Readback calls and bytes are counted. Audited samples, performance samples,
returned-input checks and retained routing checks are counted separately. The
harness rejects a mode that silently uses the wrong transport or audit policy.
Async timing fields retain the interpretation in [asynchronous transfers](ASYNC_TRANSFERS.md):
enqueue time is not completed-transfer time and overlapping spans must not be added.

## Recorded results

[Evidence](packed-readback-20261017.json) records seventeen native renders and
eighteen standalone GPU guard processes. All 231 XPU2 Python tests passed. Normal and CPU-fallback images match
original XPU float32 RGBA exactly, with unchanged selected rays, contribution
multisets and shadow visibility. The altered-color sentinel changes the film.
Each normal run processes 210,114 samples in 2,919 GPU batches; the partial-window
case has 8,757 batches.

Separate audited readbacks took 1.359 / 1.377 seconds of Mcrt time. Combined
audited readback took 1.361 / 1.336 seconds. Results-only performance mode took
1.380 / 1.348 seconds. There is no clear render-time improvement on this fixture.
Original XPU took 0.372 / 0.366 seconds and remains substantially faster.

Combined audit halves the number of readback calls, from 5,838 to 2,919, while
transferring the same 27,735,048 bytes. Performance mode transfers 7,564,104 bytes
in 2,919 calls, a 72.7% reduction in returned data. It records no echo/RGB audit
checks and retains 210,114 direction/PDF/validity checks. Mode accounting is
verified by the harness, not inferred from timings.

Despite fewer calls and bytes, readback enqueue spans remain about 0.325–0.344
seconds in the combined modes. Native collection spans remain about 0.845–0.869
seconds. Shader validation itself takes about 0.010 seconds with quiet logging.
The result points toward batch dispatch/synchronization latency as the next
priority; it does not establish a pure driver-cost breakdown. Timings have
uncontrolled cache/machine-load variation and overlap across threads.

The experiment does not justify disabling audit by default. Keep combined and
performance modes explicit. The next architectural target is independent owned
work that lets CPU workers continue while GPU batches are outstanding, with
larger useful shading stages per handoff. CPU shading is still duplicated here.

Additional GPU guards verify packed buffer reuse at 1, 8, 72, 512 and 3 samples
using varied captured inputs; non-finite output rejection; unsupported-input
fallback; rejection of altered PDF in performance mode; and rejection versus
acceptance of an RGB-only corruption in audit versus performance modes. Existing
allocation/transfer failure, queue publication, slot/lane and cleanup cases also
pass. These tests do not establish GPU-reset or Modo-unload safety.

## Reproduce

Use new output directories and the retained native build/reference inputs:

    python tools/xpu2_build_batched_shading.py --profile --window-dispatch --async-transfers --packed-readback --source <shared-source-read-only> --runtime test-results/xpu2-origin-build/trace --pbr-build test-results/xpu2-surface-capture-build --shading-build test-results/xpu2-native-async-build --trace-build test-results/xpu2-origin-build --output test-results/packed-build-new
    python tools/xpu2_profile_probe.py --window-dispatch --async-transfers --packed-readback --build test-results/packed-build-new --ptx-reference test-results/xpu2-ray-image-final --scene-reference test-results/xpu2-primary-state --output test-results/packed-native-new
    python tools/xpu2_batched_guard_probe.py --profile --window-dispatch --async-transfers --packed-readback --source <shared-source-read-only> --capture test-results/xpu2-correlated-capture-final/capture/correlated.bin --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/packed-guards-new

Changing result layout does not imply a shader, texture or scene-loading speedup.
Multi-worker film parity, full native path ownership and production lifecycle
integration remain separate unresolved gates.
