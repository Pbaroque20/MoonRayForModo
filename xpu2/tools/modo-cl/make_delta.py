"""make_delta.py <old.rdla> <new.rdla> <out.rdla>: the change from one scene's text to another's as the kit's loaded
session gets it (the installed kit's scene_delta.difference), written for the harness's --delta."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['APPDATA']) / 'Luxology' / 'Kits' / 'MoonRayForModo' / 'python'))
import importlib.util

spec = importlib.util.spec_from_file_location('scene_delta', str(Path(os.environ['APPDATA']) / 'Luxology' / 'Kits' / 'MoonRayForModo' /
                                                                  'python' / 'moonray_modo' / 'scene_delta.py'))
scene_delta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene_delta)
old, new, out = (Path(a) for a in sys.argv[1:4])
delta = scene_delta.difference(old.read_text(encoding='utf-8'), new.read_text(encoding='utf-8'))
if delta is None:
    print('no delta: the kit would reload the scene whole')
    sys.exit(1)
out.write_text(delta, encoding='utf-8')
print('delta', len(delta), 'characters ->', out)
