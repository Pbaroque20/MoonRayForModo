"""Route a preview through the plugin's Renderer with the MoonLight engine, outside Modo.

Usage: check_moonlight_renderer.py <moonray-runtime> [moonlight-folder]
Run with a Python that has PySide2, such as Modo's bundled interpreter. The runtime supplies
the display conversion the panel uses; MoonLight comes from tools/stage_moonlight.py.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
os.environ['MOONRAY_MODO_MOONLIGHT'] = str(pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'build/moonlight/stage')
from PySide2 import QtCore, QtGui
from moonray_modo.render import Renderer, MOONLIGHT_STATUS
from moonray_modo.display import values as display_values
from check_moonlight_session import snapshot, look_at

app = QtGui.QGuiApplication(sys.argv)
renderer = Renderer()
state = dict(images=[], finished=0, failures=[], notices=[], statuses=[])


def scene(eye):
    result = snapshot()
    result['camera'] = dict(result['camera'], matrix=look_at(eye, [0, .9, 0]))
    result.update(warnings=[], display=display_values({}), preview_buffer='normal')
    # An unsupported light must surface as a notice, not vanish.
    result['lights'].append({'kind': 'CylinderLight', 'identity': 'tube', 'name': 'Tube', 'color': [1, 1, 1], 'intensity': 1.0})
    return result


def submit(eye):
    renderer.submit(scene(eye), sys.argv[1], 640, 360, 1, 0.0, 0, engine='moonlight')


def finished(output):
    state['finished'] += 1
    if state['finished'] == 1:
        submit([4, 2.5, 7.5])     # an edit reuses the running session
    elif state['finished'] == 2:
        # Stop must pause, not end, the session: the next preview keeps its loaded scene.
        state['pid'] = renderer.moonlight.process.processId()
        renderer.stop()
        submit([-3, 2.5, 7.5])
    else:
        state['same_process'] = renderer.moonlight.process.processId() == state['pid']
        # Let the display worker deliver the last frame before leaving.
        QtCore.QTimer.singleShot(3000, app.quit)


def image(value):
    # The display path hands over an image, or the path of one it converted on disk.
    value = value.copy() if isinstance(value, QtGui.QImage) else QtGui.QImage(value)
    state['images'].append((state['finished'], value.width(), value.height(), value))


state['frames'] = 0
renderer.moonlight.memory_image.connect(lambda packet: state.update(frames=state['frames'] + 1))
renderer.image_ready.connect(image)
renderer.image_object.connect(image)
renderer.finished.connect(finished)
renderer.failed.connect(lambda message: (state['failures'].append(message), app.quit()))
renderer.notices.connect(state['notices'].extend)
renderer.status.connect(state['statuses'].append)
QtCore.QTimer.singleShot(60000, lambda: (state['failures'].append('timed out'), app.quit()))
submit([0, 2.2, 8.5])
app.exec_()
reused = renderer.moonlight.running()
backend = renderer.backend_status
if state['images']:
    folder = ROOT / 'build/moonlight/session'
    folder.mkdir(parents=True, exist_ok=True)
    state['images'][-1][3].save(str(folder / 'moonlight_renderer.png'))
renderer.close()

print('finished', state['finished'], 'frames', state['frames'], 'images', len(state['images']), 'notices', state['notices'])
if state['failures']:
    raise SystemExit('MoonLight renderer check failed: ' + '; '.join(state['failures']) + '\n' + '\n'.join(state['statuses'][-5:]) + '\n' + renderer.log[-2000:])
if state['finished'] != 3 or not reused or backend != MOONLIGHT_STATUS or not state.get('same_process'):
    raise SystemExit('Previews did not complete on one MoonLight session across an edit and a Stop')
if not state['images'] or state['images'][-1][0] != 3:
    raise SystemExit('The finished preview was not displayed\n' + '\n'.join(state['statuses'][-8:]))
if any((width, height) != (640, 360) for _, width, height, _ in state['images']):
    raise SystemExit('Displayed image has the wrong size')
final = state['images'][-1][3]
if not any(QtGui.QColor(final.pixel(x, y)).lightness() > 16 for x in range(0, 640, 40) for y in range(0, 360, 40)):
    raise SystemExit('Displayed image is black')
if not any('CylinderLight' in notice for notice in state['notices']):
    raise SystemExit('The unsupported light was not reported')
print('MoonLight renderer check passed')
