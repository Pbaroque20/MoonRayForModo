# python
"""Isolated GUI test: capture, as the plugin hands it to the renderers, a mesh whose material
reads an image wired in its graph. The mesh is a cube turned to show three faces. tools/check_graph_image.py renders the capture."""
import json
import pathlib
import struct
import traceback
import zlib
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/graph-image'
out.mkdir(parents=True, exist_ok=True)
result = {}


def write_png(path, size=256):
    """Red rises with u, blue with v, and one corner is marked, so any turn or flip shows."""
    rows = []
    for y in range(size):
        v = 1 - y / (size - 1)       # the top row of the file is v = 1
        row = bytearray([0])
        for x in range(size):
            u = x / (size - 1)
            green = 255 if (u < .25 and v < .25) else 60
            row += bytes([round(255 * u), green, round(255 * v)])
        rows.append(bytes(row))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


try:
    from moonray_modo import properties, graph_images, material_override, host
    image = out / 'uv-test.png'
    write_png(image)
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for name, value in (('cenX', 0), ('cenY', 0.5), ('cenZ', 0), ('sizeX', 1.0), ('sizeY', 1.0), ('sizeZ', 1.0)):
        lx.eval('tool.attr prim.cube %s %s' % (name, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    mesh = modo.Scene().selectedByType('mesh')[0]
    # Turned so that three faces show.
    lx.eval('transform.channel rot.Y 35.0')
    lx.eval('transform.channel rot.X 25.0')
    result['polygons'] = len(mesh.geometry.polygons)
    result['uv_maps'] = [uv.name for uv in mesh.geometry.vmaps.uvMaps]
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {'roughness': 0.6}}))
    material = modo.Scene().selected[0]
    settings = properties.read(material)
    graph = graph_images.set_image(settings, 'albedo', str(image))
    lx.eval('moonray.material.applyGraph {%s} %s' % (material.id, properties.encode(material_override.synchronize(settings, graph))))
    snapshot = host.snapshot()
    snapshot.pop('_evaluated_data', None)
    for key in list(snapshot):
        if key.startswith('_'):
            snapshot.pop(key)
    (out / 'snapshot.json').write_text(json.dumps(snapshot, default=str))
    result['meshes'] = [{k: (v if k in ('name', 'faces', 'uvs', 'uv_sets', 'vertices', 'material', 'face_materials') else '...') for k, v in m.items()} for m in snapshot['meshes']]
    result['materials'] = list(snapshot['materials'])
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('app.quit'))
