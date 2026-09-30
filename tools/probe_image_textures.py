# python
"""Create a UV image-layer fixture in an isolated Modo process."""
import json
from pathlib import Path
import sys
import traceback
import lx
import modo
from PySide2 import QtGui

root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
output = root / 'test-results/textures'
output.mkdir(parents=True, exist_ok=True)
try:
    sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
    from moonray_modo import host, rdla
    image = QtGui.QImage(64, 64, QtGui.QImage.Format_RGB32)
    for y in range(64):
        for x in range(64):
            image.setPixelColor(x, y, QtGui.QColor(240, 15, 15) if x < 32 else QtGui.QColor(15, 240, 15))
    source = output / 'two colors.png'
    assert image.save(str(source))
    scene = modo.Scene()
    scene.renderCamera.position.set((0, 0, 0))
    scene.renderCamera.rotation.set((0, 0, 0))
    mesh = scene.addMesh('Texture test')
    geometry = mesh.geometry
    for p in ((-1,-1,-3),(1,-1,-3),(1,1,-3),(-1,1,-3)):
        geometry.vertices.new(p)
    geometry.polygons.new((0,1,2,3))
    geometry.polygons[0].materialTag = 'texture_test'
    geometry.setMeshEdits()
    geometry = mesh.geometry
    unused = geometry.vmaps.addUVMap('AAA_Unused')
    for i in range(4):
        unused[i] = (.1, .1)
    geometry.setMeshEdits()
    geometry = mesh.geometry
    uv = geometry.vmaps.addUVMap('PaintUV')
    for i, value in enumerate(((0,0),(1,0),(1,1),(0,1))):
        uv[i] = value
    geometry.setMeshEdits()
    lx.eval('item.create mask')
    mask = scene.selected[0]
    mask.setParent(scene.renderItem)
    mask.channel('ptyp').set('Material')
    mask.channel('ptag').set('texture_test')
    material = scene.addItem('advancedMaterial')
    material.setParent(mask)
    material.channel('diffAmt').set(1)
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    layer.setParent(mask, 0)
    layer.channel('effect').set('diffCol')
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('uv')
    locator.channel('uvMap').set('PaintUV')
    lx.eval('item.create videoStill')
    clip = scene.selected[0]
    clip.channel('filename').set(str(source))
    clip.itemGraph('shadeLoc').connectInput(layer)
    snapshot = host.snapshot()
    (output / 'snapshot.json').write_text(json.dumps(snapshot, indent=2))
    assert snapshot['materials']['texture_test']['textures']['diffCol']['uv_map'] == 'PaintUV'
    assert snapshot['meshes'][0]['uvs'][2] == [1, 1]
    layer.channel('opacity').set(.5)
    blended = host.snapshot()
    assert blended['materials']['texture_test']['layers'][0]['opacity'] == .5
    layer.channel('opacity').set(1)
    locator.channel('uvMap').set('MissingMap')
    try:
        host.snapshot()
    except ValueError as exc:
        assert 'missing UV' in str(exc)
    else:
        raise AssertionError('Missing UV map silently accepted')
    locator.channel('uvMap').set('PaintUV')
    (output / 'snapshot.json').write_text(json.dumps(snapshot, indent=2))
    (output / 'scene.rdla').write_text(rdla.scene_text(snapshot, 96, 96, 2, 1))
    (output / 'host.json').write_text(json.dumps({'passed': True, 'warnings': snapshot['warnings']}))
except Exception:
    (output / 'host.json').write_text(json.dumps({'passed': False, 'error': traceback.format_exc()}))
    raise
