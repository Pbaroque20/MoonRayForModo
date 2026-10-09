# python
"""Isolated GUI test: which ways of adding a user channel to a material item work, and how each kind reads back."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/user-channels'
out.mkdir(parents=True, exist_ok=True)
result = {'tries': {}}
try:
    scene = modo.Scene()
    material = next(iter(scene.items('advancedMaterial')))
    scene.select(material)
    for label, command in (
            ('float', 'channel.create mtlx_scale float scalar false 0.0 false 0.0 2.0 {%s}' % material.id),
            ('float_username', 'channel.create mtlx_scale2 float username:{UV Scale} item:{%s}' % material.id),
            ('color', 'channel.create mtlx_paint color rgb false 0.0 false 0.0 0.5 {%s}' % material.id),
            ('color2', 'channel.create mtlx_paint2 color item:{%s}' % material.id),
            ('color_float_rgb', 'channel.create mtlx_paint3 float rgb item:{%s}' % material.id),
            ('filepath', 'channel.create mtlx_file filepath item:{%s}' % material.id),
            ('string', 'channel.create mtlx_text string item:{%s}' % material.id),
            ('angle', 'channel.create mtlx_turn angle item:{%s}' % material.id),
            ('percent', 'channel.create mtlx_share percent item:{%s}' % material.id),
            ('boolean', 'channel.create mtlx_on boolean item:{%s}' % material.id)):
        try:
            lx.eval('!' + command)
            result['tries'][label] = 'ok'
        except Exception as exc:
            result['tries'][label] = str(exc)[:120]
    for query in ('command.argNames', 'command.argTypeNames', 'command.argUsernames', 'command.usage'):
        try:
            lx.eval('query commandservice command.select ? channel.create')
            result.setdefault('about', {})[query] = lx.eval('query commandservice %s ?' % query)
        except Exception as exc:
            result.setdefault('about', {})[query] = str(exc)[:100]
    for label, command in (
            ('vector_color1', 'channel.create mtlx_v1 color1 rgb false 0.0 false 0.0 0.5 {%s}' % material.id),
            ('vector_float_xyz', 'channel.create mtlx_v2 float xyz false 0.0 false 0.0 0.5 {%s}' % material.id),
            ('vector_named', 'channel.create name:mtlx_v3 type:color1 mode:rgb item:{%s}' % material.id),
            ('vector_named2', 'channel.create name:mtlx_v4 type:float mode:vector3 item:{%s}' % material.id),
            ('path', 'channel.create name:mtlx_p1 type:filepath item:{%s}' % material.id),
            ('path2', 'channel.create name:mtlx_p2 type:+filepath item:{%s}' % material.id)):
        try:
            lx.eval('!' + command)
            result['tries'][label] = 'ok'
        except Exception as exc:
            result['tries'][label] = str(exc)[:120]
    result['types'] = {}
    for name in material.channelNames:
        if name.startswith('mtlx_'):
            try:
                result['types'][name] = [material.channel(name).type, material.channel(name).storageType]
            except Exception as exc:
                result['types'][name] = str(exc)[:60]
    result['channels'] = [name for name in material.channelNames if name.startswith('mtlx_')]
    values = {}
    for name in result['channels']:
        try:
            values[name] = material.channel(name).get()
        except Exception as exc:
            values[name] = 'error ' + str(exc)[:60]
    result['values'] = values
    try:
        material.channel('mtlx_scale').set(3.5)
        result['set_float'] = material.channel('mtlx_scale').get()
    except Exception as exc:
        result['set_float'] = str(exc)
    for name in ('mtlx_paint', 'mtlx_paint.R', 'mtlx_paint2.R', 'mtlx_paint3.R'):
        try:
            channel = material.channel(name)
            if channel is not None:
                channel.set((.2, .4, .6) if '.' not in name else .25)
                result['set_' + name] = channel.get()
        except Exception as exc:
            result['set_' + name] = str(exc)[:100]
    try:
        result['username'] = lx.eval('channel.username channel:{%s:mtlx_scale2} username:?' % material.id)
    except Exception as exc:
        result['username'] = str(exc)[:100]
    try:
        lx.eval('!channel.username channel:{%s:mtlx_scale} username:{Flake Scale}' % material.id)
        result['rename'] = lx.eval('channel.username channel:{%s:mtlx_scale} username:?' % material.id)
    except Exception as exc:
        result['rename'] = str(exc)[:100]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))
