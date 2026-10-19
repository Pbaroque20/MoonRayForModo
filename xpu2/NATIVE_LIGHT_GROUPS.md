# Grouped native light-sample packets

Experimental, default-off follow-up to the native asynchronous direct-light
connection. It combines the samples already owned by one drawLightSamples call
into one numeric packet, preserving per-sample/lobe/lane offsets and consuming
results in original order. It does not retain native pointers or extend arena
lifetimes, and does not yet batch across multiple native shading calls.

XPU2_LIGHT_GROUP=1 enables grouping only when the existing direct-light path
admits the call and samples * lobes * 8 fits 512 lanes. Larger groups use the
previous per-sample submission path; unsupported direct-light calls remain native.
The queue's job limit rises from 128 to 512 lanes, within its existing 512-lane
flight buffers and 4096-lane credit limit. No PTX or arithmetic changes are made.

Invalid samples and unsupported lanes retain zero acceptance; their output is
never accidentally used as a valid contribution. A group without any supported
input submits no job. Native validity tests, fallback, clamping, shadow rays,
accumulation and film publication remain unchanged. The group is collected before
its native call returns. Input initialization clears only each actual lobe range
instead of the maximum possible range; both same-build controls share that change.

This deliberately trades overlap within one call for fewer allocations, queue
locks, owner records, uploads and collections. It could still be slower overall;
measured paired timings and exact-image gates determine the result. The original
XPU renderer and installed kits are unchanged.

Reproduction uses tools/xpu2_native_light_group_build.py from the frozen async
build, then tools/xpu2_native_light_group_probe.py for image/failure controls,
rough diffuse, adaptive bypass and rotated timings. Cancellation uses
tools/xpu2_native_light_group_cancel.py. Both same-build control and grouped
variants run GPU direct lighting; only grouping differs. Timing compares original
XPU, same-build grouping off and grouping on, after warmup and three rotated
rounds. The probe retains an optional previous-runtime correctness label, which
leaves direct lighting and sample reuse off and is excluded from timing.

The small sample-count fixtures derive from the reflection/transmission input,
with SceneVariables image_width=96, image_height=54, pixel_samples=1 and
light_samples=1 or 4. MoonRay squares that light setting, exercising one and
sixteen samples per light. They check packet offsets and invalid lanes at both
ends of the admitted sample-count range; they do not exhaust all lobe-count
combinations or prove the maximum 512-lane packet is reached by a real scene.

Recovery qualification uses XPU2_LIGHT_HOLD_PACKET=10000 only on its canceled
frame. After uploading that flight, the worker announces a diagnostic marker and
waits one second before launching. The harness requests native cancellation upon
that marker and still requires an actually canceled job and exact replacement
image. This exercises safe handling of pending transfers/results; it does not
claim to preempt an executing CUDA kernel. Normal and timed runs omit the flag.
The initial unheld cancellation attempt drained all groups before canceling and
is excluded from pending-work qualification; its report and probe are retained.

## Follow-up direction: alternating initial assignments with stealing

The requested next scheduling experiment begins with alternating CPU/GPU tile
preferences and allows an idle device to atomically claim untouched eligible
work from a neighbor. A claim must identify the frame epoch, stable tile/sample
range and attempt; already running work stays with its owner. Retry/revocation
must reject late results, and ordered publication must not depend on completion
order. CPU-only work cannot be stolen by the GPU. Symmetric stealing is allowed
when either device finishes first; no fixed contribution percentage is enforced.

Existing local_tile_schedule.py models exclusive leases and neighbor preference,
and native_local_tile_policy.h selects pending GPU packets. Neither means the
native GPU currently owns arbitrary full-tile rendering. The current grouped
light path remains coupled to the calling CPU; larger independent owned units
and a wider GPU shading path are prerequisites for that native tile experiment.
This direction is recorded here, not claimed as implemented by packet grouping.

## Qualification (2026-10-18)

The final v2 candidate passes the reference/control/grouped/verification/fault
matrix, rough-diffuse images, adaptive bypass, single/sixteen light sample cases,
and native persistent cancellation/replacement. Before timing, this is 18 ordinary
exact float32 RGBA comparisons and one deliberate GPU-color sentinel. The native
numeric verification checks 1,438,792 accepted contributions with no bit mismatch.

The principal fixture retains 1,438,792 accepted GPU contributions while reducing
jobs and collections from 180,680 to 45,170 (75%). Each grouped job launches alone
and the observed peak flight count falls to one. This is fewer handoffs, not
more independent work in flight; the CPU still collects before leaving the call.

The held cancellation frame submits 10,000 jobs, collects 9,999, cancels one,
and retires all 10,000 with zero retained credits, errors or abandoned owners.
Its replacement matches original and fresh persistent images exactly. Missing
PTX, zero capacity and injected upload failure likewise produce exact fallback
images and release ownership. Adaptive bypass admits no direct-light jobs.

The initial candidate's controls passed, but its unheld cancellation run did not
exercise pending-job cancellation and is excluded. Final evidence uses only
xpu2-light-group-v2-* reports and the v2 frozen build. The test-only hold is absent
from correctness controls and speed measurements. This remains one native worker
on RTX 3090 / driver 591.74 / AVX1, not multiworker or production qualification.

## Timing and interpretation

Warmup plus three rotated rounds add 12 exact images, for 30 ordinary exact
float32 RGBA comparisons plus one intentional GPU-light sentinel in this phase.
No competing MoonRay process was observed before/after timed renders; those
snapshots do not exclude other machine activity or short intervening processes.

Median MCRT: original XPU 8.590 s; same-build ungrouped direct lighting 26.710 s;
grouped direct lighting 26.771 s. Grouped-minus-ungrouped paired differences are
+0.061, -0.290 and +1.456 s. Ranges overlap: there is no demonstrated speed gain.
Median process times are 28.162 s ungrouped and 28.198 s grouped. The result does
not approach the user's 30-40% reduction target against original XPU.

The paired controls explain why job count alone was misleading. Ungrouped
submission already coalesces 180,680 jobs into 46,878-47,695 CUDA launches and
45,384-45,466 collect waits in these runs. Grouping has 45,170 jobs, launches and
waits. Thus the 75% metadata/job reduction produces only a small reduction in
actual launches/waits. Both paths consume the same 1,438,792 GPU contributions.
The grouped path has one outstanding flight; ungrouped reaches two. These are
outstanding counts, not measurements of simultaneous kernel execution.

Both controls also share the narrower input clearing and equivalent packing
helper refactor, so this comparison does not attribute their individual effects.
The earlier connection's launch counts must not be substituted for this paired
same-build control. Kernel time, context switching and host wait duration still
require separate attribution; this test does not prove the GPU arithmetic itself
is slow.

The next useful boundary is multiple independently owned native work groups,
not more per-call packet reshuffling. Keep cheap/small work on CPU unless an
eligible GPU batch can amortize its handoff, and test alternating initial device
preferences with stealing only after such groups can run and resume independently.
This is a proposed compromise, not a validated policy or fixed GPU/CPU percentage.
Grouping remains experimental and off by default; no installed kit is changed.

Evidence: [native-light-groups-20261018.json](native-light-groups-20261018.json).
