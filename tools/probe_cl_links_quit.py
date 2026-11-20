# python
"""Headless: which step leaves Modo to crash as it quits with a linked mesh in the scene. PROBE_STAGE:
  plain    a mesh, nothing else
  convert  proxy.convert alone
  link     links.run('link') (convert, the file's mesh put at the origin, the proxy reading it again)
  capture  link, then a render cache reading (evaluated.capture)
  proxies  capture, then evaluated.proxies
PROBE_END=close closes the scene before quitting. The exit code is what launch_cl_probe prints."""
import os
import pathlib
import shutil
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\quit')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
stage = os.environ.get('PROBE_STAGE', 'link')
order = ['plain', 'convert', 'link', 'capture', 'proxies']
upto = order.index(stage)
lx.eval('scene.new')
lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
lx.eval('item.create mesh {Box}')
box = [i for i in modo.Scene().items('mesh') if i.name == 'Box'][0]
lx.eval('select.item {%s} set' % box.id)
lx.eval('tool.set prim.cube on')
lx.eval('tool.apply')
lx.eval('tool.set prim.cube off')
box.position.set([1.0, 0.0, 0.0])
if stage == 'convert':
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (box.id, out / 'Box.lxo'))
elif upto >= order.index('link'):
    from moonray_modo import links
    links.run('link', [box.id], out / 'links')
if upto >= order.index('capture'):
    from moonray_modo import evaluated
    data = evaluated.capture(lx.service.Selection().GetTime())
    if upto >= order.index('proxies'):
        evaluated.proxies(data, modo.Scene(), lx.service.Selection().GetTime(), [])
    del data
(out / 'stage.txt').write_text(stage)
if os.environ.get('PROBE_END') == 'close':
    lx.eval('!scene.close')
