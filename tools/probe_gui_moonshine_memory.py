# python
"""Modo with its window (tools/launch_gui_probe.py): the memory Modo holds with MOONRAY_PROBE_SCENE opened as
MOONRAY_PROBE_HOW says ('loader': MoonRay > Open Scene as MoonShine; 'normal': opened as usual; 'moved': opened as usual,
then Move Shader Tree Textures to MoonShine Graphs), sampled while Modo draws for MOONRAY_PROBE_SECONDS (default 20) with
its 3D view showing textures. Writes <MOONRAY_PROBE_OUT>/memory-<how>.json and quits."""
import ctypes
import ctypes.wintypes
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
how = os.environ.get('MOONRAY_PROBE_HOW', 'loader')
report = {'how': how, 'samples': []}


class Counters(ctypes.Structure):
    _fields_ = [('cb', ctypes.wintypes.DWORD), ('PageFaultCount', ctypes.wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t), ('PrivateUsage', ctypes.c_size_t)]


def memory():
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    kernel.K32GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(Counters), ctypes.wintypes.DWORD]
    kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return {'working set MB': round(counters.WorkingSetSize / 2 ** 20, 1), 'private MB': round(counters.PrivateUsage / 2 ** 20, 1)}


try:
    from PySide2 import QtWidgets
    report['before'] = memory()
    if how == 'loader':
        lx.eval('moonray.material.openSceneAsMoonShine filename:{%s}' % source)
    else:
        lx.eval('scene.open {%s} normal' % source)
        if how == 'moved':
            lx.eval('moonray.material.moveShaderTreeTextures')
    report['clips'] = [clip.name for clip in modo.Scene().items('videoStill')]
    try:
        # The 3D view with textures, as an artist looks at a textured scene.
        lx.eval('view3d.shadingStyle advgl active')
    except Exception as exc:
        report['shading'] = str(exc)
    began = time.time()
    seconds = float(os.environ.get('MOONRAY_PROBE_SECONDS', 20))
    while time.time() - began < seconds:
        QtWidgets.QApplication.processEvents()
        time.sleep(.1)
        if len(report['samples']) < int((time.time() - began) / 2) + 1:
            report['samples'].append(memory())
    report['after'] = memory()
except Exception:
    report['error'] = traceback.format_exc()
(out / ('memory-%s.json' % how)).write_text(json.dumps(report, indent=1))
lx.eval('app.quit')
