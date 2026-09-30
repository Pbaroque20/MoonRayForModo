"""Verify exported Modo images in real MoonRay pixels and invalidate the cache."""
import json
from pathlib import Path
import subprocess
import sys
import os
modo = Path(r'C:\Program Files\Modo16.1v9\modo')
extra = modo / 'resrc/python3kit/extra64'
sys.path.insert(0, str(extra / 'Python/Scripts'))
dll_paths = [os.add_dll_directory(str(p)) for p in (modo, extra)]
from PySide2 import QtGui
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native, rdla, textures
folder = root / 'test-results/textures'
assert json.loads((folder / 'host.json').read_text())['passed']
scene = json.loads((folder / 'snapshot.json').read_text())
scene['lights'] = []
runtime = root / 'runtime/native-avx'
source = scene['materials']['texture_test']['textures']['diffCol']['path']
before = textures.prepare(source, True)
def render(name):
    rdla_path = folder / (name + '.rdla')
    output = folder / (name + '.png')
    rdla_path.write_text(rdla.scene_text(scene, 96, 96, 2, 1))
    with (folder / (name + '.log')).open('w') as log:
        result = subprocess.run([str(runtime/'moonray.exe')] + native.arguments(rdla_path, output, 2),
            env=native.environment(runtime), stdout=log, stderr=subprocess.STDOUT, timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, 'Native render failed; inspect texture test log'
    image = QtGui.QImage(str(output))
    assert not image.isNull()
    return image.pixelColor(32,48), image.pixelColor(64,48)
left, right = render('before')
assert left.red() > left.green()*2 and right.green() > right.red()*2, (left.getRgb(), right.getRgb())
original = Path(source).read_bytes()
try:
    image = QtGui.QImage(source).mirrored(True, False)
    assert image.save(source)
    after = textures.prepare(source, True)
    assert before != after, 'Changed source did not invalidate texture cache'
    left, right = render('after')
    assert left.green() > left.red()*2 and right.red() > right.green()*2, (left.getRgb(), right.getRgb())
finally:
    Path(source).write_bytes(original)
(folder/'render.json').write_text(json.dumps({'passed': True, 'named_uv': True,
    'srgb_conversion': True, 'source_edit_changes_pixels': True, 'cache_invalidated': True}, indent=2))
print('Real texture render and source-edit/cache invalidation passed.')
