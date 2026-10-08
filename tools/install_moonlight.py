"""Add the built MoonLight GPU preview to the installed kit, with a backup of what it replaces.

Copies only what this branch changed: the session, its device program and the CUDA runtime into
the kit's runtime/moonlight folder, the Python modules that route previews to it, and the
MoonRay items (their module, schema, commands and forms). The rest of the installed kit is left
as it is. Close Modo first; a running Modo keeps the old modules
loaded and the old session open.
"""
import csv
from datetime import datetime
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys

MODULES = ('about.py', 'shader_library.py', 'graph.py', 'light_units.py', 'environment_layers.py', 'environments.py', 'modo_daylight.bin', 'modo_daylight.json', 'sun.py', 'daylight.py', 'curve_tubes.py', 'options.py', 'extra_geometry.py', '__init__.py', 'panel.py', 'render.py', 'buffer_cache.py', 'assets.py', 'changes.py', 'scene_digest.py', 'moonshine.py', 'rdla.py', 'lighting.py', 'gradients.py',
           'moonlight_scene.py', 'moonlight_materials.py', 'moonlight_session.py', 'host.py', 'entities.py', 'entity_catalog.json', 'ramp_editor.py', 'materials.py', 'material_editor.py', 'rdl_import.py', 'properties.py',
           'panel_tools.py', 'preferences.py', 'scene_settings.py', 'focus.py', 'progress.py', 'node_editor.py', 'node_widgets.py', 'incremental.py', 'graph_images.py', 'property_notifications.py', 'camera_choice.py', 'graph_bake.py', 'nodes.py', 'coordinates.py', 'animation.py', 'package_sequence.py')
# Files outside the Python package, relative to the kit: the commands and forms of the MoonRay
# items and of native materials.
KIT_FILES = ('THIRD_PARTY.txt', 'index.cfg', 'lxserv/moonray_entities.py', 'entities.cfg', 'lxserv/moonray_material_forms.py', 'material_forms.cfg',
             'lxserv/moonray_render_settings.py', 'render_settings.cfg', 'lxserv/moonray_commands.py',
             'lxserv/moonray_material_properties.py', 'lxserv/moonray_moonshine_layer.py', 'shader_layers.cfg', 'lxserv/moonray_camera.py')

root = Path(__file__).resolve().parents[1]
source = root / 'kit/MoonRayForModo/python/moonray_modo'
kit = Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo'
target = kit / 'python/moonray_modo'
if not target.is_dir():
    raise SystemExit('MoonRayForModo is not installed in ' + str(kit))
processes = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq modo.exe', '/FO', 'CSV', '/NH'],
                                    text=True, creationflags=subprocess.CREATE_NO_WINDOW)
if any(row and row[0].lower() == 'modo.exe' for row in csv.reader(io.StringIO(processes))):
    raise SystemExit('Close Modo before installing MoonLight; nothing was changed')

backup = root / 'backups' / ('before-moonlight-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
for name in MODULES:
    if (target / name).is_file():
        (backup / 'python/moonray_modo').mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, backup / 'python/moonray_modo' / name)
for name in KIT_FILES:
    if (kit / name).is_file():
        (backup / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kit / name, backup / name)
if (kit / 'runtime/moonlight').is_dir():
    shutil.copytree(kit / 'runtime/moonlight', backup / 'runtime/moonlight')
subprocess.run([sys.executable, str(root / 'tools/stage_moonlight.py'), '--destination', str(kit / 'runtime/moonlight')], check=True)
for name in MODULES:
    shutil.copyfile(source / name, target / name)
for name in KIT_FILES:
    shutil.copyfile(root / 'kit/MoonRayForModo' / name, kit / name)
# The MoonRay menu: its MoonRay items submenu, dividers between its groups, and plain characters.
# The installed layout.cfg is edited in place, not replaced, so nothing else in it changes.
sys.path.insert(0, str(root / 'tools'))
import moonray_menu
layout = kit / 'layout.cfg'
text = layout.read_bytes().decode('utf-8')
tidied = moonray_menu.curve_controls(moonray_menu.tidy(text))
if 'MoonRayEntityMenu' not in tidied:
    print('Could not find where to add "Add MoonRay Item" in', layout)
if tidied != text:
    backup.mkdir(parents=True, exist_ok=True)
    (backup / 'layout.cfg').write_bytes(text.encode('utf-8'))
    layout.write_bytes(tidied.encode('utf-8'))
print('Installed MoonLight into', kit)
print('Backup:', backup)
