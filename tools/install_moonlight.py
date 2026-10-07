"""Add the built MoonLight GPU preview to the installed kit, with a backup of what it replaces.

Copies only MoonLight's own files: the session, its device program and the CUDA runtime into
the kit's runtime/moonlight folder, and the Python modules that route previews to it. The rest
of the installed kit is left as it is. Close Modo first; a running Modo keeps the old modules
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

MODULES = ('__init__.py', 'panel.py', 'render.py', 'buffer_cache.py', 'assets.py', 'changes.py', 'scene_digest.py',
           'moonlight_scene.py', 'moonlight_materials.py', 'moonlight_session.py')

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
if (kit / 'runtime/moonlight').is_dir():
    shutil.copytree(kit / 'runtime/moonlight', backup / 'runtime/moonlight')
subprocess.run([sys.executable, str(root / 'tools/stage_moonlight.py'), '--destination', str(kit / 'runtime/moonlight')], check=True)
for name in MODULES:
    shutil.copyfile(source / name, target / name)
print('Installed MoonLight into', kit)
print('Backup:', backup)
