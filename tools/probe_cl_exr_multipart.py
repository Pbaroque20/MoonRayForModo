# python
"""The Render item's Multi-Part EXR control in Modo: it reads, it sets, and the scene written then has its parts. Run through
tools/launch_cl_probe.py. Writes test-results/layered-exr/control.json."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
report = {}
try:
    from moonray_modo import host, rdla
    from moonray_modo.scene_setup import configure, values
    lx.eval('scene.new')
    report['starts'] = lx.eval('moonray.render.exr_multipart ?')
    before = host.snapshot()
    configure(before, values())
    report['exr before'] = before.get('exr')
    lx.eval('moonray.render.exr_multipart true')
    report['set'] = lx.eval('moonray.render.exr_multipart ?')
    after = host.snapshot()
    configure(after, values())
    report['exr after'] = after.get('exr')
    text = rdla.scene_text(dict(after, aovs=['alpha', 'depth'], custom_aovs=[]), 64, 64, 1, 0, str(root / 'test-results/layered-exr/unused.exr'))
    report['parts written'] = sorted(set(line.strip() for line in text.splitlines() if 'file_part' in line))
except Exception:
    report['error'] = traceback.format_exc()
(root / 'test-results/layered-exr/control.json').write_text(json.dumps(report, indent=1, default=str))
