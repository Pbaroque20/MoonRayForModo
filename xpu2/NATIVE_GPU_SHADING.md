# Native asynchronous GPU shading

Status: **experimental Lambert shading in isolated native runtimes**. XPU is
unchanged; this is not an installed or selectable XPU2 engine. Two candidates
separate lifetime restoration from removal of duplicate CPU BSDF evaluation.

## Owned child-path dispatch

`native_gpu_paths.py` copies first diffuse-bounce shader inputs and numerical
child-path state, submits bounded CUDA jobs, frees the original native ray
allocations, and returns from the enqueue callback. Native queue barriers collect
the shader results, reconstruct fresh ray allocations on the original CPU owner,
and put GPU-derived throughput into subsequent native traversal and film output.
No arena, BSDF, intersection or native scene pointer enters the GPU packet.

This candidate retains the native BSDF answer as an oracle and fallback. It checks
GPU direction, RGB, PDF and validity before substitution, and preserves the native
throughput multiplication grouping. It is an asynchronous ownership test, not an
acceleration claim. Native ordering barriers can wait for GPU completion.

The single-worker fixture restores 1,632,493 child paths and accepts the same
number of actual CUDA shader samples. Disabled, replacement, poisoned original
storage, missing-PTX and zero-capacity images match native XPU float32 RGBA exactly.
A half-color GPU sentinel changes 31,080 pixels (maximum channel change 0.318274),
proving the returned shader values reach the native image. Adaptive rendering and
unsupported shadow-terminator shading retain exact native output.

Matched persistent reference, fresh candidate and cancelled/reloaded candidate
images are exact. Every recorded frame releases all owned paths and GPU credits.
The cancelled frame had already drained its shader packets: this does not prove
cancellation of a deliberately held native in-flight shader. Physical worker
changes in progressive phases still bypass this restoration adapter.

The four-worker image gate remains **failed/unresolved**. An unchanged native
reference repeated with identical inputs differs by up to 0.062444 RGB; candidate
comparisons also exceed the existing 1e-6 absolute/relative bound. Queue accounting
and GPU shader-oracle comparisons pass. This does not excuse or resolve the image
differences, and no tolerance was widened.

## Pre-evaluation dispatch without a CPU oracle

`native_gpu_early.py` moves submission into `drawBsdfSamples`, ahead of native
`BsdfSampler_sample`. For the supported first-scattering Lambert subset it:

1. Copies the complete native sample-generator state and prepares the same sample
   identities for up to 16 samples per lobe. The original sampler is unchanged.
2. Copies numerical lobe inputs into the bounded GPU queue. No CPU BSDF answer is
   supplied; unavailable outputs carry a bit-checked invalid marker.
3. Consumes results in original sample order. Accepted GPU direction/RGB/PDF
   replace the lobe sample calculation. The original native surface-validity,
   statistics, light intersection, MIS, ray differential, child-ray and film code
   still runs. Light work for one sample can overlap later submitted GPU work.
4. Evaluates the native CPU lobe only for a rejected, unavailable or failed GPU
   sample. It does not also dispatch the old post-shading child-path adapter.

Native intersections and BSDFs remain valid on their owning stack/arena until
this function finishes. Only copied numerical inputs are asynchronous; this does
not suspend an arbitrary material shader and release its whole native context.
There is still a wait at the first unready dependency. Preparation repeats random
sample generation from a full sampler copy, but not accepted BSDF evaluation.

The CUDA implementation is the previously validated AVX-compatible Lambert
sampling kernel. Unsupported lobes, non-first-scattering work, more than 16 lobe
samples, adaptive sampling and nonempty AOV schemas remain native. Fresnel,
spherical/transmission modes and unsupported shadow-terminator correction are
rejected by the numerical capability contract. Texture evaluation and material
construction still happen on the CPU before this boundary. No arbitrary material
or indexed texture-streaming integration is implied.

The first one-worker matrix accepts 1,619,280 GPU samples with no CPU BSDF oracle
and exactly matches native XPU RGBA. The GPU sentinel changes 45,601 pixels.
Missing-PTX and capacity-refusal cases evaluate native shading on demand and also
match exactly. GPU counts here are execution/consumption counts, not per-sample
oracle comparisons; image parity is checked separately.

This is not yet faster: the recorded early-dispatch process took 11.22 seconds
versus 5.34 seconds disabled. The older duplicate-shading candidate took 16.41
seconds in its separate run. These are diagnostic timings with different cache
and system conditions, not a controlled comparative benchmark. Tiny transfers,
queue synchronization and first-result waits remain costs. The one-worker early
run recorded no kernel/CPU overlap observations; advance submission alone is not
proof of useful overlap or speedup.

The early candidate also matches both fresh and cancelled/reloaded persistent
native reference images exactly, accepting 1,615,887 GPU samples in each completed
frame. Nine fallback lane slots in these runs are inactive packet padding, not
nine failed active material evaluations. The cancelled first frame had already
consumed its 6,471 GPU samples; deliberately held in-flight cancellation remains
unvalidated. Both candidates join their GPU worker before releasing its context.

Four-worker early dispatch accepted 1,550,452 samples with no GPU/cleanup errors
or retained credits. Its maximum image difference was 0.062444 RGB; the repeated
unchanged reference differed by 0.056347. This image gate remains unresolved.
There were eight kernel/CPU overlap observations in the enabled four-worker run
and 12 in the persistent restart run. These event-poll counts demonstrate observed
overlap windows, not their duration or a speed benefit.

## Reproduction and remaining work

Both builders copy runtime files and recompile six objects against frozen retained
link inputs. They never edit shared native sources or the installed kit. They
record source, preprocessed/object, PTX, runtime and fixture hashes. This is not a
clean full-runtime rebuild. Raw EXRs/logs remain in `test-results`; compact results
are recorded in `native-gpu-shading-20261018.json`.

```powershell
python tools/xpu2_native_gpu_paths_build.py --source <shared-source-read-only> --base test-results/xpu2-origin-build --output test-results/new-owned-build
python tools/xpu2_native_gpu_paths_probe.py --build test-results/new-owned-build --reference test-results/xpu2-origin-build/control --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/new-owned-check
python tools/xpu2_native_gpu_early_build.py --source <shared-source-read-only> --base test-results/xpu2-origin-build --output test-results/new-early-build
python tools/xpu2_native_gpu_early_probe.py --build test-results/new-early-build --reference test-results/xpu2-origin-build/control --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/new-early-check
```

The probe supports `--adaptive`, `--unsupported`, and `--threads 4 --diagnostic`.
Diagnostic image differences remain failures. The corresponding `_cancel.py`
runners additionally require `--baseline` pointing at a passed single-worker
fixed-sample probe directory.

A shading hierarchy can route validated whole stages before CPU evaluation.
It must track feature support, scene revision, texture readiness and one owner per
sample. This candidate supplies a narrow early-routing boundary, not that general
hierarchy. Next work is larger batches with useful native continuation scheduling,
held-work cancellation, multiworker image repeatability, broader materials/AOVs,
and integration with scene-index texture dependencies. Unsupported work continues
through XPU; XPU2 must remain a separate optional architecture.
