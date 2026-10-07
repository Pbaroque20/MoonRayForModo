"""Exercise the plugin's MoonLightIPR session class under Qt, outside Modo.

Run with a Python that has PySide2, such as Modo's bundled interpreter, after
tools/stage_moonlight.py. Submits a snapshot, then edits faster than they can be applied.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
from PySide2 import QtCore
from moonray_modo.moonlight_session import Session, supported
from check_moonlight_session import snapshot, look_at

stage = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build/moonlight/stage'
if not supported(stage):
    raise SystemExit('No staged MoonLightIPR in ' + str(stage))
app = QtCore.QCoreApplication(sys.argv)
session = Session()
scene = snapshot()
state = dict(generation=0, frames={}, applied=[], done=[], failures=[], warnings=[], log='')


def submit():
    state['generation'] += 1
    session.submit(scene, stage, 640, 360, 0, state['generation'], samples=64)


def finished(generation):
    state['done'].append(generation)
    if generation == 1:
        # A burst of camera moves: only the newest should be rendered to completion.
        for step in range(1, 6):
            scene['camera'] = dict(scene['camera'], matrix=look_at([step, 2.2, 8.5], [0, .9, 0]))
            submit()
    elif generation == state['generation']:
        app.quit()


session.memory_image.connect(lambda packet: state['frames'].setdefault(packet[0], []).append(len(packet[4])))
session.acknowledged.connect(state['applied'].append)
session.ready.connect(finished)
session.failed.connect(lambda message: (state['failures'].append(message), app.quit()))
session.warnings.connect(state['warnings'].extend)
session.output.connect(lambda text: state.update(log=state['log'] + text))
QtCore.QTimer.singleShot(60000, lambda: (state['failures'].append('timed out'), app.quit()))
submit()
app.exec_()
session.close()

print('applied', state['applied'], 'done', state['done'], 'frames', {k: len(v) for k, v in state['frames'].items()})
if state['failures']:
    raise SystemExit('MoonLightIPR Qt session failed: ' + '; '.join(state['failures']) + '\n' + state['log'][-2000:])
if state['done'] != [1, state['generation']] or state['applied'][0] != 1 or state['applied'][-1] != state['generation']:
    raise SystemExit('Unexpected event order')
if len(state['applied']) >= state['generation']:
    raise SystemExit('Queued edits were not coalesced')
if not state['frames'].get(1) or not state['frames'].get(state['generation']) or any(size != 640 * 360 * 12 for v in state['frames'].values() for size in v):
    raise SystemExit('Frames are missing or the wrong size')
print('MoonLightIPR Qt session check passed')
