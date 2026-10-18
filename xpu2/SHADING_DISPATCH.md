# Owned asynchronous shading-stage dispatch

Status: experimental stage integration. **Full native asynchronous shading is not
finished, and this dispatcher is not installed or selectable in Modo.**

`shading_dispatch.h` joins the indexed texture-work queue, real CUDA Lambert
queue, and CPU continuation mailbox. Previously these boundaries had independent
probes. A job can now pass through all three without keeping its submitter's stack
alive:

1. Copy up to eight shader inputs, matching native fallback values, path IDs and
   numerical context into owned storage. Associate the job with a render attempt,
   scene revision and immutable texture dependency view.
2. Wait for required RAM tiles through the background decoder. Ready jobs may
   bypass a blocked decode. The coordinator never decodes or uploads a GPU tile.
3. Prepare numerical shader inputs from resident RAM data. This callback must be
   bounded, must not call host/native scene APIs and must not retain tile pointers.
4. Submit copied inputs to the existing CUDA worker, release RAM tile leases, and
   return. The GPU's separate CUDA context receives no texture-cache addresses.
5. Poll for completion and claim an immutable CPU resume result. Keep its capacity
   charge until the consumer returns it. Only an `Accepted` finish permits image
   publication, on the coordinator before another scene transition.

GPU refusal or failure preserves the supplied CPU oracle. Decode/preparation
failures instead return an explicit failed result, which cannot enter the image.
There is no invented fallback color for missing texture data. Scene or texture
changes must begin a newer attempt, even when the geometry revision is unchanged.
Old GPU results and old CPU leases cannot publish after that transition.

The dispatcher supports at most 64 outstanding jobs, including claimed CPU
results. Its texture identity ledger is also bounded. Cache, decoder and GPU queue
have their own budgets; in-flight cancelled GPU work retains its queue credit
until the worker acknowledges it. Snapshot copies retained by callers after
acknowledgement are caller-owned memory. Polling may allocate and take locks;
this is not a hard real-time API. Close revokes work without waiting for the GPU,
but the owner must drain/join the GPU queue and decoder before destroying them.
A missing CPU consumer must return its lease; this implementation does not recover
orphaned leases automatically.

Numerical validation uses exponent bits, so NaN/infinity rejection remains active
under the native renderer's `-ffast-math` optimization. Sample ownership and lane
count cannot be changed by the preparation callback.

## Validation

The final standalone suite runs 12 scenarios on an RTX 3090, compiled with native
fast-math enabled. The machine-readable summary is
[shading-dispatch-20261017.json](shading-dispatch-20261017.json).

- Real GPU Lambert packets use pinned native AVX8 input/output captures. An
  intentional half-color GPU result proves the returned CUDA values reach CPU
  resumes. Direction, PDF, validity, IDs and numerical context are preserved.
- A synthetic constant half-albedo RAM tile changes the actual GPU input. Its
  power-of-two-scaled native oracle matches the GPU. This is a narrow data-flow
  test, not a test of arbitrary texture filtering or native textured images.
- Ready shading completes while texture decoding is deliberately held. The
  original caller reuses its input storage and performs independent CPU work.
- Missing PTX and zero GPU capacity retain exact CPU values. Decode failure,
  preparation failure, sample-identity changes and nonfinite values do not publish.
- Restart during decoding/GPU work, restart after completion, and repeated restart
  with an outstanding CPU lease suppress old results. Claimed CPU work continues
  to consume capacity. A 32-job reverse drain rejects duplicates and forged leases.
- Closing with GPU work deliberately held returns promptly; a bounded GPU stop
  reports unfinished work and later drains successfully. No worker credit remains.

Queue accounting, GPU capture counts, compiler/input/executable hashes and source
stability are checked by the runner. This suite does **not** render a native image
or establish a speedup. Existing native image results apply to the earlier
terminal-film continuation candidate, not to this dispatcher.

```powershell
python tools/xpu2_shading_dispatch_probe.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/shading-dispatch-new --fast-math
```

## Remaining native integration boundary

The native `ShadeBundleHandler` still owns arena-backed intersections and BSDFs
while `PathIntegratorMultiSampler` uses stack-local light/sampler state; it frees
parent ray states after integration returns. The new numerical stage result does
not restore any of that state. Moving a raw `RayState` or retaining its arena would
not make it independently owned.

Next, the supported Lambert path needs an explicit native prepare/resume split:
copy or reconstruct all required intersection, BSDF, sample-sequence, throughput,
light/visibility and child-ray state; retain native resources with their actual
ownership rules; enqueue resumption on valid CPU TLS; and return child rays and
radiance through native queues. Unsupported materials, volumes, deep/Cryptomatte
state and adaptive film dependencies remain on existing XPU until their contracts
are represented. A native image and cancellation gate must pass before removing
the duplicated CPU oracle or claiming acceleration. XPU remains unchanged.
