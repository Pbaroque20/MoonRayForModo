# python
"""Command line: how Modo reads an image sequence clip, and what its clip and Image Map choices are. Writes
MOONRAY_PROBE_OUT/clip_frames.json (default test-results/clip-frames):
  hints     the choices of the clip's alphaMode, endBehavior, holdType and the Image Map's pixBlend, as Modo lists them;
  frames    for each End Behavior and Start Frame tried, the sequence frame Modo's own renderer shows at each scene frame
            (a camera filled by a plane glowing with the sequence, each of whose 5 images is one colour of its own;
            None where it shows none of them).
Run with tools/launch_cl_probe.py --profile <a copy of the test profile>."""
import json
import os
import pathlib
import struct
import traceback
import zlib
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-af3d27f0b82fde226\test-results\clip-frames')
out.mkdir(parents=True, exist_ok=True)
report = {}
COLOURS = {frame: (frame * 40, 20, 255 - frame * 40) for frame in range(1, 6)}


def png(path, rgb):
    rows = b''.join(b'\0' + bytes(rgb) * 8 for _ in range(8))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def read_png(path):
    """The middle pixel of an 8-bit RGB or RGBA PNG."""
    data = path.read_bytes()
    at, idat, width, height, kind = 8, b'', 0, 0, 2
    while at < len(data):
        size = struct.unpack('>I', data[at:at + 4])[0]
        tag = data[at + 4:at + 8]
        body = data[at + 8:at + 8 + size]
        if tag == b'IHDR':
            width, height, depth, kind = struct.unpack('>IIBB', body[:10])
        elif tag == b'IDAT':
            idat += body
        at += 12 + size
    channels = {2: 3, 6: 4}[kind]
    raw = zlib.decompress(idat)
    stride = width * channels
    previous = bytearray(stride)
    rows = []
    for y in range(height):
        filt = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = previous[x]
            c = previous[x - channels] if x >= channels else 0
            if filt == 1:
                line[x] = (line[x] + a) & 255
            elif filt == 2:
                line[x] = (line[x] + b) & 255
            elif filt == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        previous = line
    middle = rows[height // 2]
    return tuple(middle[(width // 2) * channels:(width // 2) * channels + 3])


def which(rgb):
    best = min(COLOURS, key=lambda f: sum((a - b) ** 2 for a, b in zip(COLOURS[f], rgb)))
    return best if sum((a - b) ** 2 for a, b in zip(COLOURS[best], rgb)) < 300 else [list(rgb)]


def hints(item, name):
    internal = item.internalItem
    try:
        index = internal.ChannelLookup(name)
        found = internal.ChannelIntHint(index)
        return [list(h) if isinstance(h, (list, tuple)) else h for h in found] if found else found
    except Exception as exc:
        return 'error %s' % exc


try:
    for frame in COLOURS:
        png(out / ('seq.%04d.png' % frame), COLOURS[frame])
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 16), ('resY', 16)):
        render.channel(name).set(value)
    for name, value in (('globEnable', 0), ('aaSamples', 1)):
        try:
            render.channel(name).set(value)
        except Exception:
            pass
    lx.eval('clip.addSequence {%s}' % (out / 'seq.0001.png'))
    clip = next(iter(scene.items('videoSequence')))
    layer = scene.addItem('imageMap')
    report['hints'] = {'alphaMode': hints(clip, 'alphaMode'), 'endBehavior': hints(clip, 'endBehavior'), 'holdType': hints(clip, 'holdType'),
                       'pixBlend': hints(layer, 'pixBlend'), 'interlace': hints(clip, 'interlace')}
    # A plane in front of the camera, glowing with the sequence.
    plane = scene.addMesh('Plane')
    with plane.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0))]
        geo.polygons.new(points)
    material = next(i for i in scene.items('advancedMaterial'))
    for name, value in (('diffAmt', 0.0), ('specAmt', 0.0), ('reflAmt', 0.0), ('radiance', 1.0)):
        try:
            material.channel(name).set(value)
        except Exception:
            pass
    # Just above the material (children are bottom first), below the Base Shader, where Modo applies it.
    siblings = list(material.parent.children())
    layer.setParent(material.parent, siblings.index(next(s for s in siblings if s.id == material.id)) + 1)
    shader = next(i for i in material.parent.children() if i.type == 'defaultShader')
    shader.setParent(material.parent, len(list(material.parent.children())))
    report['tree'] = [(i.type, i.name) for i in reversed(list(material.parent.children()))]
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, clip._item)
    layer.channel('effect').set('lumiColor')
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('planar')
    locator.channel('projAxis').set(2)
    locator.channel('sclX').set(10.0) if locator.channel('sclX') else None
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 3.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    for light in list(scene.items('light')):
        light.channel('radiance').set(0.0)
    report['frames'] = {}
    cases = [('hold', 0), ('hold', 3), ('repeat', 0), ('repeat', 3), ('pingpong', 0), ('pingpong', 3)]
    only = os.environ.get('MOONRAY_PROBE_CASES')
    if only:
        cases = [c for c in cases if '%s_%d' % c in only.split(',')]
    for behaviour, start in cases:
        try:
            clip.channel('endBehavior').set(behaviour)
            clip.channel('startFrame').set(start)
            # MOONRAY_PROBE_HOLD: the clip's Frame Hold (holdType) for every case.
            clip.channel('holdType').set(os.environ.get('MOONRAY_PROBE_HOLD') or 'frameHoldOn')
        except Exception as exc:
            report['frames']['%s start %d' % (behaviour, start)] = 'error %s' % exc
            continue
        render.channel('first').set(-2)
        render.channel('last').set(int(os.environ.get('MOONRAY_PROBE_LAST') or 12))
        folder = out / ('%s_%d' % (behaviour, start))
        folder.mkdir(exist_ok=True)
        lx.eval('!render.animation {%s} PNG' % str(folder / 'f'))
        seen = {}
        for path in sorted(folder.glob('f*.png')):
            digits = ''.join(c for c in path.stem[1:] if c.isdigit() or c == '-')
            seen[digits] = which(read_png(path))
        report['frames']['%s start %d' % (behaviour, start)] = seen
        (out / 'clip_frames.json').write_text(json.dumps(report, indent=1, default=str))
    # Alpha Mode: a still of (100, 60, 20) at alpha 128 over the material's white glow, for each mode.
    rows = b''.join(b'\0' + bytes((100, 60, 20, 128)) * 8 for _ in range(8))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    (out / 'half.png').write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 6, 0, 0, 0))
                                   + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    lx.eval('clip.addStill {%s}' % (out / 'half.png'))
    still = next(i for i in scene.items('videoStill') if i.name == 'half')
    graph.DeleteLink(layer._item, clip._item)
    graph.AddLink(layer._item, still._item)
    render.channel('first').set(1)
    render.channel('last').set(1)
    report['alpha'] = {}
    for mode in range(0, 5):
        try:
            still.channel('alphaMode').set(mode)
        except Exception as exc:
            report['alpha'][mode] = 'error %s' % exc
            continue
        folder = out / ('alpha_%d' % mode)
        folder.mkdir(exist_ok=True)
        lx.eval('!render.animation {%s} PNG' % str(folder / 'f'))
        found = sorted(folder.glob('f*.png'))
        report['alpha'][mode] = [still.channel('alphaMode').get(), list(read_png(found[0])) if found else None]
    for blend in ('nearest', 'bilinear', 'bicubic'):
        layer.channel('pixBlend').set(blend)
    report['alpha_mode_now'] = still.channel('alphaMode').get()
except Exception:
    report['error'] = traceback.format_exc()
(out / 'clip_frames.json').write_text(json.dumps(report, indent=1, default=str))
