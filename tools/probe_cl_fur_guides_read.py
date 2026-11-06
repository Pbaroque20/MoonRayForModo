# python
"""Command line: the kit reading a Fur material's guides out of a scene (extra_geometry.fur_guides), as the preview
and renders do. Opens MOONRAY_PROBE_SCENE (test-results/fur-guides/guides.lxo: guides on the base surface), reads its
fur with each guide mode, then with the guides in a mesh of their own, and writes how many guides were found, the
fibres grown and their reach, and the notices. Writes test-results/fur-guides-read.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    from moonray_modo import extra_geometry, properties, fur, fur_native
    layer = next(iter(scene.items('furMaterial')))
    skin = next(i for i in scene.items('mesh') if i.name == 'Skin')
    found = {}
    original = extra_geometry.fur_guides

    def counted(*a, **k):
        guides = original(*a, **k)
        found['guides'] = len(guides)
        found['first'] = [round(v, 3) for v in guides[0][-1]] if guides else None
        return guides
    extra_geometry.fur_guides = counted

    def reading(label):
        warnings = []
        entries = extra_geometry.collect(scene, warnings, properties.scene_settings().get('production', {}))
        furry = [e for e in entries if '|fur|' in str(e.get('identity', ''))]
        tops = []
        for entry in furry:
            if entry.get('fur_file'):
                vertices, counts, _, _, fibres = fur_native.read(pathlib.Path(entry['fur_file']))
                tops.append(max(v[1] for v in vertices) if vertices else 0.0)
                tops.append(max(v[0] for v in vertices) if vertices else 0.0)
            elif entry.get('vertices'):
                tops.append(max(v[1] for v in entry['vertices']))
        result[label] = {'guides': found.get('guides'), 'tip_of_first_guide': found.get('first'), 'entries': len(furry),
                         'native': any(e.get('fur_file') for e in furry), 'highest_and_furthest': [round(v, 3) for v in tops[:2]],
                         'warnings': [w for w in warnings if 'Fur' in w or 'fur' in w][:4]}
        found.clear()
    for mode in ('none', 'shape', 'range', 'normal'):
        layer.channel('guides').set(mode)
        reading('surface-' + mode)
    guides = next((i for i in scene.items('mesh') if i.name == 'Guides'), None)
    if guides is None:
        guides = scene.addMesh('Guides')
        with skin.geometry as geo:
            pass
    layer.channel('guideSurf').set(0)
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('fur.setMesh name:{%s}' % guides.name)
    layer.channel('guides').set('shape')
    reading('item-shape-empty' if not len(guides.geometry.polygons) else 'item-shape')
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\fur-guides-read.json').write_text(json.dumps(result, indent=1, default=str))
