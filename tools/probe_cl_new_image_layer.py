# python
"""Command line: ways to make a new image layer in a material's group (for shader_tree_revert.new_layer), each logged
before it runs to MOONRAY_PROBE_OUT/new-layer.txt (flushed), so a crash names its way. MOONRAY_PROBE_WAY picks one:
create (shader.create imageMap, the group selected), add (scene.addItem, parented, a Texture Locator linked), duplicate
(texture.duplicate of a layer, its clip changed)."""
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results\shader-tree-revert')
way = os.environ.get('MOONRAY_PROBE_WAY', 'create')
log = open(str(out / ('new-layer-%s.txt' % way)), 'w', encoding='utf-8')


def say(text):
    log.write(text + '\n')
    log.flush()
    os.fsync(log.fileno())


def tree(item, depth=0):
    for child in item.children():
        say('  ' * depth + '%s (%s)' % (child.name, child.type))
        tree(child, depth + 1)


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Box')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('poly.setMaterial Wood')
    mask = [i for i in scene.items('mask') if i.name.startswith('Wood')][0]
    image = r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results\shader-tree\images\grey.png'
    say('clip.addStill')
    lx.eval('clip.addStill {%s}' % image)
    clip = scene.items('videoStill')[-1]
    if way == 'create':
        lx.eval('select.item {%s} set' % mask.id)
        say('shader.create imageMap (group selected)')
        lx.eval('shader.create imageMap')
        say('made')
    elif way == 'create_clip':
        lx.eval('select.item {%s} set' % clip.id)
        lx.eval('select.item {%s} add' % mask.id)
        say('shader.create imageMap (clip and group selected)')
        lx.eval('shader.create imageMap')
        say('made')
    elif way == 'add':
        say('scene.addItem imageMap')
        layer = scene.addItem('imageMap', name='Grey')
        layer.setParent(mask, len(mask.children()))
        say('parented')
        lx.eval('select.item {%s} set' % layer.id)
        say('texture.setIMap')
        lx.eval('texture.setIMap {%s}' % clip.name)
        say('linked')
    layer = next((i for i in scene.items('imageMap')), None)
    say('layer %s' % (layer.name if layer else None))
    if layer is not None:
        try:
            linked = [i.type for i in layer.itemGraph('shadeLoc').forward()]
        except Exception as exc:
            linked = str(exc)
        say('linked: %s' % linked)
    tree(scene.renderItem)
    say('DONE')
except Exception:
    say('ERROR ' + traceback.format_exc())
log.close()
