# python
"""Command line: the kit reading a Fur material's vector map and width map out of a scene (extra_geometry), as the
preview and renders do. Opens MOONRAY_PROBE_SCENE (test-results/fur-maps/maps.lxo: FurVector, FurWidth on the patch),
reads its fur with no map, the vector map, and the width map, with the kit's own runtime's grower or Python's, and
writes the fibres grown, how high and how far over they reach, their radii and the notices. Writes
test-results/fur-maps-read.json."""
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
    from moonray_modo import extra_geometry, properties, fur_native
    layer = next(iter(scene.items('furMaterial')))
    if os.environ.get('MOONRAY_PROBE_GROWER'):
        grower = pathlib.Path(os.environ['MOONRAY_PROBE_GROWER'])
        fur_native.program = lambda runtime=None: grower

    def reading(label):
        warnings = []
        entries = [e for e in extra_geometry.collect(scene, warnings, properties.scene_settings().get('production', {}))
                   if '|fur|' in str(e.get('identity', ''))]
        found = {'entries': len(entries), 'native': any(e.get('fur_file') for e in entries),
                 'warnings': [w for w in warnings if 'ur' in w][:3]}
        vertices, radii = [], []
        for entry in entries:
            if entry.get('fur_file'):
                v, counts, r, _, _ = fur_native.read(pathlib.Path(entry['fur_file']))
                vertices += v
                radii += r
            else:
                vertices += entry.get('vertices') or []
                radii += entry.get('radii') or [entry.get('radius')] * len(entry.get('vertices') or [])
        if vertices:
            found.update(points=len(vertices), highest=round(max(p[1] for p in vertices), 3),
                         furthest_x=round(max(p[0] for p in vertices), 3),
                         radius_range_mm=[round(1000 * min(radii), 4), round(1000 * max(radii), 4)] if radii else None)
        result[label] = found
    layer.channel('vectorMap').set('')
    layer.channel('widthMap').set('')
    reading('plain')
    layer.channel('vectorMap').set('FurVector')
    reading('vector')
    layer.channel('vectorMap').set('')
    layer.channel('widthMap').set('FurWidth')
    reading('width')
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\fur-maps-read.json').write_text(json.dumps(result, indent=1, default=str))
