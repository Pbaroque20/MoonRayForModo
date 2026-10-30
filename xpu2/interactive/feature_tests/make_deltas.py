"""Test deltas for the kit scene: make_deltas.py <folder> <output folder>."""
import sys
from pathlib import Path

folder, out = Path(sys.argv[1]), Path(sys.argv[2]).resolve().as_posix()
(folder / 'd2.rdla').write_text('''PerspectiveCamera("/modo/camera") {
  ["node_xform"] = Mat4(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -0.4, 0.3, 4, 1),
}
RenderOutput("/modo/preview/beauty") {
  ["file_name"] = "%s/2.buffer.exr",
}
''' % out, encoding='utf-8')
(folder / 'd3.rdla').write_text('''UsdPreviewSurface("/modo/material/0") {
  ["diffuseColor"] = Rgb(0.1, 0.6, 0.2),
}
SceneVariables {
  ["image_width"] = 320,
  ["image_height"] = 200,
  ["pixel_samples"] = 8,
}
RenderOutput("/modo/preview/beauty") {
  ["file_name"] = "%s/3.buffer.exr",
}
''' % out, encoding='utf-8')
(folder / 'd4.rdla').write_text('''SceneVariables {
  ["sampling_mode"] = 2,
  ["min_adaptive_samples"] = 16,
  ["max_adaptive_samples"] = 1024,
  ["target_adaptive_error"] = 10,
}
RenderOutput("/modo/preview/beauty") {
  ["file_name"] = "%s/4.buffer.exr",
}
''' % out, encoding='utf-8')
print('ok')
