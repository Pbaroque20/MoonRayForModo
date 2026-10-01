"""Render a supplied image through both supported material backends."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
modo = Path(r'C:\Program Files\Modo16.1v9\modo')
extra = modo / 'resrc/python3kit/extra64'
sys.path.insert(0, str(extra / 'Python/Scripts'))
dll_paths = [os.add_dll_directory(str(p)) for p in (modo, extra)]
from PySide2 import QtGui, QtCore
QtCore.QCoreApplication.addLibraryPath(str(modo / 'qtplugins'))
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native, rdla

source = Path(sys.argv[1]).resolve()
assert source.is_file()
folder = root / 'test-results/image-file'
folder.mkdir(parents=True, exist_ok=True)
snapshot = Path(sys.argv[2]) if len(sys.argv) > 2 else root / 'test-results/textures/snapshot.json'
scene = json.loads(snapshot.read_text())
scene['lights'] = []
material = scene['materials']['texture_test']
layer = dict(material['textures']['diffCol'], path=str(source), use_alpha=True)
material['layers'] = [layer]
material['textures'] = {'diffCol': layer}
# Preserve the source aspect ratio on the mesh and in the render.
reference = QtGui.QImage(str(source))
assert not reference.isNull()
aspect = reference.width() / reference.height()
for vertex in scene['meshes'][0]['vertices']:
    vertex[1] /= aspect
runtime = root / 'runtime/native-avx'
for shader in ('', 'DwaBaseMaterial'):
    material['shader'] = shader
    name = 'moonshine' if shader else 'standard'
    path, output = folder/(name+'.rdla'), folder/(name+'.png')
    path.write_text(rdla.scene_text(scene, 480, round(480/aspect), 2, 1))
    with (folder/(name+'.log')).open('w') as log:
        result = subprocess.run([str(runtime/'moonray.exe')] + native.arguments(path, output, 2),
            env=native.environment(runtime), stdout=log, stderr=subprocess.STDOUT,
            timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, name + ' render failed'
    rendered = QtGui.QImage(str(output))
    assert not rendered.isNull()
    colors = {rendered.pixelColor(x,y).rgb() for y in range(rendered.height()) for x in range(rendered.width())}
    assert len(colors) > 100, name + ' output is flat'
    print(output, flush=True)
