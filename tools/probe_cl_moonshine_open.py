# python
"""Command line: MOONRAY_PROBE_SCENE opened as MOONRAY_PROBE_HOW says: 'loader' through MoonRay > Open Scene as
MoonShine (moonray.material.openSceneAsMoonShine), 'normal' opened as usual and then moved with Move Shader Tree
Textures to MoonShine Graphs. Writes to MOONRAY_PROBE_OUT: report-<how>.json (the report, clips, layers, the process's
memory after opening and after the move, each image clip's pixels as Modo holds them), graphs-<how>.json, and
after-<how>.rdla (the scene as MoonRay is given it)."""
import ctypes
import ctypes.wintypes
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
how = os.environ.get('MOONRAY_PROBE_HOW', 'loader')
report = {'how': how}


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
    return {'working set MB': round(counters.WorkingSetSize / 2 ** 20, 1), 'private MB': round(counters.PrivateUsage / 2 ** 20, 1),
            'peak working set MB': round(counters.PeakWorkingSetSize / 2 ** 20, 1)}


def clips():
    return [{'name': clip.name, 'file': clip.channel('filename').get()} for clip in modo.Scene().items('videoStill')]


def save():
    (out / ('report-%s.json' % how)).write_text(json.dumps(report, indent=1, default=str))


try:
    report['memory at start'] = memory()
    if how == 'loader':
        lx.eval('moonray.material.openSceneAsMoonShine filename:{%s}' % source)
        report['memory after opening'] = memory()
    else:
        lx.eval('scene.open {%s} normal' % source)
        report['memory after opening'] = memory()
        lx.eval('moonray.material.moveShaderTreeTextures')
    from moonray_modo import shader_tree_scene, properties, material_override, host, rdla
    report['memory after the move'] = memory()
    report['report'] = list(shader_tree_scene.LAST_REPORT)
    scene = modo.Scene()
    report['scene file'] = scene.filename
    report['clips'] = clips()
    report['layers'] = {layer.name: bool(layer.channel('enable').get()) for layer in scene.items('imageMap')}
    graphs = {}
    for item in scene.items('advancedMaterial', superType=True):
        settings = properties.read(item)
        graph = settings.get('node_graph') if material_override.enabled(settings) else None
        if graph:
            graphs[item.name] = graph
    (out / ('graphs-%s.json' % how)).write_text(json.dumps(graphs, indent=1, sort_keys=True, default=str))
    save()
    if os.environ.get('MOONRAY_PROBE_EXPORT', '1') == '1':
        with host.by_engine('moonray'):
            snapshot = host.snapshot(evaluated_geometry=True)
        render = scene.renderItem
        text = rdla.scene_text(snapshot, int(render.channel('resX').get()), int(render.channel('resY').get()), 6, 0.0, str(out / ('after-%s.exr' % how)))
        (out / ('after-%s.rdla' % how)).write_text(text, encoding='utf-8')
        report['memory after reading for a render'] = memory()
except Exception:
    report['error'] = traceback.format_exc()
save()
