# python
"""Command-line test: VDB sequences and blackbody fire on the kit's own MoonRay items, in Modo. A VDB shape and a VDB volume
made as Load VDB File makes them, the shape's file one frame of an EmberGen sequence (MOONRAY_PROBE_VDB), set to
Sequence, blackbody colour on with the temperature grid; at a few frames, what the scene hands MoonRay: the file, the
emission grid, and whether the volume is there. Writes test-results/cl-export/vdb-fire.json and, at frame 40,
vdb-fire.rdla."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    import modo
    from moonray_modo import entities, host, rdla
    scene = modo.Scene()
    prefix = entities.CHANNEL_PREFIX
    shape = scene.addItem(entities.item_type('VdbGeometry'), name='Explosion')
    volume = scene.addItem(entities.item_type('VdbVolume'), name='Fire')
    chosen = os.environ['MOONRAY_PROBE_VDB'].replace('\\', '/')
    for key, value in (('model', chosen), ('emission_grid', 'temperature'), ('density_grid', 'density'), ('modo_volume', volume.name),
                       ('static', 0), ('modo_blackbody', 1), ('modo_blackbody_kelvin', 3000.0)):
        shape.channel(prefix + key).set(value)
    result['channels'] = {key: shape.channel(prefix + key).get() for key in ('model', 'static', 'modo_blackbody', 'modo_blackbody_kelvin', 'emission_grid')}
    fps = float(scene.fps)
    for frame in (-5, 0, 40, 125, 200):
        lx.eval('select.time %s' % (frame / fps))
        held = host.snapshot()
        found = [e for e in entities.checked(held) if e['class'] == 'VdbGeometry']
        result['frame %d' % frame] = [{'model': e['parameters'].get('model'), 'emission_grid': e['parameters'].get('emission_grid')} for e in found] or 'hidden'
        if frame == 40:
            text = rdla.scene_text(held, 320, 200, 4, 0.15, 'OUTPUT')
            (out / 'vdb-fire.rdla').write_text(text, encoding='utf-8')
            result['rdla_vdb_lines'] = [line.strip()[:300] for line in text.splitlines() if 'VdbGeometry(' in line or '"model"' in line or 'emission_grid' in line][:6]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'vdb-fire.json').write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')
lx.out('vdb fire probe written')
