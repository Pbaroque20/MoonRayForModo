# python
"""Command-line test: whether Modo's own Bake to Texture (bake.toTexture) works without Modo's window, as a way to
hand MoonRay any of Modo's textures exactly. A sphere's material is given Modo's Noise and Enhance: Modo's Crackle on
its diffuse colour; a new image map at the top of the Shader Tree, on the sphere's UV map, is baked; the file is
read back. Writes test-results/cl-export/bake/report.json and the baked image beside it."""
import json
import pathlib
import traceback
import lx
import modo

folder = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\bake')
result = {'steps': []}


def save():
    (folder / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def attempt(label, command):
    result['steps'].append([label, 'started'])
    save()
    try:
        value = lx.eval(command)
        result['steps'].append([label, 'ok', value])
        return True
    except Exception as error:
        result['steps'].append([label, 'failed', str(error)])
        return False


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    lx.eval('layer.new')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.sphere off')
    mesh = scene.selected[-1]
    result['mesh'] = mesh.name
    result['uv_maps'] = [m.name for m in modo.Mesh(mesh).geometry.vmaps.uvMaps]
    render = scene.renderItem
    noise = scene.addItem('noise')
    noise.setParent(render, len(render.children()))
    noise.channel('effect').set('diffColor')
    crackle = scene.addItem('val.Organic_Crackle.RJJ')
    crackle.setParent(render, len(render.children()))
    crackle.channel('effect').set('diffColor')
    crackle.channel('opacity').set(0.5)
    result['layers'] = [(c.name, c.type) for c in render.children()]
    path = folder / 'baked.png'
    if path.exists():
        path.unlink()
    attempt('new still', 'clip.newStill {%s} res:x256 type:RGB format:PNG' % path)
    clip = [c for c in scene.items('videoStill')][-1]
    result['clip'] = clip.name
    # As Modo's own Add Layer > Image Map does: a layer with its texture locator, at the top of the Shader Tree.
    # An image map with a texture locator of its own, on the sphere's UV map (shader.create crashes modo_cl).
    image = scene.addItem('imageMap')
    image.setParent(render, len(render.children()))
    image.channel('effect').set('diffColor')
    locator = scene.addItem('txtrLocator')
    image.itemGraph('shadeLoc') >> locator.itemGraph('shadeLoc')
    locator.channel('projType').set('uv')
    locator.channel('uvMap').set(result['uv_maps'][0])
    lx.eval('select.item {%s} set' % image.id)
    attempt('set image', 'texture.setIMap {%s}' % clip.name)
    result['image_layer'] = (image.name, image.type, [c.type for c in image.itemGraph('shadeLoc').forward()])
    result['layers'] = [(c.name, c.type) for c in render.children()]
    lx.eval('select.item {%s} add' % mesh.id)
    attempt('select uv map', 'select.vertexMap {%s} txuv replace' % result['uv_maps'][0])
    lx.eval('select.item {%s} set' % image.id)
    attempt('bake to texture', 'bake.toTexture')
    lx.eval('select.item {%s} set' % clip.id)
    attempt('save clip', 'clip.save')
    result['file'] = [str(path), path.exists(), path.stat().st_size if path.exists() else 0]
except Exception:
    result['error'] = traceback.format_exc()
save()
if lx.service.Platform().IsHeadless() is False:
    lx.eval('!app.quit')
