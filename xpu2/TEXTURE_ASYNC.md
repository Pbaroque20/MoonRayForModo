# Background texture decoding

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

`texture_async.h` adds a bounded native decode worker and a polling bridge into
`Cache::acquire`. The coordinator submits exact texture/revision/mip/tile keys;
the worker performs file reads and decoding, and the coordinator consumes ready
owned bytes before starting existing completion-fenced CUDA uploads. No Modo or
CUDA APIs run on the decode worker. Its decoder is both created and destroyed on
that worker, preserving OIIO loader thread ownership.

Duplicate keys share one ticket. Queued, active, ready and failed requests all
count against byte and record limits. Ready bytes remain charged until cache
admission consumes them, including while pinned cache pages prevent admission.
An existing CPU/GPU backing page bypasses decoding. Failure is explicit, consumes
no successful sample, and can be retried after the caller collects the exception.

Cancellation removes queued/ready work immediately. An active read cannot be
interrupted: its reservation remains until it returns, then its result is
discarded. Cancelling and resubmitting the same key creates a distinct ticket;
the old completion cannot remove or replace the new request. `cancelAll` lets the
caller retire an old generation without publishing its delayed results. `close`
waits for active decoding to finish; it is not a bounded-latency cancellation API.

## Validation

- 1,292 native assertions, including 1,000 lifecycle jobs: controlled blocked
  reads, coordinator responsiveness while a read waits, deduplication, queue
  limits, queued/active/ready cancellation, revision separation, stale tickets,
  decode/size/factory failures, retry, blocked cache admission and worker teardown.
- Existing cache regression: 29,532 assertions / 20,000 randomized operations.
- Existing policy regression: 74,689 assertions / 5,000 randomized plans.
- Four real RTX 3090 transfer consumers, with no CUDA cleanup errors.
- Actual OIIO decoding on the worker feeding CUDA filtering: 16 decoded tiles;
  24,576 bytes and six records at peak in the 65,536-byte decode queue.
- All 234,976 point/bilinear lookups / 587,776 components match the frozen CPU
  OIIO reference exactly. All 32 fallback checks pass, as do two policy-driven
  GPU evictions and the independent 96x64 texture-space RGBA image comparison.

Compact evidence: `texture-async-20261017.json`. Full local results:
`test-results/xpu2-async-contract-publish/report.json` and
`test-results/xpu2-async-filter-first/report.json`.

Use the cache and filter commands documented in `TEXTURE_RESIDENCY.md`; both now
include background-loader validation. The filter runner locks fixture, source,
binary and runtime hashes and rejects drift.

## Scope and remaining work

This is standalone native texture-pipeline validation, not a production renderer
or a measured speed improvement. The probe still waits for all required pages
before launching a filter batch. Metadata discovery on the coordinator remains
synchronous; actual worker file registration and tile decoding are independent.
A future native scene-index integration must supply validated immutable content
revisions, cancel obsolete demand, prioritize queued work and dispatch other
useful CPU/GPU work while pages are absent. The generic queue does not hash files
or watch them for changes. The OIIO loader checks source size/mtime after its own
registration; the probe additionally verifies immutable fixture hashes.

Queue limits cover owned decoded payload reservations, not the decoder's internal
allocations, OIIO's separate cache, metadata, driver overhead or kernel buffers.
The decoder itself must enforce its output-size limit before allocating. Texture
cache, staging and decode-queue budgets are separate and must all be included in
production memory planning. No mip selection, anisotropic filtering, color/alpha
conversion, full-scene parity, native fallback dispatch or load-speed claim is
added here. Stock XPU, the installed kit and the shared checkout remain unchanged.
