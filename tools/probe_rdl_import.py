# python
"""Isolated GUI test: import MoonRay scenes into Modo and write each back out as the plugin would render it.

PROBE_RDL names a folder of documents made by tools/check_rdl_import.py --documents (the scenes as MoonRay's reader
gave them). Each is planned and applied in a scene of its own; what Modo then holds is counted, and the scene the
plugin would hand MoonRay is written beside it, for tools/check_rdl_import.py --compare to render against the original."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
folder = pathlib.Path(os.environ.get('PROBE_RDL', str(root / 'test-results/rdl-import')))
result = {}


def save():
    (folder / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import host, properties, rdl_import, rdla, scene_settings
    for source in sorted(folder.glob('*.document.json')):
        name = source.name[:-len('.document.json')]
        entry = result[name] = {}
        try:
            lx.eval('!scene.new')
            document = json.loads(source.read_text(encoding='utf-8'))
            data = rdl_import.plan(document, document['_path'])
            entry['plan'] = rdl_import.summary(data)
            entry['said'] = rdl_import.apply(data).splitlines()[0]
            scene = modo.Scene()
            entry['items'] = {kind: len(scene.items(kind, superType=False)) for kind in ('mesh', 'meshInst', 'camera', 'mask')}
            entry['moonray_items'] = sorted(item.type for item in scene.items() if item.type.startswith('moonray.'))
            entry['materials'] = sorted(item.type for item in scene.items() if properties.is_material(item) and item.type != 'advancedMaterial')
            snapshot = host.snapshot()
            entry['warnings'] = snapshot.get('warnings', [])
            values = scene_settings.complete(properties.scene_settings())
            snapshot.update(render_settings=values['render'], aovs=values['aovs'], custom_aovs=[], production=values['production'],
                            asset_settings=values['asset_settings'], environments=[] if not values['modo_environment'] else snapshot.get('environments', []))
            from moonray_modo.extra_geometry import attach
            attach(snapshot, values['production'])
            width = 400
            height = max(1, round(width * scene.renderItem.channel('resY').get() / max(1, scene.renderItem.channel('resX').get())))
            entry['size'] = [width, height]
            (folder / (name + '.imported.rdla')).write_text(rdla.scene_text(snapshot, width, height, 4, 0.0, str(folder / (name + '.imported.exr'))), encoding='utf-8')
        except Exception:
            entry['error'] = traceback.format_exc()
            try:
                entry['stacks'] = {tag: [[child.get('native_shader'), child.get('layer_opacity'), len(child.get('layers', [])), len(child.get('material_groups', []))]
                                         for child in material.get('material_stack', [material])] for tag, material in host.snapshot()['materials'].items()}
            except Exception:
                pass
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
