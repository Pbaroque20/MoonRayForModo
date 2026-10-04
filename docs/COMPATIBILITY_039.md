# 0.3.9 development update

## Tile scheduling and adaptive display

The upstream batch path hard-coded Morton. The plugin previously exported a
`batch_tile_order` attribute that is not used by this path. The repeatable native
patch now makes batch rendering consume `progressive_tile_order`; the exporter
writes that supported attribute and `checkpoint_tile_order` from the selected
pattern, without emitting the unused batch attribute. The persistent render log
reports the effective scheduler from the native frame state.

Boxes show sampled active CPU worker rectangles, not completed pixels or a
replay of dispatch order. Multiple workers, skipped converged adaptive pixels,
100 ms telemetry polling, delayed image conversion, and asynchronous XPU work
can produce a scattered appearance. This release does not claim frame-exact
synchronization between boxes and images. Boxes are suppressed when image and
telemetry dimensions differ. Checkpoint initial estimation can use an upstream
random schedule independently of the main selected order.

Progressive previews snapshot sample weights before color and display a gray
checkerboard for zero-weight pixels. This is a display-only placeholder in both
shared-memory and PFM delivery; final EXRs are untouched. Alpha is never used as
sample validity: environment RGB remains visible at zero coverage alpha. Display
transforms also affect placeholder shades. This distinguishes missing samples;
it does not diagnose or fix black pixels with valid samples, nor prove that the
reported artifact is resolved. Live snapshot buffers are not an atomic film copy.

## Texture coordinates

Named UV attributes now request derivatives in native scalar and vector texture
maps. Normal bases use those derivatives; bump differences transport coordinates
from primary UVs to named/projected UVs. Skewed tangent bases use the full bump
gradient. Projection-only meshes receive a nondegenerate reference UV basis.
Missing derivatives produce a warning and neutral result. Locator projections
remain interpolated from exported face corners rather than evaluated analytically
at every hit; this can differ on large polygons. Render validation is pending.

## Deferred verification

No tests or Modo sessions are run for this release. Run
`python -m unittest discover -s tests -p test_compatibility_039.py` later for
export regressions. Host checks: compare spiral/Morton/top-down at one CPU worker
and then multiple workers; compare adaptive and uniform; compare intermediate
checkerboard against final beauty, environment-only pixels and cropped frames;
compare UV1 color with UV2 normal/bump and skew/mirror/non-UV projections in
Scalar, Vector and XPU. Existing 0.3.8 and broader compatibility gaps remain.
