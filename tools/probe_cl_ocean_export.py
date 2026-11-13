# python
"""Command line: test-results/ocean/ocean_demo.lxo exported for MoonRay by the kit as it now is (the test profile's),
as the kit's scripts/export_moonray.py exports it: test-results/ocean/ocean_demo.rdla (PROBE_SCENE and PROBE_RDLA
for another scene)."""
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean')
try:
    source = os.environ.get('PROBE_SCENE', str(out / 'ocean_demo.lxo'))
    target = os.environ.get('PROBE_RDLA', str(out / 'ocean_demo.rdla'))
    lx.eval('@{kit_MoonRayForModo:scripts/export_moonray.py} "%s" "%s"' % (source, target))
except Exception:
    (out / 'export_error.txt').write_text(traceback.format_exc())
lx.eval('!app.quit')
