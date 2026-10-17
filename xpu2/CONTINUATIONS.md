# Owned CPU-resume stage

The experimental continuation mailbox connects the existing real GPU queue to
an owned CPU-resume lease. It is an integration component, not a suspended native
MoonRay path. Shader packets come from the pinned native capture; the metadata
used by the current test harness is synthetic and pointer-free.

## Native lifetime boundary

Inspection of the current native source found three reasons not to suspend the
Lambert function and simply retain its arguments:

- `ShadeBundleHandler.cc` wraps its arena in `SCOPED_MEM`. It allocates intersection,
  BSDF and SOA ray-state buffers there, calls `integrateBundledv`, then frees the
  parent pooled ray states when that call returns.
- `PathIntegratorMultiSampler.ispc` allocates BSDF/light samples and child-ray
  buffers in the arena, uses stack-local samplers and references, then restores
  arena bookmarks. The Lambert return is consumed inside this call chain.
- `RayState.hh` contains intersection/deferred-node/Cryptomatte pointers, deep
  and Cryptomatte handles, and encoded light-set pointers. A byte copy is not an
  independent ownership snapshot.

[Recorded source inspection and test evidence](continuation-20261017.json)
pins the inspected source hashes and line anchors. These are lifetime findings,
not a complete inventory of native continuation dependencies. The shared native
sources were read, not patched.

## Mailbox contract

`ContinuationMailbox<State, Queue>` is an internal coordinator-thread component:

1. `begin(attempt, revision)` starts a strictly newer render attempt and revokes
   older pending/claimed work, even when the scene revision is unchanged.
2. `submit` owns a value copy of the supplied state, native fallback output and
   a GPU ticket. It returns an owner/slot/serial token. Invalid inputs, closed
   admission or a full mailbox return no token. If GPU admission declines, the
   admitted mailbox entry holds the existing CPU result for immediate resumption.
3. `claim` returns an immutable owned snapshot only when ready, and only once.
   Pending/rejected claims do not change the destination. The snapshot carries
   attempt, revision, original metadata and shader output. `QueueResult` may
   contain preserved native values after GPU failure; it does not assert GPU use.
4. CPU consumers can read the immutable snapshot on other threads, then return
   their lease to the coordinator. `finish` accepts the current lease once,
   rejects duplicates/foreign payloads, or reports it revoked after cancellation,
   closing or restart. Native film publication is not implemented. A future
   adapter must apply this gate before accepting a consumer's work.
5. `close` cancels waiting tickets and revokes claimed CPU leases. It returns
   false while any CPU lease remains unreturned. Return those leases, close
   successfully, stop/join the GPU queue, and destroy the owners in that order.

Capacity is held until CPU lease return, not merely GPU completion. Revoked CPU
leases retain their slots across restarts; otherwise rapid restarts could create
unbounded outstanding CPU snapshots. Collected shader credits can be released
while these separate continuation slots remain occupied. Slot serials prevent
old tokens aliasing newly admitted work.

`State` must own every resource it needs: the template cannot prove a user-defined
state contains no borrowed pointers. The current fixture tests only owned value
arrays. The mailbox does not preserve arbitrary native handles, enforce global
path/sample uniqueness, assign random numbers, accumulate film, or retry CPU work.
Exactly-once acceptance is per admitted lease. Stable logical sample/path identity
must be supplied by the future integrator adapter independently of dispatch order.

Callers must return leases even after revocation. Retaining copies of acknowledged
snapshots is caller-owned memory outside this capacity budget. Owners must not be
destroyed with live leases; the diagnostic implementation terminates on contract
violation. Destruction is not a loader-lock cleanup path. GPU/device-loss handling
and orphaned CPU-lease recovery remain future work.

## Validation

Six final standalone processes passed on the RTX 3090:

- 64 GPU requests were admitted before a deliberately held GPU worker was released.
  Original input/state buffers were reused. Reverse collection matched all pinned
  shader values and owned metadata exactly; four CPU readers checked the snapshots.
- Completed GPU work released its queue credits, while 64 claimed CPU leases kept
  the continuation mailbox full until return. Foreign owners/threads and duplicate
  claims/finishes were rejected. Closed GPU admission used exact CPU values.
- Missing PTX returned exact native values for all 64 accepted requests.
- Restart cancelled three queued packets and one in-flight packet, rejected old
  tokens, reused slots safely and delivered fresh work under the new attempt.
- A one-slot mailbox stayed full across repeated restarts while its old CPU lease
  was outstanding. Closing reported that obligation; returning the old lease
  reported revocation, then new work completed successfully.
- A completed-but-unclaimed old result was cancelled before resumption. Zero GPU
  capacity used CPU fallback without GPU initialization. A forged snapshot and an
  invalid attempt transition were rejected without corrupting valid work.

All test owners drained and all queue workers joined with zero cleanup errors.
Queue accounting and shader captures were checked independently by the runner.
An earlier six-case pass is retained locally; the final pass adds a forced
one-slot restart-capacity assertion. This is not native rendered-image validation.
The unchanged unit suite, native image matrix and DLL-unload tests were not rerun.
The existing multithread bitwise image gate remains unresolved.

## Next native adapter

Start with a tightly restricted supported Lambert path. Split preparation and
resumption outside the current nested ISPC stack; explicitly own the needed ray,
intersection, sampler and BSDF/light state. Exclude unsupported deep/volume/AOV or
pointer-bearing state until its ownership is represented. Keep other work on the
existing XPU path. A moved RayState or a generic byte copy is insufficient.

The adapter must preserve native sequence addresses and the selected CPU SIMD
profile, attach render-attempt and scene-revision identities, and keep cancellation
from publishing stale rays or film contributions. Resume on the proper CPU work
queue with valid TLS/arena state. Validate native rays, contributions and image
parity before removing duplicated CPU reference shading or measuring acceleration.

## Reproduce

```powershell
python tools/xpu2_continuation_probe.py --source <shared-source-read-only> --ptx test-results/xpu2-ray-image-final/sampler.ptx --output test-results/continuation-new
```

The output must be new. No Modo launch, kit installation or user-scene change is
required. The report records compiler, preprocessed-source, executable, input and
log hashes, GPU identity, shader comparisons and complete queue accounting.

## Native numeric capture follow-up

[NATIVE_SURFACE_STATE.md](NATIVE_SURFACE_STATE.md) records the first real native
numeric snapshots and their transport through this mailbox. Full native path
capture and restoration remain incomplete; the paired shader fixture is independent.
