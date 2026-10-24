# python
"""Command-line test: the channels Modo 16.1 gives its lights' volumetrics, its environment material's and shader's fog,
and the render item's volume settings, with their types and defaults, for translating them to MoonRay. Writes
test-results/cl-export/prep/fog_channels.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\fog_channels.json')
result = {}
WORDS = ('vol', 'fog', 'scat', 'dens', 'atten', 'shift', 'height', 'radius', 'samp', 'quality', 'glob', 'aniso', 'falloff', 'murk', 'water', 'jitter')


def channels(item, everything=False):
    found = {}
    for index in range(item.internalItem.ChannelCount()):
        name = item.internalItem.ChannelName(index)
        if everything or any(w in name.lower() for w in WORDS):
            try:
                value = item.channel(name).get()
            except Exception as error:
                value = 'unreadable: %s' % error
            try:
                kind = item.internalItem.ChannelType(index)
            except Exception:
                kind = None
            found[name] = [value if isinstance(value, (int, float, str, type(None))) else str(value), kind]
    return found


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    for kind in ('sunLight', 'pointLight', 'spotLight', 'areaLight', 'cylinderLight', 'domeLight', 'photometryLight', 'meshLight'):
        try:
            light = scene.addItem(kind)
            result[kind] = channels(light, everything=kind in ('pointLight', 'spotLight', 'sunLight'))
        except Exception:
            result[kind] = traceback.format_exc()[-300:]
    for item in scene.items():
        if item.type in ('environment', 'envMaterial', 'defaultShader', 'polyRender', 'render'):
            result[item.type + ' ' + item.name] = channels(item, everything=item.type in ('envMaterial',))
    # A light's material may carry its volumetric colour.
    for item in scene.items():
        if item.type == 'lightMaterial':
            result.setdefault('lightMaterial', channels(item, everything=True))
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1, default=str))
