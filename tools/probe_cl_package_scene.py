# python
"""Command-line: a scene packaged as Package Render Scene packages it (assets.package), to see what is not local and what
other renderers' items leave in it: the scene's item types of other renderers (Octane and the like), the packaged
scene.rdla's file names outside the package folder, and its objects named after those items. The scene from
MOONRAY_PROBE_SCENE. Writes test-results/package-scene/report.json and the package beside it."""
import json
import os
import pathlib
import re
import shutil
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\package-scene')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host, assets
    lx.eval('!scene.open {%s}' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    kinds = {}
    for item in scene.items():
        kinds.setdefault(item.type, []).append(item.name)
    report['all_types'] = sorted(kinds)
    report['other_types'] = {k: v[:6] for k, v in kinds.items() if re.search('octane|vray|redshift|arnold|corona|cycles|maxwell|fprime', k, re.I)}
    snapshot = host.snapshot()
    report['warnings'] = snapshot.get('warnings', [])[:40]
    target = out / 'package'
    shutil.rmtree(target, ignore_errors=True)
    try:
        assets.package(snapshot, str(target), 640, 360, 4, 1.0)
    except Exception:
        report['package_error'] = traceback.format_exc()
    text = (target / 'scene.rdla').read_text(encoding='utf-8') if (target / 'scene.rdla').is_file() else ''
    report['outside'] = sorted({m for m in re.findall(r'"((?:[A-Za-z]:[/\\]|//)[^"]+)"', text)})[:60]
    names = [n for v in report['other_types'].values() for n in v]
    report['other_named'] = [n for n in names if n and ('"%s' % n) in text][:20]
    report['objects'] = sorted({m for m in re.findall(r'^(\w+)\("', text, re.M)})
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
