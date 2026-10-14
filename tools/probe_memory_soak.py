# python
"""Isolated GUI test: does memory pile up as the preview is used over and over?

Two balls under a light. MoonRay renders the scene again and again, MoonLightIPR follows a ball moved many times, and
MoonRay LS renders again and again. After each round what is written down: the memory of Modo, of the loaded MoonRay and
of the MoonLightIPR session; how many Python objects there are; the preview's cached render folders and the kit's
temporary folders; and the sizes of the plugin's caches. Memory that settles is a cache; memory that climbs with
every round is a leak."""
import ctypes
import gc
import json
import os
import pathlib
import subprocess
import tempfile
import traceback
from ctypes import wintypes
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/memory-soak'
out.mkdir(parents=True, exist_ok=True)
ROUNDS = int(os.environ.get('MOONRAY_PROBE_ROUNDS', '10'))
result = {'rounds': []}
held = {}


class Counters(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t), ('PrivateUsage', ctypes.c_size_t)]


def own_memory():
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    process = kernel.GetCurrentProcess()
    query = ctypes.WinDLL('psapi').GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    query(process, ctypes.byref(counters), counters.cb)
    handles = wintypes.DWORD()
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessHandleCount(process, ctypes.byref(handles))
    return round(counters.PrivateUsage / 1048576.0, 1), handles.value


def others():
    """Working set, in MB, of each MoonRay and MoonLightIPR process (tasklist), by name."""
    found = {}
    try:
        text = subprocess.check_output(['tasklist', '/FO', 'CSV', '/NH'], text=True, creationflags=0x08000000)
        for line in text.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 5 and parts[0].lower() in ('moonray.exe', 'moonlightipr_session.exe'):
                found.setdefault(parts[0].lower(), []).append(round(int(parts[4].replace(',', '').split()[0]) / 1024.0, 1))
    except Exception as exc:
        found['error'] = str(exc)
    return found


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def caches():
    from moonray_modo import extra_geometry, geometry, moonlightipr_scene, rdla, scene_digest, serialization, properties
    return {'packed': len(moonlightipr_scene._packed), 'emitters': len(moonlightipr_scene._emitters), 'smoothed': len(geometry._SMOOTHED),
            'apart': len(rdla._APART), 'remembered': len(scene_digest._remembered), 'serialized': len(serialization._cache),
            'written': len(extra_geometry.WRITTEN), 'live': len(properties.LIVE)}


def folders():
    panel = panel_widget()
    cache_root = pathlib.Path(panel.renderer.buffers.root)
    temp = pathlib.Path(tempfile.gettempdir())
    return {'buffer_frames': sum(1 for p in cache_root.iterdir() if p.is_dir()) if cache_root.is_dir() else None,
            'temp_moonray': sum(1 for p in temp.iterdir() if p.name.lower().startswith(('moonray', 'tmp')) and p.is_dir())}


def kinds():
    import collections
    return collections.Counter(type(o).__name__ for o in gc.get_objects())


def note(name):
    gc.collect()
    counted = kinds()
    if name in ('moonray_1', 'moonray_%d' % ROUNDS, 'moonlightipr_0', 'moonlightipr_%d' % (ROUNDS * 4), 'ls_1', 'ls_%d' % ROUNDS):
        held[name] = counted
    for first, last in (('moonray_1', 'moonray_%d' % ROUNDS), ('moonlightipr_0', 'moonlightipr_%d' % (ROUNDS * 4)), ('ls_1', 'ls_%d' % ROUNDS)):
        if name == last and first in held:
            grown = (counted - held[first]).most_common(12)
            result.setdefault('grown', {})[first.split('_')[0]] = grown
    private, handles = own_memory()
    panel = panel_widget()
    result['rounds'].append({'round': name, 'moved': held.get('moved', 0), 'modo_private_mb': private, 'modo_handles': handles, 'others_mb': others(),
                             'python_objects': len(gc.get_objects()), 'qt_widgets': len(QtWidgets.QApplication.allWidgets()),
                             'panel_children': len(panel.findChildren(QtCore.QObject)), 'caches': caches(), 'folders': folders(),
                             'status': panel.status.text()[:60]})
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


def engine(name):
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(name))


@step(3000)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    engine('moonray')
    note('start')


for index in range(ROUNDS):
    @step(14000)
    def moonray_render(index=index):
        if index:
            note('moonray_%d' % index)
        panel_widget().start.click()


@step(3000)
def to_realtime():
    note('moonray_%d' % ROUNDS)
    engine('moonlightipr')
    panel_widget().start.click()

for index in range(ROUNDS * 4):
    @step(1500)
    def nudge(index=index):
        # The ball moved, as dragging it in Modo moves it.
        if index % 4 == 0:
            note('moonlightipr_%d' % index)
        lx.eval('!select.item {%s} set' % held['ball'])
        lx.eval('!transform.channel pos.X %s' % (0.6 + 0.05 * (index % 7)))
        held['moved'] = held.get('moved', 0) + 1


@step(3000)
def to_low():
    note('moonlightipr_%d' % (ROUNDS * 4))
    panel_widget().stop()
    engine('moonray_ls')

for index in range(ROUNDS):
    @step(6000)
    def low_render(index=index):
        if index:
            note('ls_%d' % index)
        panel_widget().start.click()


@step(500)
def finish_():
    note('ls_%d' % ROUNDS)


def run(index=0):
    if index >= len(STEPS):
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
        lx.eval('!!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    held['ball'] = modo.Scene().selected[0].id
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, lambda: run())
