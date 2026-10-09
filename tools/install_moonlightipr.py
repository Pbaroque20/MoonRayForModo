"""Add the built MoonLightIPR GPU preview to the installed kit, with a backup of what it replaces.

Copies only what this branch changed: the session, its device program and the CUDA runtime into
the kit's runtime/moonlightipr folder, the Python modules that route previews to it, and the
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

MODULES = ('native.py', 'persistent.py', 'display.py', 'display_stream.py', 'mesh_reader.py', 'textures.py', 'primitive_attributes.py', 'rdl_import_dialog.py', 'rdl_primitives.py', 'procedurals.py', 'asset_import.py', 'evaluated.py', 'layers.py', 'hair.py', 'materialx_document.py', 'materialx_definitions.py', 'materialx_expand.py', 'materialx_geometry.py', 'materialx_standard.py', 'materialx.py', 'about.py', 'shader_library.py', 'graph.py', 'light_units.py', 'environment_layers.py', 'environments.py', 'modo_daylight.bin', 'modo_daylight.json', 'sun.py', 'daylight.py', 'curve_tubes.py', 'options.py', 'extra_geometry.py', '__init__.py', 'panel.py', 'render.py', 'buffer_cache.py', 'assets.py', 'changes.py', 'scene_digest.py', 'moonshine.py', 'rdla.py', 'lighting.py', 'gradients.py',
           'moonlightipr_scene.py', 'moonlightipr_materials.py', 'moonlightipr_session.py', 'host.py', 'entities.py', 'entity_catalog.json', 'ramp_editor.py', 'materials.py', 'material_editor.py', 'rdl_import.py', 'properties.py',
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
    raise SystemExit('Close Modo before installing MoonLightIPR; nothing was changed')

backup = root / 'backups' / ('before-moonlightipr-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
for name in MODULES:
    if (target / name).is_file():
        (backup / 'python/moonray_modo').mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, backup / 'python/moonray_modo' / name)
for name in KIT_FILES:
    if (kit / name).is_file():
        (backup / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kit / name, backup / name)
if (kit / 'runtime/moonlightipr').is_dir():
    shutil.copytree(kit / 'runtime/moonlightipr', backup / 'runtime/moonlightipr')
subprocess.run([sys.executable, str(root / 'tools/stage_moonlightipr.py'), '--destination', str(kit / 'runtime/moonlightipr')], check=True)
for name in MODULES:
    shutil.copyfile(source / name, target / name)
# The native geometry adapter, where it has been built with the reader for heavy meshes (tools/build_modo_bridge.py
# --output-dir build/modo-geometry-fast --geometry-only --skip-tests). Modo must be closed: it holds the file open.
adapter = root / 'build/modo-geometry-fast/MoonRayGeometry.lx'
if adapter.is_file() and (kit / 'bin').is_dir():
    held = kit / 'bin' / adapter.name
    if held.is_file():
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(held, backup / adapter.name)
    shutil.copyfile(adapter, held)
# The one renderer library rebuilt with more room for a GPU render's outputs (patches/native-windows/cl1-pool-scale.patch),
# where it has been built into runtime/steady-0350-pool. It goes only into a runtime of the build it was made for.
pool = root / 'runtime/steady-0350-pool/librendering_mcrt_common.dll'
made_for = root / 'runtime/steady-0349-candidate/moonray.exe'
if pool.is_file() and made_for.is_file() and (kit / 'runtime/moonray.exe').is_file()         and (kit / 'runtime/moonray.exe').read_bytes() == made_for.read_bytes():
    held = kit / 'runtime' / pool.name
    if held.is_file() and held.read_bytes() != pool.read_bytes():
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(held, backup / pool.name)
        shutil.copyfile(pool, held)
        print('Installed the renderer library with the larger output store')
# The scene reader behind Import RDL Scene, where it has been built (tools/build_rdl_reader.py).
reader = root / 'build/native-avx/bin/modo_rdl_import.exe'
if reader.is_file() and (kit / 'runtime').is_dir():
    held = kit / 'runtime' / reader.name
    if held.is_file():
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(held, backup / reader.name)
    shutil.copyfile(reader, held)
for name in KIT_FILES:
    shutil.copyfile(root / 'kit/MoonRayForModo' / name, kit / name)
# The MoonRay menu: its MoonRay items submenu, dividers between its groups, and plain characters.
# The installed layout.cfg is edited in place, not replaced, so nothing else in it changes.
sys.path.insert(0, str(root / 'tools'))
import moonray_menu
layout = kit / 'layout.cfg'
text = layout.read_bytes().decode('utf-8')
tidied = moonray_menu.rdl_entry(moonray_menu.curve_controls(moonray_menu.tidy(text)))
if 'MoonRayEntityMenu' not in tidied:
    print('Could not find where to add "Add MoonRay Item" in', layout)
if tidied != text:
    backup.mkdir(parents=True, exist_ok=True)
    (backup / 'layout.cfg').write_bytes(text.encode('utf-8'))
    layout.write_bytes(tidied.encode('utf-8'))
print('Installed MoonLightIPR into', kit)
print('Backup:', backup)
