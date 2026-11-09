# python
"""GUI: whether a scene with Scene Proxies, once the kit has read it (host.snapshot, as the preview does), can be closed
and another scene opened and read, with Modo still working; then Modo is quit (its settings are saved as it quits:
launch-side, compare the profile's config files' times). Each step is written to test-results/references/close.json
before the next, so that a crash shows how far it got."""
import json
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {'steps': [], 'began': time.time()}


def save():
    (out / 'close.json').write_text(json.dumps(result, indent=1, default=str))


def step(text):
    result['steps'].append(text); save()


def read(label):
    import modo
    from moonray_modo import host
    snap = host.snapshot()
    step('%s read: %s, scene %s' % (label, [m.get('identity') for m in snap.get('meshes', [])], modo.Scene().filename))


def run():
    try:
        lx.eval('!scene.open {%s} normal' % (out / 'proxy2-test.lxo'))
        read('proxies')
        read('proxies again')
        if __import__('os').environ.get('QUIT_OPEN'):
            step('quitting with the proxy scene open')
            save()
            QtCore.QTimer.singleShot(3000, quit_now)
            return
        lx.eval('!scene.close')
        step('closed the proxy scene')
        lx.eval('!scene.open {%s} normal' % (out / 'src.lxo'))
        read('another scene')
        lx.eval('!scene.close')
        lx.eval('!scene.new')
        step('new scene')
        lx.eval('!scene.open {%s} normal' % (out / 'proxy2-test.lxo'))
        read('proxies reopened')
        lx.eval('!scene.close')
        step('closed it again')
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(3000, quit_now)


def quit_now():
    step('quitting')
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(4000, run)
