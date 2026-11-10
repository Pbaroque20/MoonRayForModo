# python
"""Command-line test: which images a scene's materials ask for, and whether MoonLightIPR finds them. The scene
(PROBE_SCENE, Grass by default) is opened and captured as the preview captures it; for each material, every image path
its layers name and whether that file is there; then the scene is packed for MoonLightIPR at full size (as a Render
packs it), with what packing says and the images it converted. Written to test-results/grass-images/report.json."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\grass-images')
out.mkdir(parents=True, exist_ok=True)
SCENE = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Grass\wildGreen_Patches_bundled.lxo')
result = {'scene': SCENE}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def paths(value, found, where=''):
    """Every string in a material's description that names an image file, with where in it."""
    if isinstance(value, dict):
        for key, inner in value.items():
            paths(inner, found, where + '/' + str(key))
    elif isinstance(value, (list, tuple)):
        for i, inner in enumerate(value):
            paths(inner, found, where + '[%d]' % i)
    elif isinstance(value, str) and value.lower().endswith(('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.exr', '.hdr', '.tga', '.tx')):
        found.append((where, value, pathlib.Path(value).is_file()))


try:
    lx.eval('!scene.open {%s} normal' % SCENE)
    import modo
    from moonray_modo.animation import capture_frame
    snapshot = capture_frame(lx.service.Selection().GetTime(), False, False, float(modo.Scene().fps), preview=True)
    result['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w][:40]
    materials = snapshot.get('materials', {})
    result['materials'] = {}
    items = materials.items() if isinstance(materials, dict) else enumerate(materials)
    for name, material in items:
        found = []
        paths(material, found)
        kinds = sorted({str(layer.get('kind') or layer.get('type') or layer.get('shader') or '?')
                        for layer in (material.get('layers') or []) if isinstance(layer, dict)}) if isinstance(material, dict) else []
        result['materials'][str(name)] = {'images': found, 'layer kinds': kinds,
                                          'shader': material.get('shader') if isinstance(material, dict) else None}
    result['meshes'] = len(snapshot.get('meshes', []))
    result['mesh materials'] = sorted({str(t) for m in snapshot.get('meshes', []) for t in (m.get('materials') or [m.get('material')]) if t is not None})[:40]
    save()
    from moonray_modo import moonlightipr_scene
    try:
        payload, keys, warnings = moonlightipr_scene.pack(dict(snapshot, _full_textures=True), 320, 180, 0.15, (), 16, False, None)
        result['pack'] = {'bytes': len(payload), 'warnings': warnings[:40]}
    except Exception:
        result['pack'] = {'error': traceback.format_exc()[-2000:]}
except Exception:
    result['error'] = traceback.format_exc()[-3000:]
save()
lx.eval('!app.quit')
