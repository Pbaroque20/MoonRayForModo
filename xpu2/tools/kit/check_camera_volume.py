"""XPU2's camera-only update with a volume (an unmapped one, a fog) against a full preparation, through the kit's own
session, headless with Modo's Python: the scene rendered, the camera moved (a delta), the update's picture beside the
moved scene rendered whole by a fresh session, and two fresh renders for the noise floor (oiiotool --diff)."""
import json
import os
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
namespace = {'__file__': str(here / 'check_fast_paths.py')}
source = (here / 'check_fast_paths.py').read_text(encoding='utf-8')
# The helpers alone (session, scene text, pictures): up to where check_fast_paths starts its own run.
exec(compile(source[:source.index('base = multiline(SOURCE)')], 'check_fast_paths.py', 'exec'), namespace)
multiline, render, kept, diff, Session = (namespace[n] for n in ('multiline', 'render', 'kept', 'diff', 'Session'))
store, OUT = namespace['store'], namespace['OUT']

text = Path(sys.argv[1]).read_text(encoding='utf-8').replace('"OUTPUT"', '"beauty.exr"')


def camera_at(scene, x):
    return re.sub(r'(PerspectiveCamera\("/camera"\) \{\n  \["node_xform"\]=Mat4\([^)]*?,)([-0-9.e]+)(,[-0-9.e]+,[-0-9.e]+,1\))',
                  lambda m: m.group(1) + '%g' % x + m.group(3), scene, count=1)


base = multiline(text)
moved = camera_at(base, 0.35)
assert moved != base, 'the camera was not moved'
result = {}
try:
    live = Session()
    r, lines = render(live, base, 1)
    result['base'] = {'ready': r['ready'], 'failed': r['failed']}
    r, lines = render(live, moved, 2)
    result['camera_update'] = {'ready': r['ready'], 'failed': r['failed'],
                               'lines': [l for l in r['log'].splitlines() if 'camera' in l or 'alone' in l][-4:]}
    update = kept(live, 'camera-update')
    live.close()
    pictures = {}
    for name, scene in (('camera-whole', moved), ('camera-whole-2', moved), ('base-whole', base)):
        fresh = Session()
        render(fresh, scene, 1)
        pictures[name] = kept(fresh, name)
        fresh.close()
    result['camera: update vs whole'] = diff(update, pictures['camera-whole'])
    result['noise floor: whole vs whole'] = diff(pictures['camera-whole'], pictures['camera-whole-2'])
    result['a real change: moved vs base'] = diff(pictures['camera-whole'], pictures['base-whole'])
except Exception:
    import traceback
    result['error'] = traceback.format_exc()
finally:
    store.remove('xpu2/renderer')
    store.sync()
Path(sys.argv[2]).write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
