"""seed_refcache.py: the MoonRay references already rendered (every <case>-moonray.exr and -moonray1.exr beside the
scene that made it and its harness log) into the reference cache, keyed as feature_compare.py keys them (the mode read
from the harness's protocol log; a scene newer than its picture, or one without a log, is skipped)."""
import re
import sys
from pathlib import Path

S = Path(__file__).resolve().parent
sys.path.insert(0, str(S))
import runq  # noqa: E402

MOONRAY = Path(r'C:\Users\Raphael Tobar\AppData\Roaming\Luxology\Kits\MoonRayForModo\runtime\moonray.exe')
seeded = skipped = 0
for exr in sorted(S.glob('*/*-moonray*.exr')):
    m = re.match(r'(.+)-(moonray1?)\.exr$', exr.name)
    if not m:
        continue
    scene = exr.with_suffix('.rdla')
    log = exr.parent / (exr.stem + '-harness') / 'protocol.log'
    if not scene.is_file() or not log.is_file() or scene.stat().st_mtime > exr.stat().st_mtime:
        skipped += 1
        continue
    text = log.read_text(encoding='utf-8', errors='replace')
    mode = 'scalar' if 'Executing a scalar render' in text else 'vectorized' if 'Executing a vectorized render' in text else None
    if not mode:
        skipped += 1
        continue
    scene_text = scene.read_text(encoding='utf-8')
    frame = '1' if m.group(2) == 'moonray1' else '0'
    key = runq.reference_key(scene_text, exr, frame, mode, MOONRAY)
    if not (runq.CACHE / (key + '.exr')).exists():
        runq.store(key, exr)
        seeded += 1
print('seeded', seeded, 'skipped', skipped)
