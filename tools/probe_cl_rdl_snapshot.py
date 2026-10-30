# python
"""Command-line test: an RDL example scene imported into Modo as the RDL importer brings it in, and the scene as the
plugin hands it to MoonRay and MoonLightIPR (host.snapshot) written out, for rendering in both outside Modo.

MOONRAY_PROBE_NAME names the scene (coffee_maker by default); its decoded document is
test-results/rdl-examples/<name>.document.json. Writes test-results/rdl-compare/<name>.snapshot.pickle and report.json."""
import json
import os
import pathlib
import pickle
import time
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
name = os.environ.get('MOONRAY_PROBE_NAME', 'coffee_maker')
out = root / 'test-results/rdl-compare'
out.mkdir(parents=True, exist_ok=True)
report = {'name': name}
try:
    from moonray_modo import host, rdl_import
    source = root / 'downloads/moonray-example-scenes/scenes' / name / 'scene.rdla'
    document = json.loads((root / 'test-results/rdl-examples' / (name + '.document.json')).read_text(encoding='utf-8'))
    lx.eval('scene.new')
    started = time.time()
    data = rdl_import.plan(document, str(source))
    report['summary'] = rdl_import.summary(data)
    report['import_warnings'] = data['warnings'][:40]
    rdl_import.apply(data)
    report['import_seconds'] = round(time.time() - started, 2)
    started = time.time()
    snapshot = host.snapshot()
    report['snapshot_seconds'] = round(time.time() - started, 2)
    report['meshes'] = len(snapshot.get('meshes', []))
    report['lights'] = len(snapshot.get('lights', []))
    report['camera'] = {k: snapshot.get('camera', {}).get(k) for k in ('focal_mm', 'film_mm')}
    report['resolution'] = [snapshot.get('width'), snapshot.get('height')]
    report['working_space'] = snapshot.get('asset_settings', {}).get('working_space')
    report['display'] = snapshot.get('display')
    (out / (name + '.snapshot.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
