# python
"""GUI: what an exported Cryptomatte holds (a reporter: the material Cryptomatte, as saved, does not work in
Photoshop). Opens test-results/layer-mask/layer_mask.lxo, gives the scene Cryptomatte outputs for objects and
materials as the preview window's buffer list does, renders once in MoonRay (vector), then saves each Cryptomatte with
Export AOVs' writers, one file each and one multilayer OpenEXR, into test-results/cryptomatte-export. report.json has,
for the preview's own buffer files and every file written, its parts, channels and Cryptomatte metadata."""
import json
import os
import pathlib
import subprocess
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = pathlib.Path(os.environ.get('PROBE_OUT') or root / 'test-results/cryptomatte-export')
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def described(runtime, path):
    from moonray_modo import native
    text = subprocess.run([str(pathlib.Path(runtime) / 'oiiotool.exe'), '--info', '-v', '-a', str(path)], env=native.environment(runtime),
                          capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    keep = []
    for line in text.splitlines():
        held = line.strip()
        if any(word in held for word in ('channel list', 'cryptomatte', 'subimage', 'oiio:subimagename', 'name:', ' x ')):
            keep.append(held[:400])
    return keep


def panel_widget():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def export():
    try:
        p = panel_widget()
        frame = p.renderer.buffers.frame
        runtime = frame['runtime']
        result['buffers'] = {key: str(path) for key, path in frame['files'].items()}
        crypto = [key for key in frame['files'] if key.startswith('crypto')]
        result['crypto_keys'] = crypto
        result['preview_files'] = {key: described(runtime, frame['files'][key]) for key in crypto}
        written = {}
        for key in crypto:
            target = out / ('render_%s.exr' % key)
            try:
                p.write_buffer(frame, key, target, 'exr32')
                written[target.name] = described(runtime, target)
            except Exception as exc:
                written[target.name] = 'failed: %s' % exc
        saved, failed = p.write_layered(frame, ['beauty'] + crypto, out / 'render.exr', 'exr32')
        written['render.exr'] = described(runtime, out / 'render.exr') if saved else 'failed %s' % failed
        result['written'] = written
    except Exception:
        result['export_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


def start():
    try:
        p = panel_widget()
        stored = p._settings_values() if hasattr(p, '_settings_values') else None
        from moonray_modo import outputs, properties
        settings = properties.scene_settings()
        entries = [v for v in settings.get('custom_aovs', []) if v.get('kind') != 'cryptomatte']
        # The categories asked for (PROBE_CATEGORIES, comma-separated): the material one alone by default.
        wanted = [{'name': 'crypto_' + c, 'kind': 'cryptomatte', 'category': c, 'depth': 6}
                  for c in (os.environ.get('PROBE_CATEGORIES') or 'material').split(',')]
        entries = outputs.values(entries + wanted)
        p._store(custom_aovs=entries)
        # The kit's own runtime, as installed: the test profile's writes one Cryptomatte category alone.
        p.preferences.set('runtime', str(root / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime'))
        result['runtime'] = p.runtime_path()
        p.preferences.set('xpu2/renderer', 'xpu')
        p._store(execution_mode='vectorized')
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray'))
        p.render_once()
        began = time.monotonic()

        def wait():
            q = panel_widget()
            if (getattr(q, '_rendering', False) and time.monotonic() - began < 300) or time.monotonic() - began < 8:
                QtCore.QTimer.singleShot(1500, wait)
                return
            result['steps'].append([q.status.text(), q.render_timing.text()])
            save()
            QtCore.QTimer.singleShot(3000, export)
        QtCore.QTimer.singleShot(2000, wait)
    except Exception:
        result['start_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % (root / 'test-results/layer-mask/layer_mask.lxo'))
    lx.eval('moonray.open')
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, start)
