# python
"""Command line: how a scene's image layers are tied to their images. PROBE_SCENE the .lxo. For each image layer and
its texture locator: every item graph it is in and what it is linked to each way; every channel of the layer and the
locator; and for each image (videoStill) the graphs it is in. Modo's own UDIM sets are one image per tile, each with
its tile number in its udim channel, and the locator's useUDIM on. Writes test-results/udim-links/report.json."""
import json
import os
import pathlib
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\udim-links'))
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def channels(item):
    found = {}
    for name in item.channelNames:
        try:
            value = item.channel(name).get()
        except Exception:
            continue
        found[name] = value
    return found


def graphs(item):
    found = {}
    scene = lx.object.Scene(item._item.Context())
    for k in range(scene.GraphCount()):
        try:
            name = scene.GraphByIndex(k).Name()
        except Exception:
            continue
        try:
            graph = item.itemGraph(name)
            forward = [(i.type, i.name) for i in graph.forward()]
            reverse = [(i.type, i.name) for i in graph.reverse()]
        except Exception:
            continue
        if forward or reverse:
            found[name] = {'forward': forward, 'reverse': reverse}
    return found


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    scene = modo.Scene()
    layers = []
    for layer in scene.items('imageMap'):
        entry = {'name': layer.name, 'graphs': graphs(layer), 'channels': channels(layer)}
        locators = [i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator']
        entry['locators'] = [{'name': l.name, 'graphs': graphs(l), 'channels': channels(l)} for l in locators]
        layers.append(entry)
    report['layers'] = layers
    report['clips'] = [{'name': c.name, 'graphs': graphs(c)} for c in scene.items('videoStill')]
    save()
    # What Modo's own scripting says each layer shows.
    shown = {}
    for layer in scene.items('imageMap'):
        try:
            shown[layer.name] = lx.eval('texture.setIMap ? item:%s' % layer.id)
        except Exception as error:
            shown[layer.name] = 'texture.setIMap: ' + str(error)
    report['setIMap'] = shown
except Exception:
    report['error'] = traceback.format_exc()
save()
