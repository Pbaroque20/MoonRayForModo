# python
"""Command line: an asset library scene brought into a new scene as the library brings it in (Open the Scene for a
Modo scene, asset_import.execute otherwise), then what the scene has: its lights, environments, cameras and the render camera.
PROBE_ASSET the file (the ocean demo by default). Writes test-results/asset-import/report.json and merged.lxo."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\asset-import')
out.mkdir(parents=True, exist_ok=True)
asset = os.environ.get('PROBE_ASSET', r'C:\Users\Raphael Tobar\MoonRayForModo\kit\MoonRayForModo\assets\library\scenes\Ocean at sunset.lxo')
report = {}


def inventory(scene):
    found = {}
    for item in scene.iterItems():
        if item.type in ('sunLight', 'pointLight', 'spotLight', 'areaLight', 'domeLight', 'environment', 'envMaterial', 'camera',
                         'polyRender'):
            entry = {'name': item.name, 'id': item.id}
            for channel in ('radiance', 'type', 'visCam', 'visInd'):
                try:
                    entry[channel] = item.channel(channel).get()
                except (LookupError, AttributeError, RuntimeError, TypeError):
                    pass
            found.setdefault(item.type, []).append(entry)
    try:
        found['render_camera'] = scene.renderCamera.name
    except Exception:
        pass
    return found


try:
    lx.eval('scene.new')
    report['before'] = inventory(modo.Scene())
    from moonray_modo import asset_import
    if asset.lower().endswith('.lxo'):
        # As the library's Open the Scene does (asset_browser.import_asset), its copy made under the test folder.
        from unittest import mock
        with mock.patch('pathlib.Path.home', return_value=out / 'home'):
            opened = asset_import.working_copy(asset)
        lx.eval('scene.open ' + asset_import.command_path(opened) + ' normal')
        report['opened'] = str(opened)
    else:
        asset_import.execute(asset)
    report['after'] = inventory(modo.Scene())
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'merged.lxo'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
