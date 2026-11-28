# python
"""Command line: Modo's own render (render.animation, the scene's first frame, OpenEXR) of the scene MOONRAY_PROBE_SCENE
names, to MOONRAY_PROBE_RENDER (a path without its extension; Modo adds the output's name and the frame)."""
import os
import pathlib
import traceback
import lx

target = pathlib.Path(os.environ['MOONRAY_PROBE_RENDER'])
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('!render.animation {%s} openexr' % target)
    lx.eval('!scene.close')
except Exception:
    target.with_name(target.name + '-error.txt').write_text(traceback.format_exc())
