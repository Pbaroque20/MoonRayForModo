"""A headless Modo profile (modo_cl) with the private XPU2 kit as installed in the user's Modo, for exporting the
user's scenes as that kit writes them. The kit's runtimes are linked (junctions), not copied. Git-ignored place."""
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_PROFILE = Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gui-profile')
KIT = Path(os.environ['APPDATA']) / 'Luxology' / 'Kits' / 'MoonRayForModo'
PROFILE = HERE / 'profile'
LINKED = ('runtime', 'runtime-xpu2')

if not PROFILE.exists():
    shutil.copytree(SOURCE_PROFILE, PROFILE, ignore=shutil.ignore_patterns('MoonRayForModo', 'commandLog*'))
target = PROFILE / 'Configs' / 'MoonRayForModo'
if target.exists():
    for name in LINKED:
        link = target / name
        if link.exists():
            subprocess.run(['cmd', '/c', 'rmdir', str(link)], check=True)  # a junction: the link alone
    shutil.rmtree(target)
shutil.copytree(KIT, target, ignore=shutil.ignore_patterns('__pycache__', *LINKED))
for name in LINKED:
    if (KIT / name).is_dir():
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(target / name), str(KIT / name)], check=True, capture_output=True)
print('profile ready:', PROFILE)
