# python
"""Command line: what Modo's own renderer makes of a Blob. A mesh of 27 points in a loose grid as the particle source,
linked to a Blob item (radius 0.45), a Sprite beside it on a second cloud, a camera and a light; rendered with Modo's
renderer (render.animation, one frame) to test-results/blob-scene/modo.exr, and the scene saved as blob_test.lxo for
the kit's work on blobs and particles. Writes test-results/blob-scene/report.json."""
import json
import pathlib
import traceback
import lx
import modo


out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\blob-scene')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def cloud(scene, name, offset):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        for x in range(3):
            for y in range(3):
                for z in range(3):
                    geo.vertices.new((offset + x * 0.6 + 0.07 * ((y + z) % 2), 0.4 + y * 0.6, z * 0.6 - 0.6))
    return mesh


def render():
    try:
        target = out / 'modo.exr'
        lx.eval('!render.animation {%s} openexr' % (out / 'modo'))
        report['rendered'] = sorted(p.name for p in out.glob('modo*'))
    except Exception:
        report['render error'] = traceback.format_exc()
    save()



try:
    scene = modo.Scene()
    blob_cloud = cloud(scene, 'Blob points', -2.2)
    sprite_cloud = cloud(scene, 'Sprite points', 0.6)
    blob = scene.addItem('blob', name='Blob')
    sprite = scene.addItem('sprite', name='Sprite')
    # The particle source, as Modo's Particle Source property sets it: the volume item selected, volume.particle.
    for source, item in ((blob_cloud, blob), (sprite_cloud, sprite)):
        lx.eval('select.item {%s} set' % item.id)
        lx.eval('volume.particle {%s}' % source.id)
    graph = lx.object.ItemGraph(scene.GraphLookup('particle'))
    blob_raw = lx.object.Item(blob)
    report['blob graph'] = {'forward': [lx.object.Item(graph.FwdByIndex(blob_raw, i)).UniqueName() for i in range(graph.FwdCount(blob_raw))],
                            'reverse': [lx.object.Item(graph.RevByIndex(blob_raw, i)).UniqueName() for i in range(graph.RevCount(blob_raw))]}
    blob.channel('radius').set(0.45)
    sprite.channel('radius').set(0.45)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        corners = [geo.vertices.new(p) for p in ((-6, 0, -6), (6, 0, -6), (6, 0, 6), (-6, 0, 6))]
        geo.polygons.new([corners[0], corners[3], corners[2], corners[1]])
    camera = scene.renderCamera
    camera.position.set((0.0, 2.2, 6.5))
    camera.rotation.set((-0.22, 0.0, 0.0))
    render_item = scene.renderItem
    for name, value in (('resX', 960), ('resY', 540), ('first', 1), ('last', 1)):
        render_item.channel(name).set(value)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'blob_test.lxo'))
    report['saved'] = str(out / 'blob_test.lxo')
    save()
    render()
except Exception:
    report['error'] = traceback.format_exc()
    save()
lx.eval('!app.quit')
