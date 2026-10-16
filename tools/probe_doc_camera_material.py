# python
"""Scenes for the docs, saved as the plugin reads them for a render (host.snapshot), to be rendered in MoonRay after.

A box is made, given an orange MoonRay material whole, and then a second box is made in the same mesh, as new
geometry. The scene is saved as seen through the Modo render camera; the camera is then converted into a MoonRay
perspective camera, which is chosen to render through, and the scene saved again."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/doc-camera-material'
out.mkdir(parents=True, exist_ok=True)
result = {}


def box(mesh, x, size=1.0):
    corners = [(x + a * size, b * size, c * size - size / 2) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    with mesh.geometry as geometry:
        points = [geometry.vertices.new(p) for p in corners]
        for face in faces:
            geometry.polygons.new([points[i] for i in face])


try:
    from moonray_modo import camera_choice, camera_convert, host, materials
    scene = modo.Scene()
    ground = scene.addMesh('Ground')
    with ground.geometry as geometry:
        points = [geometry.vertices.new(p) for p in ((-6, 0, -6), (6, 0, -6), (6, 0, 6), (-6, 0, 6))]
        geometry.polygons.new(points[::-1])
    mesh = scene.addMesh('Boxes')
    box(mesh, -1.6)
    scene.select(mesh)
    materials.assign(color=[0.9, 0.4, 0.1])
    # New geometry, made after the material was assigned.
    box(mesh, 0.6, 1.2)
    camera = scene.renderCamera
    placed = modo.LocatorSuperType(camera)
    placed.position.set((0.3, 2.2, 5.5))
    placed.rotation.set((-0.33, 0.0, 0.0))
    result['tags'] = sorted(set(mesh.geometry.polygons[i].materialTag for i in range(len(mesh.geometry.polygons))))
    (out / 'modo_camera.json').write_text(json.dumps(host.snapshot(), default=str))
    made = camera_convert.convert(camera, 'PerspectiveCamera')
    camera_choice.choose(made.id)
    (out / 'moonray_camera.json').write_text(json.dumps(host.snapshot(), default=str))
    result['converted'] = made.name
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
