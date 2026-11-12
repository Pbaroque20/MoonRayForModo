# python
"""Headless: what MoonLightIPR's motion vector should be for probe_moonlightipr_motion_vectors.py's scene (a cube sliding
along X, 0 at frame 0 and 10 at frame 2, seen at frame 1, the camera at (5, 0, 20)): the scene captured with the
shutter's ends as the preview captures it, the cube's middle at each end through the camera's lens, in pixels of a
480 x 270 picture. Writes test-results/moonlightipr-motion/expected.json."""
import json
import math
import traceback
import lx

out = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-motion\expected.json'
result = {}
try:
    import modo
    scene = modo.Scene()
    cube = scene.addMesh('Slider')
    with cube.geometry as geometry:
        corners = [geometry.vertices.new((x, y, z)) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([corners[i] for i in face])
    fps = float(scene.fps)
    for frame, x in ((0, 0.0), (2, 10.0)):
        cube.position.x.set(x, time=frame / fps, key=True)
    camera = scene.renderCamera
    for name, value in (('pos.X', 5), ('pos.Y', 0), ('pos.Z', 20), ('rot.X', 0), ('rot.Y', 0)):
        lx.eval('select.item {%s} set' % camera.id)
        lx.eval('transform.channel %s %s' % (name, value))
    for name, value in (('resX', 480), ('resY', 270)):
        scene.renderItem.channel(name).set(value)
    lx.eval('select.time %s' % (1 / fps))
    from moonray_modo import animation
    snap = animation.capture_frame(1 / fps, False, True, fps, preview=True)
    steps = snap.get('motion_steps')
    cam = snap['camera']
    result['steps'] = steps
    result['camera'] = {k: cam.get(k) for k in ('focal_mm', 'film_mm', 'shutter_length', 'shutter_offset', 'matrix')}
    mesh = next(m for m in snap['meshes'] if 'Slider' in str(m.get('name')))
    result['matrix_open'] = (mesh.get('matrix') or [])[12:15]
    result['matrix_close'] = (mesh.get('matrix_close') or [])[12:15]
    # The cube's middle at each end, seen through a pinhole with the camera's film and focal length, looking down -Z.
    width, height = 480, 270
    focal, film = float(cam['focal_mm']), float(cam['film_mm'])
    eye = cam['matrix'][12:15]

    def pixel(p):
        d = [p[k] - eye[k] for k in range(3)]
        depth = -d[2]
        # Modo's film width is the picture's width: half of it at the focal length, in the image plane.
        across = d[0] / depth * focal / (film / 2.0)
        return (across + 1.0) * 0.5 * width
    if result['matrix_open'] and result['matrix_close']:
        a, b = pixel(result['matrix_open']), pixel(result['matrix_close'])
        result['expected_across'] = round(b - a, 3)
        # And the front face's middle (z = +1), which most of the pixels seen are.
        a1 = pixel([result['matrix_open'][0], result['matrix_open'][1], 1.0])
        b1 = pixel([result['matrix_close'][0], result['matrix_close'][1], 1.0])
        result['expected_across_front'] = round(b1 - a1, 3)
except Exception:
    result['error'] = traceback.format_exc()
open(out, 'w').write(json.dumps(result, indent=1, default=str))
