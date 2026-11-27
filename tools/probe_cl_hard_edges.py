# python
"""Command line: tools/probe_cl_smooth_render.py with the MoonRay Source Override "Displaced hard edges stay sharp"
(native.displaced_hard_edges) as PROBE_HARD_EDGES says (1 on, 0 off), whatever the test profile's preference: what the
kit hands MoonRay, XPU2 and MoonLightIPR either way, for test-results/hard-edges/render.py."""
import os
import pathlib

from moonray_modo import native

wanted = os.environ.get('PROBE_HARD_EDGES', '1') == '1'
native.displaced_hard_edges = lambda: wanted
os.environ['MOONRAY_MODO_DISPLACED_HARD_EDGES'] = '1' if wanted else '0'
# Modo runs a probe without __file__: the tools folder named, else this checkout's.
probe = pathlib.Path(os.environ.get('PROBE_TOOLS', r'C:\Users\Raphael Tobar\MoonRayForModo\tools')) / 'probe_cl_smooth_render.py'
exec(compile(probe.read_text(encoding='utf-8'), str(probe), 'exec'), {'__name__': '__main__', '__file__': str(probe)})
