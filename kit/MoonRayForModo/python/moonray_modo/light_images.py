"""A Modo light's Shader Tree images (Image Map layers under the light, beside its Light Material, of effect Light
Color), drawn as Modo's own renderer draws them, in MoonRay, XPU2 and MoonLightIPR alike.

How Modo draws them (read from its renders: tools/probe_cl_light_images.py, a floor lit by a light whose image is
tools/make_uv_code_image.py's, its colour the image coordinate looked up; tools/read_light_image_code.py):
  - the image is looked up where the light gives off its light, at the point of the light's own surface in its own
    frame, measured in the light's size: an area light's point at (x / width, y / height, 0), from -0.5 to 0.5 across
    it; a light with no size (a Spot, a Point, a Directional light) gives off its light from its middle alone, so it is
    one colour, the image at that point; one with a size (a Spot or Point with a radius) shows little of its image on
    what it lights, and is taken here as that one colour too;
  - that point goes through the layer's Texture Locator as a point of the world would: less the locator's place, by
    its turn and size, then its projection as Modo lays an environment's (environment_projections.coordinates): Planar
    along its axis, the Wraps doing nothing; UV Map, Front and Implicit UV give one colour; Solid (none, a new layer's)
    lays the image as Planar along Y does on a light, so that an area light shows the image's middle row across its
    width (Modo's own render; the light has no depth);
  - the layer's colour replaces the light's (Light Material's Light Color) by its opacity (Normal blend); Multiply,
    Add and Subtract blend as Modo's layers do; layers stack bottom first.
How the kit draws that: a light of one colour is given it as its colour; an area light (MoonRay's RectLight) is given a
picture across it, its texture, laid as MoonRay lays a RectLight's (across it toward its own -X): the image itself,
mirrored, where it is laid once across the light (Planar along Z, the locator untouched, opaque, alone), else one made here (made in the cache, Light Images) of the layers laid as above, one pixel
high (or wide) where the image does not change up (or across) the light. A Mesh Light's image is not drawn (said).

A layer the Shader Tree to MoonShine command moved (shader_tree_lights: its layer switched off, its clip taken out, a
record naming its image kept in the scene's light settings) is drawn from its record as it was drawn from its clip.

Nothing of Modo but read(): plan(), colour_at() and bake() work on plain dicts, for tests."""
import hashlib
import math
import struct
from pathlib import Path

VERSION = 'light-images-v4'
EFFECT = 'lightColor'
# The kinds whose image is one colour (the light's middle), and the one whose picture is laid across it.
ONE_COLOUR = ('SpotLight', 'SphereLight', 'DistantLight')
ACROSS = ('RectLight',)
BLENDS = ('normal', 'multiply', 'add', 'subtract')
BAKE_SIZE = 256        # a picture laid otherwise than once across the light: its size, up and across
ROW_SIZE = 1024        # one that changes only across (or only up): its length
READ_SIZE = 1024       # an image read for laying: at most this across and up


def projection(channels, matrix):
    """A layer's Texture Locator as environment_projections lays it, for a point of the light: its channels (projType,
    projAxis, wrapU, wrapV, uvRotation, tileU, tileV) and world matrix (row-major 4x4). Solid is laid as Planar along
    Y (Modo's renders of a light); the locator's place is kept (offset), which a direction has none of."""
    from . import environment_projections
    held = dict(channels)
    if str(held.get('projType', 'none')) == 'none':
        held.update(projType='planar', projAxis=1)
    found = environment_projections.capture(None, lambda item, key, default=None: held.get(key, default), matrix)
    found['offset'] = [float(v) for v in matrix[12:15]]
    return found


def coordinates(found, point):
    """Where Modo looks the layer up for a point of the light: [(u, v, weight)]."""
    from . import environment_projections
    if found['projection'] == 'constant':
        return environment_projections.coordinates(found, point)
    return environment_projections.coordinates(found, [p - o for p, o in zip(point, found.get('offset', (0, 0, 0)))])


def blend(under, over, amount, mode):
    """A layer's colour over what is under it, by its opacity (times its alpha) and blend mode, as Modo blends."""
    if mode == 'multiply':
        made = [u * o for u, o in zip(under, over)]
    elif mode == 'add':
        made = [u + o for u, o in zip(under, over)]
    elif mode == 'subtract':
        made = [max(0.0, u - o) for u, o in zip(under, over)]
    else:
        made = list(over)
    return [u + (m - u) * amount for u, m in zip(under, made)]


def sample(found, pixels, alpha, width, height, point):
    """A layer's colour and coverage at a point of the light (environment_projections.sample, the locator's place taken
    off the point first: it takes a direction, which has none)."""
    from . import environment_projections
    if found['projection'] != 'constant':
        point = [p - o for p, o in zip(point, found.get('offset', (0, 0, 0)))]
    return environment_projections.sample(found, pixels, alpha, width, height, point)


def layered(base, layers, images, point):
    """The light's colour at a point of it: its base colour with each layer over it, bottom first. images: for each
    layer, (pixels, alpha, width, height) as environment_projections.sample reads them."""
    colour = list(base)
    for layer, image in zip(layers, images):
        pixels, alpha, width, height = image
        value, coverage = sample(layer['projection'], pixels, alpha, width, height, point)
        if coverage <= 0:
            continue
        if layer.get('invert'):
            value = [1.0 - v for v in value]
        colour = blend(colour, value, float(layer.get('opacity', 1.0)) * coverage, layer.get('blend', 'normal'))
    return colour


def point_of(s, t):
    """The point of a flat light (its local frame, measured in its size) at (s, t) across and up it, 0 to 1."""
    return [s - .5, t - .5, 0.0]


def plain(layers, alpha):
    """Whether one layer's image is laid once across the light as it stands (Planar along Z, the locator untouched,
    opaque, Normal, no alpha, repeating): it is then the light's picture itself."""
    if len(layers) != 1 or alpha:
        return False
    layer = layers[0]
    found = layer['projection']
    identity = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
    return (found['projection'] == 'planar' and int(found.get('axis', 1)) == 2 and float(layer.get('opacity', 1)) >= 1
            and layer.get('blend', 'normal') == 'normal' and not layer.get('invert')
            and all(abs(a - b) < 1e-6 for a, b in zip(found['turn'], identity)) and all(abs(s - 1) < 1e-6 for s in found['size'])
            and all(abs(o) < 1e-6 for o in found.get('offset', (0, 0, 0))) and abs(float(found.get('uv_rotation', 0))) < 1e-9)


def extent(layers):
    """(across, up): whether the picture changes across the light and up it (a layer laid by Planar along Y changes
    across it alone)."""
    across = up = False
    for layer in layers:
        found = layer['projection']
        for s, t in ((.1, .2), (.7, .9), (.35, .6)):
            here = coordinates(found, point_of(s, t))
            if coordinates(found, point_of(s, .5 + (t - .5) * -1.3)) != here:
                up = True
            if coordinates(found, point_of(.5 + (s - .5) * -1.3, t)) != here:
                across = True
    return across, up


def bake_size(layers):
    across, up = extent(layers)
    if across and up:
        return BAKE_SIZE, BAKE_SIZE
    if across:
        return ROW_SIZE, 1
    if up:
        return 1, ROW_SIZE
    return 1, 1


def bake(base, layers, images, width, height):
    """The light's picture, top row first: its colour at each pixel's middle, mirrored across, as MoonRay lays a
    RectLight's texture: across it toward the light's own -X, up it toward its +Y (MoonRay's renders of the same image,
    read by tools/read_light_image_code.py)."""
    values = []
    for row in range(height):
        t = 1.0 - (row + .5) / height
        for column in range(width):
            values.extend(layered(base, layers, images, point_of(1.0 - (column + .5) / width, t)))
    return values


def mirrored(layer):
    """A layer's image, its colours taken to linear as prepare takes them, mirrored left to right: laid once across
    the light, it is then its picture as MoonRay lays a RectLight's texture (bake). Made once in the cache (Light
    Images) for each file as it stands."""
    import subprocess
    from . import environment_layers, native, textures
    source = textures.asset_path(layer['path'])
    stat = source.stat()
    _, colour, transform_key = textures.color_conversion(layer['path'], layer.get('srgb', False), layer.get('color_space', ''))
    key = repr((VERSION, 'mirrored', str(source), stat.st_size, stat.st_mtime_ns, transform_key))
    folder = textures.cache_root() / 'Light Images'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (hashlib.sha256(key.encode()).hexdigest()[:32] + '.exr')
    if target.is_file():
        return str(target)
    tool = native.tool('oiiotool.exe')
    environment = native.environment(tool.parent)

    def run(args):
        done = subprocess.run([str(tool)] + args, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            raise ValueError('the image %s could not be read: %s' % (source.name, done.stdout.decode(errors='replace')[-600:]))
        return done.stdout.decode(errors='replace')
    grey = environment_layers.channel_count(run(['--info:format=xml', '-v', str(source)])) < 3
    staged = folder / (target.stem + '-staged.exr')
    try:
        run([str(source)] + (['--ch', '0,0,0', '--chnames', 'R,G,B'] if grey else ['--ch', 'R,G,B']) + colour + ['--flop', '-d', 'float', '-o', str(staged)])
        staged.replace(target)
    finally:
        if staged.exists():
            staged.unlink()
    return str(target)


def write_picture(target, values, width, height):
    """A picture of three floats a pixel, top row first, written as an OpenEXR (by way of a PFM, bottom row first as the
    format has it, which the runtime's oiiotool reads so). Not a PFM itself: MoonRay's lights and cookies read a PFM's
    rows the other way up from oiiotool (and from what the other engines take through it)."""
    import subprocess
    import uuid
    from . import native
    target = Path(target)
    staged = target.with_name(target.stem + '-' + uuid.uuid4().hex)
    rows = [values[row * width * 3:(row + 1) * width * 3] for row in range(height)]
    try:
        with open(str(staged) + '.pfm', 'wb') as stream:
            stream.write(b'PF\n%d %d\n-1.0\n' % (width, height))
            for row in reversed(rows):
                stream.write(struct.pack('<%df' % len(row), *row))
        tool = native.tool('oiiotool.exe')
        done = subprocess.run([str(tool), str(staged) + '.pfm', '-d', 'float', '-o', str(staged) + '.exr'], env=native.environment(tool.parent),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            raise ValueError('a light picture could not be written: ' + done.stdout.decode(errors='replace')[-600:])
        Path(str(staged) + '.exr').replace(target)
    finally:
        for suffix in ('.pfm', '.exr'):
            if Path(str(staged) + suffix).exists():
                Path(str(staged) + suffix).unlink()


# Modo.
def read(item, records=None):
    """The light's Image Map layers that it draws by (effect Light Color, on), top first, each a dict: its image (path,
    srgb, color_space; from its record where the Shader Tree to MoonShine command took its clip out), opacity, blend,
    invert, and its locator's projection; and [(layer name, why)] for layers left out."""
    from .host import channel, world_matrix
    from . import shader_tree_lights, shader_tree_scene
    recorded = {r.get('layer'): r for r in (records or []) if r.get('layer')}
    found, left = [], []
    for layer in shader_tree_lights.light_layers(item):
        if layer.type != 'imageMap':
            continue
        enabled = bool(channel(layer, 'enable', 1)) and bool(channel(layer, 'render', 1))
        held = recorded.get(layer.id)
        if not enabled and held is None:
            continue
        source = shader_tree_scene.source_of(layer) if enabled else held.get('source')
        if not source or not source.get('filename'):
            if enabled:
                left.append((layer.name, 'it has no single image (a UDIM set or sequence is not drawn on a light)'))
            continue
        effect = str(channel(layer, 'effect', '') or '')
        if effect != EFFECT:
            left.append((layer.name, 'its effect is %s; a light draws Light Color alone' % (effect or 'none')))
            continue
        locator = next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator'), None)
        names = ('projType', 'projAxis', 'wrapU', 'wrapV', 'uvRotation', 'tileU', 'tileV', 'triplanarBlending')
        channels = {name: channel(locator, name, None) for name in names} if locator is not None else {}
        channels = {k: v for k, v in channels.items() if v is not None}
        matrix = world_matrix(locator) if locator is not None else [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        try:
            placed = projection(channels, matrix)
        except ValueError as exc:
            left.append((layer.name, str(exc)))
            continue
        path = str(source['filename'])
        space = str(source.get('colorspace') or '(default)')
        found.append({'name': layer.name, 'path': path, 'srgb': Path(path).suffix.lower() not in ('.exr', '.hdr', '.tx', '.pfm', '.tif', '.tiff'),
                      'color_space': '' if space == '(default)' else space,
                      'opacity': float(channel(layer, 'opacity', 1.0)), 'blend': str(channel(layer, 'blend', 'normal')),
                      'invert': bool(channel(layer, 'invert', 0)), 'alpha': str(channel(layer, 'alpha', 'use')),
                      'projection': placed, 'recorded': not enabled})
    return found, left


def _image(layer):
    """(pixels, alpha, width, height) of a layer's image, read once for each file as it stands (environment_layers)."""
    from . import environment_layers, textures
    path = textures.asset_path(layer['path'])
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, layer.get('srgb'), layer.get('color_space'), layer.get('alpha'))
    if key in _IMAGES:
        return _IMAGES[key]
    width, height = _size(path)
    scale = min(1.0, READ_SIZE / max(width, height))
    width, height = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    folder = textures.cache_root() / 'Light Images'
    folder.mkdir(parents=True, exist_ok=True)
    reading = {'path': str(path), 'srgb': layer.get('srgb', False), 'color_space': layer.get('color_space', ''),
               'image_channel': 'use' if layer.get('alpha', 'use') == 'use' else 'ignore'}
    pixels, alpha = environment_layers.image_pixels(reading, folder, width, height)
    if len(_IMAGES) > 8:
        _IMAGES.clear()
    _IMAGES[key] = held = (pixels, alpha, width, height)
    return held


_IMAGES = {}


def _size(path):
    import subprocess
    import xml.etree.ElementTree as ET
    from . import native
    tool = native.tool('oiiotool.exe')
    result = subprocess.run([str(tool), '--info:format=xml', '-v', str(path)], env=native.environment(tool.parent), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    text = result.stdout.decode(errors='replace')
    start, end = text.find('<ImageSpec'), text.find('</ImageSpec>')
    if start < 0 or end < 0:
        raise ValueError('cannot read the image %s' % path)
    spec = ET.fromstring(text[start:end + len('</ImageSpec>')])
    return int(spec.findtext('width')), int(spec.findtext('height'))


def apply(light, layers, warnings):
    """The light (a snapshot's dict) given its layers (read()): its colour, or its picture (texture, and its colour
    then white). Said in warnings where an image cannot be drawn."""
    if not layers:
        return
    kind = light['kind']
    label = light.get('name', light.get('identity', ''))
    if kind not in ONE_COLOUR + ACROSS:
        warnings.append('The image on light %s is not drawn: a %s shows no image.' % (label, kind))
        return
    base = [float(c) for c in light.get('color', [1, 1, 1])]
    try:
        images = [_image(layer) for layer in reversed(layers)]
    except (OSError, ValueError) as exc:
        warnings.append('The image on light %s is not drawn: %s.' % (label, exc))
        return
    ordered = list(reversed(layers))
    if kind in ONE_COLOUR:
        light['color'] = layered(base, ordered, images, [0.0, 0.0, 0.0])
        return
    if plain(ordered, images[0][1] is not None):
        try:
            light['texture'] = mirrored(ordered[0])
        except (OSError, ValueError) as exc:
            warnings.append('The image on light %s is not drawn: %s.' % (label, exc))
            return
        light['color'] = [1.0, 1.0, 1.0]
        return
    width, height = bake_size(ordered)
    if (width, height) == (1, 1):
        # The same all across (UV Map, Front, Implicit UV): one colour, as a light without a size is given it. MoonRay
        # stops on a light texture of one pixel ("1x1 mip level not supported").
        light['color'] = layered(base, ordered, images, [0.0, 0.0, 0.0])
        return
    from . import textures
    key = repr((VERSION, base, [(l['path'], Path(textures.asset_path(l['path'])).stat().st_mtime_ns, l['srgb'], l['color_space'], l['opacity'],
                                 l['blend'], l['invert'], l['alpha'], sorted(l['projection'].items())) for l in ordered], width, height))
    folder = textures.cache_root() / 'Light Images'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (hashlib.sha256(key.encode()).hexdigest()[:32] + '.exr')
    if not target.is_file():
        write_picture(target, bake(base, ordered, images, width, height), width, height)
    light['texture'] = str(target)
    light['color'] = [1.0, 1.0, 1.0]
