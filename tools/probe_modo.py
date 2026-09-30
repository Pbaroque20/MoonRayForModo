# python
"""Read-only host API probe, run in a separate modo_cl process."""
import json
import os
import sys
import traceback
import lx
import modo

result = {"python": sys.version}
def progress(message):
    with open(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\host-progress.txt', 'w') as stream:
        stream.write(message)
progress('started')
result['app_version'] = lx.eval('query platformservice appversion ?')
platform = lx.service.Platform()
result['import_paths'] = [platform.ImportPathByIndex(i) for i in range(platform.ImportPathCount())]
result['server_module_loaded'] = 'moonray_commands' in sys.modules
try:
    scene = modo.Scene()
    try:
        result['command_registered'] = bool(lx.service.Command().Spawn(0, 'moonray.open').test())
    except Exception as exc:
        result['command_registration_error'] = str(exc)
        try:
            sys.path.insert(0, r'C:\Users\Raphael Tobar\MoonRayForModo\kit\MoonRayForModo\lxserv')
            import moonray_commands
            result['manual_command_registered'] = bool(lx.service.Command().Spawn(0, 'moonray.open').test())
        except Exception:
            result['manual_server_error'] = traceback.format_exc()
    result['camera_matrix'] = lx.object.Matrix(scene.renderCamera.channel('worldMatrix').get()).Get4()
    lx.eval('item.create spotLight')
    progress('spot created')
    for kind in ("camera", "polyRender", "advancedMaterial", "sunLight", "spotLight", "lightMaterial", "light", "mesh"):
        result[kind] = []
        for item in scene.items(kind):
            channels = {}
            for index in range(item.ChannelCount()):
                name = item.ChannelName(index)
                if item.type == 'spotLight' and not any(word in name.lower() for word in ('cone', 'spread', 'radius', 'edge', 'angle', 'radiance', 'soft')):
                    continue
                try:
                    value = item.channel(name).get()
                    channels[name] = value if isinstance(value, (int, float, str, tuple, list)) else repr(value)
                except Exception:
                    pass
            result[kind].append({"name": item.name, "channels": channels})
    result["matrix_api"] = dir(lx.object.Matrix())
    result["locator_api"] = dir(lx.object.Locator())
    from PySide2 import QtCore, QtWidgets
    result["qt"] = QtCore.qVersion()
    result["qapplication"] = bool(QtWidgets.QApplication.instance())
    sys.path.insert(0, r'C:\Users\Raphael Tobar\MoonRayForModo\kit\MoonRayForModo\python')
    from moonray_modo import host, rdla
    mesh = scene.addMesh('MoonRay API Test')
    progress('mesh created')
    geometry = mesh.geometry
    for position in ((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)):
        geometry.vertices.new(position)
    geometry.polygons.new((0, 1, 2, 3))
    geometry.setMeshEdits()
    geometry = mesh.geometry
    uv_map = geometry.vmaps.addUVMap('Texture')
    progress('UV map created')
    for index, uv in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv_map[index] = uv
    progress('UV map populated')
    geometry.setMeshEdits()
    geometry = mesh.geometry
    normal_map = geometry.vmaps.addVertexNormalMap('Vertex Normal')
    progress('normal map created')
    for index in range(4):
        normal_map[index] = (0, 0, 1)
    geometry.setMeshEdits()
    progress('mesh map values committed')
    result['snapshot'] = host.snapshot()
    progress('snapshot captured')
    exported_mesh = next(m for m in result['snapshot']['meshes'] if m['name'] == mesh.name)
    assert len(exported_mesh['uvs']) == 4 and exported_mesh['uvs'][2] == [1, 1]
    assert exported_mesh['normals'] == [[0, 0, 1]] * 4
    result['uv_and_normal_export'] = True
    with open(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\modo-export.rdla', 'w') as out:
        out.write(rdla.scene_text(result['snapshot'], 128, 128))
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.convert psubdiv face')
    subdivided = host.snapshot()
    exported_mesh = next(m for m in subdivided['meshes'] if m['name'] == mesh.name)
    assert exported_mesh['subdivision'], 'Modo Pixar subdivision was exported as a coarse polygon cage'
    result['subdivision_export'] = {'pixar': True}
    lx.eval('poly.convert subpatch psubdiv')
    subdivided = host.snapshot()
    exported_mesh = next(m for m in subdivided['meshes'] if m['name'] == mesh.name)
    assert exported_mesh['subdivision'], 'Modo subdivision was exported as a coarse polygon cage'
    result['subdivision_export']['modo'] = True
    from moonray_modo.panel import Panel
    preview = Panel()
    preview.surface.setCurrentIndex(1)
    captured = preview._capture()
    assert all(m['subdivision'] and m['subdivision_level'] == 3 for m in captured['meshes'])
    preview.dispose()
    # modo_cl exits without a graphical event loop to process deleteLater().
    import shiboken2
    shiboken2.delete(preview)
    del preview
    result['subdivision_preview_controls'] = True
    from moonray_modo import properties
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % mesh.id)
    settings = {'override': True, 'subdivision': False, 'level': 2, 'smooth': False}
    lx.eval('moonray.objectSettings ' + properties.encode(settings))
    assert properties.read(mesh) == settings
    assert lx.eval('moonray.object.level ?') == 2
    captured = next(m for m in host.snapshot()['meshes'] if m['name'] == mesh.name)
    assert not captured['subdivision'] and not captured['smooth'] and captured['subdivision_level'] == 2
    lx.eval('moonray.sceneSettings ' + properties.encode({'render': {'max_depth': 7}, 'aovs': ['depth', 'normal']}))
    assert properties.scene_settings()['render']['max_depth'] == 7
    result['scene_and_object_settings'] = {'stored': True, 'queried': True, 'exported': True}
    import unittest
    import io
    test_log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(r'C:\Users\Raphael Tobar\MoonRayForModo\tests')
    tested = unittest.TextTestRunner(stream=test_log, verbosity=2).run(suite)
    result['tests'] = {'count': tested.testsRun, 'passed': tested.wasSuccessful(), 'log': test_log.getvalue()}
except Exception:
    result["error"] = traceback.format_exc()
with open(r"C:\Users\Raphael Tobar\MoonRayForModo\tools\probe_result.json", "w") as stream:
    json.dump(result, stream, indent=2)
# The harness sends app.quit after this script has returned and released Qt refs.
