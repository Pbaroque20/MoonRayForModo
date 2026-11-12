# python
"""Command-line: a test scene for XPU2 with a 16K diffuse map, as a tester's volcano had (16384 x 16384): the
reference scene (test-results/references/src.lxo) with test-results/volcano/diffuse16k.exr as a diffuse image layer on
its first UV map over everything, saved as test-results/volcano/diffuse16k_exr.lxo. Writes make.json beside it."""
import json
import pathlib
import traceback
import lx
import modo

folder = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\volcano')
result = {}
try:
    lx.eval('!scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\src.lxo')
    scene = modo.Scene()
    uv = None
    for mesh in scene.items('mesh'):
        maps = modo.Mesh(mesh).geometry.vmaps.uvMaps
        if maps:
            uv = maps[0].name
            break
    result['uv'] = uv
    lx.eval('clip.addStill {%s}' % (folder / 'diffuse16k.exr'))
    clip = [c for c in scene.items('videoStill')][-1]
    render = scene.renderItem
    image = scene.addItem('imageMap')
    image.setParent(render, len(render.children()))
    image.channel('effect').set('diffColor')
    locator = scene.addItem('txtrLocator')
    image.itemGraph('shadeLoc') >> locator.itemGraph('shadeLoc')
    locator.channel('projType').set('uv')
    if uv:
        locator.channel('uvMap').set(uv)
    lx.eval('select.item {%s} set' % image.id)
    lx.eval('texture.setIMap {%s}' % clip.name)
    result['layers'] = [(c.name, c.type) for c in render.children()]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (folder / 'diffuse16k_exr.lxo'))
    result['saved'] = (folder / 'diffuse16k_exr.lxo').is_file()
except Exception:
    result['error'] = traceback.format_exc()[-2000:]
(folder / 'make.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
