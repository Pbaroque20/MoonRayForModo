# Bounded local-neighbor scheduling

This isolated experiment builds on four owner-thread chunks and the combined
coordination switches. It changes selection of already-admitted numeric GPU
shading packets. Original XPU and the installed Modo kit are unchanged.

## Policy

`XPU2_TILE_POLICY=neighbor` treats the last selected tile as a locality hint,
not a barrier. `XPU2_NEIGHBOR_SCAN=16` looks at at most sixteen ready packets
for a packet in the same tile or one of its eight adjacent tiles. If no match
is found, it immediately selects the oldest ready packet anywhere in the queue.
A packet at the front that has waited for 64 claims bypasses the locality search.
The optional bound of eight is also checked; an absent/zero bound preserves the
previous full-queue neighbor search for comparison. Shared mode remains FIFO.

The queue's existing mutex protects selection and removal. No packet is split,
dropped or duplicated by the policy. Mixed-pixel packets remain intact; their
first active pixel supplies only a hint. Stable sample IDs, replay validation,
owner-thread native integration and film publication order are unchanged.

This separates the small queued work unit from display buckets, but it is not
arbitrary tile ownership across CPU and GPU workers. Unsupported shading still
uses the CPU. Native TLS, BSDFs and arenas never migrate. There is no probabilistic
correctness assumption and no new global scene scan. Texture residency or a
faster shader cannot be inferred merely from selecting a nearby pixel.

## Validation

`native_local_tile_policy_test.cc` exercises bounded search, nearby work beyond
the search window, immediate nonlocal fallback, age priority, no duplicate/lost
selections, repeatability, and mixed/unknown pixel hints against the actual policy
header. `tools/xpu2_native_local_neighbor_probe.py` compares the frozen combined
coordination runtime, a same-build shared control, full-queue neighbor search,
and bounded search. Eight-entry bounds are correctness-only in this experiment;
three-round timings compare the sixteen-entry bound against full search and FIFO.

`tools/xpu2_native_local_neighbor_cancel.py` additionally checks frame replacement
with the bound active. Original float32 RGBA and raw RGB/alpha hashes remain the
image gate; changed-input and dropped-speculation controls retain native fallback.
Performance runs exclude warmup and keep compilation and other MoonRay rendering
idle. Qualification remains one native render worker and the tested fixtures.

## Recorded results (2026-10-18)

`native-local-neighbor-20261018.json` retains 37 ordinary images exactly matching
original XPU float32 RGBA and raw RGB/alpha hashes, plus two GPU-color sentinels.
Native policy contracts, rough diffuse, adaptive bypass, replay mismatch/drop,
and cancellation/replacement pass. The interrupted frame consumes all 792
claimed results; replacement consumes all 201,735 and renders the exact
original/fresh image. The `four` probe label means the sixteen-candidate policy
with four prepared CPU chunks; `neighbor` means the prior full-queue policy.

After warmup, three rotated rounds measured MCRT medians of 8.066 s original
XPU, 9.722 s frozen combined-coordination runtime, 9.886 s same-build FIFO,
9.800 s full-queue neighbor search, and 9.999 s bounded search. Bounded search
ranges from 9.460 to 10.089 s and FIFO from 9.798 to 10.423 s. Ranges overlap;
no speed gain is demonstrated. The bounded observed median is 1.14% slower
than FIFO and 23.96% slower than original XPU in this comparison. It remains
opt-in, and the 7.6 s target remains unmet.

Median candidate inspections fall from 345,757 to 211,986 (about 39%), but
selection time is only 23.32 ms versus 22.06 ms. Both modes process the same
1,625,067 GPU shading lanes without queue-capacity fallback. The bounded policy
therefore controls search cost and fairness; it does not remove the dominant
render overhead. Queues are timing-dependent, so inspection totals are observed
counts, not a guaranteed fixed reduction for every scene.

No competing MoonRay renderer was recorded during timing. The earlier CPU-side
coordination result and this scheduler result are separate experiments with
separate controls; their percentage changes must not be multiplied or summed.
