# python
"""Command-line test: where a whole reading of MOONRAY_PROBE_SCENE (host.snapshot, as Modo evaluates it) spends its
time, by function. Writes test-results/cl-export/prep/profile_snapshot.txt."""
import cProfile
import io
import os
import pathlib
import pstats
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\profile_snapshot.txt')
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host
    profile = cProfile.Profile()
    profile.runcall(host.snapshot, evaluated_geometry=True)
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(45)
    pstats.Stats(profile, stream=text).sort_stats('tottime').print_stats(20)
    out.write_text(text.getvalue())
except Exception:
    out.write_text(traceback.format_exc())
