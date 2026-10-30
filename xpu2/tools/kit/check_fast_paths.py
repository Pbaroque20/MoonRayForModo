"""XPU2's placement-only and light-only updates against a full preparation, through the kit's own session (persistent.
Session), headless with Modo's Python: a scene rendered, then one mesh moved (a delta: placements alone), then a light
changed (a delta: lights alone), each update's picture beside the same scene rendered whole by a fresh session, and
two fresh renders of a scene beside each other for the noise floor (oiiotool --diff). Writes the result to argv[2]."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

for d in (r"C:\Program Files\Modo16.1v9\modo", r"C:\Program Files\Modo16.1v9\modo\resrc\python3kit\extra64"):
    os.add_dll_directory(d)
os.environ['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
KIT = Path(r'C:\Users\Raphael Tobar\MoonRayForModo-xpu2\test-results\xpu2-kit\MoonRayForModo')
sys.path.insert(0, str(KIT / 'python'))
from PySide2 import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication([])
from moonray_modo import native  # noqa: E402
from moonray_modo.persistent import Session  # noqa: E402

store = QtCore.QSettings('MoonRayForModo', 'TestPreview')
store.setValue('xpu2/renderer', 'xpu2')
store.sync()
OUT = Path(sys.argv[2]).parent
SOURCE = Path(sys.argv[1]).read_text(encoding='utf-8')


def split_top(body):
    parts, depth, start, quoted = [], 0, 0, False
    for i, c in enumerate(body):
        if c == '"' and (i == 0 or body[i - 1] != '\\'):
            quoted = not quoted
        if quoted:
            continue
        if c in '({[':
            depth += 1
        elif c in ')}]':
            depth -= 1
        elif c == ',' and depth == 0:
            parts.append(body[start:i].strip())
            start = i + 1
    if body[start:].strip():
        parts.append(body[start:].strip())
    return parts


def multiline(text):
    """The scene's objects one attribute a line, as the kit writes them (scene_delta.difference reads them so)."""
    out = []
    for line in text.splitlines():
        m = re.match(r'^(\w+(?:\("[^"]*"\))?)\s*\{\s*(.*)\}\s*$', line)
        if not m:
            out.append(line)
            continue
        out.append(m.group(1) + ' {')
        out.extend('  ' + part + ',' for part in split_top(m.group(2)))
        out.append('}')
    return '\n'.join(out) + '\n'


def with_ball_at(text, x, degrees=0.0):
    """/ball1 placed x along X, then turned by degrees about Y through the origin (its node_xform, row vectors), the rest
    as it is. XPU2_CHECK_ANGLE: the moves turn it as well (a placement's rotation, not its translation alone)."""
    import math
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    xform = 'Mat4(%g,0,%g,0, 0,1,0,0, %g,0,%g,0, %g,0,%g,1)' % (c, -s, s, c, x * c, -x * s)
    return re.sub(r'(RdlMeshGeometry\("/ball1"\) \{\n)', r'\1  ["node_xform"] = ' + xform + r',\n', text, count=1)


ANGLE = float(os.environ.get('XPU2_CHECK_ANGLE', '0'))


def with_key(text, intensity):
    return re.sub(r'(RectLight\("/key"\) \{\n(?:  .*\n)*?)  \["intensity"\]=[^\n]*\n', r'\1  ["intensity"]=%g,\n' % intensity, text, count=1)


def render(session, text, generation, seconds=150):
    record = {'ready': [], 'failed': [], 'log': ''}
    hooks = [(session.ready, lambda g: record['ready'].append(g)), (session.failed, lambda s: record['failed'].append(s)),
             (session.output, lambda s: record.__setitem__('log', record['log'] + s))]
    for signal, slot in hooks:
        signal.connect(slot)
    session.submit(text, Path(native.default_runtime()), 4, 'xpu', generation, 32)
    end = time.monotonic() + seconds
    while time.monotonic() < end and generation not in record['ready'] and not record['failed']:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)
    for signal, slot in hooks:
        signal.disconnect(slot)
    lines = [l for l in record['log'].splitlines() if 'XPU2' in l and ('alone' in l or 'prepared' in l or 'GPU scene' in l or 'changed' in l or 'debug' in l or 'within' in l or "CPU's scene" in l)]
    return record, lines


def kept(session, name):
    target = OUT / (name + '.exr')
    shutil.copyfile(Path(session.root) / 'beauty.exr', target)
    return target


def diff(a, b):
    tool = Path(native.default_runtime()) / 'oiiotool.exe'
    text = subprocess.run([str(tool), str(a), str(b), '--diff'], capture_output=True, text=True).stdout
    mean = re.search(r'Mean error = ([0-9.e+-]+)', text)
    worst = re.search(r'Max error\s*=\s*([0-9.e+-]+)', text)
    return {'mean': float(mean.group(1)) if mean else None, 'max': float(worst.group(1)) if worst else None}


base = multiline(SOURCE)
base = with_ball_at(base, 0.3 if ANGLE else 0.0, 0.4 * ANGLE)
moved = with_ball_at(multiline(SOURCE), 0.6, ANGLE)
lit = with_key(moved, 0.12)
# Moved again after the light, from the same base: the moves and the light since the last full preparation together.
again = with_key(with_ball_at(multiline(SOURCE), -0.9, -ANGLE), 0.12)
# Another ball edited after the moves (its label: a full preparation): the moved ball, its node_xform alone changed, is
# taken over and placed anew (MeshData::shape); then moved again, from where it was placed anew (placeMoved).
edited = re.sub(r'(RdlMeshGeometry\("/ball2"\) \{\n)', r'\1  ["label"] = "edited",\n', again, count=1)
edited_moved = with_key(re.sub(r'(RdlMeshGeometry\("/ball2"\) \{\n)', r'\1  ["label"] = "edited",\n',
                               with_ball_at(multiline(SOURCE), 0.45, 0.5 * ANGLE), count=1), 0.12)
(OUT / 'base.rdla').write_text(base, encoding='utf-8')
(OUT / 'moved.rdla').write_text(moved, encoding='utf-8')
(OUT / 'lit.rdla').write_text(lit, encoding='utf-8')
result = {}
try:
    live = Session()
    r, lines = render(live, base, 1)
    result['base'] = {'ready': r['ready'], 'failed': r['failed'], 'lines': lines[-4:]}
    r, lines = render(live, moved, 2)
    result['moved_update'] = {'ready': r['ready'], 'failed': r['failed'], 'lines': lines[-10:]}
    moved_update = kept(live, 'moved-update')
    r, lines = render(live, lit, 3)
    result['lit_update'] = {'ready': r['ready'], 'failed': r['failed'], 'lines': lines[-4:]}
    lit_update = kept(live, 'lit-update')
    r, lines = render(live, again, 4)
    result['again_update'] = {'ready': r['ready'], 'failed': r['failed'], 'lines': lines[-4:]}
    again_update = kept(live, 'again-update')
    r, lines = render(live, edited, 5)
    result['edited_update'] = {'ready': r['ready'], 'failed': r['failed'], 'lines': lines[-6:]}
    edited_update = kept(live, 'edited-update')
    r, lines = render(live, edited_moved, 6)
    result['edited_moved_update'] = {'ready': r['ready'], 'failed': r['failed'], 'lines': lines[-4:]}
    edited_moved_update = kept(live, 'edited-moved-update')
    live.close()
    pictures = {}
    for name, text in (('moved-whole', moved), ('moved-whole-2', moved), ('lit-whole', lit), ('lit-whole-2', lit), ('again-whole', again),
                       ('edited-whole', edited), ('edited-moved-whole', edited_moved)):
        fresh = Session()
        r, lines = render(fresh, text, 1)
        result[name] = {'ready': r['ready'], 'failed': r['failed']}
        pictures[name] = kept(fresh, name)
        fresh.close()
    result['moved: update vs whole'] = diff(moved_update, pictures['moved-whole'])
    result['noise floor: whole vs whole'] = diff(pictures['moved-whole'], pictures['moved-whole-2'])
    result['lit: update vs whole'] = diff(lit_update, pictures['lit-whole'])
    result['noise floor, lit: whole vs whole'] = diff(pictures['lit-whole'], pictures['lit-whole-2'])
    result['moved vs lit (a real change)'] = diff(pictures['moved-whole'], pictures['lit-whole'])
    result['again: update vs whole'] = diff(again_update, pictures['again-whole'])
    result['again vs lit (a real move)'] = diff(pictures['again-whole'], pictures['lit-whole'])
    result['edited: update vs whole'] = diff(edited_update, pictures['edited-whole'])
    result['edited, moved: update vs whole'] = diff(edited_moved_update, pictures['edited-moved-whole'])
except Exception:
    import traceback
    result['error'] = traceback.format_exc()
finally:
    store.remove('xpu2/renderer')
    store.sync()
Path(sys.argv[2]).write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
print(json.dumps(result, indent=1, default=str)[:3000])
