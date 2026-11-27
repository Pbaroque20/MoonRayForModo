"""Modo image clips beyond a still image: image sequences, and the clip and layer choices that change how an image is
read, for a render of the Shader Tree (layers.collect), for the graph's Image node (nodes.emit, MoonLightIPR's
graph_image) and for Move Shader Tree Textures to MoonShine Graphs (shader_tree_transfer, shader_tree_scene).

An image sequence clip (videoSequence) names its files by a pattern, seq.[####].png, the run of # the frame's number
padded with zeros. Which of its files Modo shows at a scene frame, as measured against Modo's own renders
(tools/probe_cl_clip_frames.py; the sequence's frames First to Last, starting at the scene frame Start Frame):
  hold      before its start the first file, past its end the last;
  repeat    over and over; before its start backwards, as Modo has it (one frame before: the third file of five);
  pingpong  forth once, then back and forth from the next to last, with a frame of no image at each turn back, and
            no image before its start, as Modo has it.
The Image node carries the pattern and these (sequence, first_frame, last_frame, start_frame, end_behavior); the
frame's file is found when the scene is read for each frame (host.material_values), so MoonRay, XPU2 and MoonLightIPR
are given the frame's file as any other image.

A clip's Alpha (alphaMode, 0: ignored) leaves its alpha out: the image is read as with the layer's Alpha set to
Ignore. A layer's pixel blending (Nearest, Bilinear, Bicubic) is recorded: MoonRay's ImageMap filters each texture one
way, which the kit renders a layer with whatever its blending."""
import copy
import re
from pathlib import Path

BEHAVIOURS = ('hold', 'repeat', 'pingpong')
# The Image node's parameters for a sequence, and their defaults (a still image).
SEQUENCE_PARAMETERS = {'sequence': False, 'first_frame': 1, 'last_frame': 1, 'start_frame': 0, 'end_behavior': 'hold'}
PATTERN = re.compile(r'\[(#+)\]')
SEQUENCE_TYPE = 'videoSequence'


# Which file, at which frame.
def sequence_index(frame, first, last, start=0, behaviour='hold'):
    """The sequence's file (0 its first) Modo shows at a scene frame, or None for no image."""
    count = int(last) - int(first) + 1
    if count < 1:
        return None
    at = int(frame) - int(start)
    if count == 1:
        return 0 if behaviour != 'pingpong' or at >= 0 else None
    if behaviour == 'repeat':
        return at % count if at >= 0 else (1 - at) % count
    if behaviour == 'pingpong':
        if at < 0:
            return None
        if at < count:
            return at
        turn = at % (2 * count - 2)
        index = turn if turn < count - 1 else count + 1 - turn
        return index if 0 <= index < count else None
    return min(max(at, 0), count - 1)


def pattern_file(pattern, number):
    """The file of a sequence's pattern for one of its frame numbers."""
    pattern = str(pattern)
    found = PATTERN.search(pattern)
    if not found:
        return pattern
    digits = len(found.group(1))
    text = ('-%0*d' % (digits - 1, -number)) if number < 0 else '%0*d' % (digits, number)
    return pattern[:found.start()] + text + pattern[found.end():]


def is_pattern(path):
    return bool(PATTERN.search(str(path or '')))


def frame_file(values, frame):
    """The file of a sequence ({pattern or file, first_frame, last_frame, start_frame, end_behavior}) at a scene frame,
    or '' where Modo shows no image then."""
    pattern = values.get('pattern') or values.get('file') or ''
    first = int(values.get('first_frame', 1))
    index = sequence_index(frame, first, values.get('last_frame', first), values.get('start_frame', 0), values.get('end_behavior', 'hold'))
    return '' if index is None else pattern_file(pattern, first + index)


def scene_frame():
    """The scene's frame now (its time times its frame rate), or 0 where there is no Modo."""
    try:
        import lx
        import modo
        return int(round(lx.service.Selection().GetTime() * float(modo.Scene().fps)))
    except Exception:
        return 0


# Modo's clips, as layers.collect reads them.
class FrameClip:
    """A sequence clip as the still of the frame: what layers.collect reads of a still (its filename, colour space)."""

    def __init__(self, clip, filename):
        self._clip = clip
        self.id = getattr(clip, 'id', '') + '|frame'
        self.name = getattr(clip, 'name', '')
        self.type = 'videoStill'
        self._filename = filename

    def channel(self, name):
        if name == 'filename':
            return _Value(self._filename)
        return self._clip.channel(name)

    def __getattr__(self, name):
        return getattr(self._clip, name)


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self, *args):
        return self.value


def read_sequence(clip, channel):
    """A sequence clip's settings: {pattern, first_frame, last_frame, start_frame, end_behavior}."""
    behaviour = str(channel(clip, 'endBehavior', 'hold') or 'hold')
    if behaviour not in BEHAVIOURS:
        behaviour = 'hold'
    first = int(channel(clip, 'firstFrame', 1))
    return {'pattern': str(channel(clip, 'pattern', '') or ''), 'first_frame': first,
            'last_frame': int(channel(clip, 'lastFrame', first)), 'start_frame': int(channel(clip, 'startFrame', 0)),
            'end_behavior': behaviour}


def sequence_clip(connected, channel, frame=None):
    """(the frame's still as a clip, the sequence's settings) of the first image sequence among a layer's links, or
    (None, None). ValueError where the sequence shows no image at the frame (the layer is then left out, as Modo draws
    nothing of it)."""
    clip = next((i for i in connected if i.type == SEQUENCE_TYPE), None)
    if clip is None:
        return None, None
    held = read_sequence(clip, channel)
    if not held['pattern']:
        raise ValueError('its image sequence %s names no files' % clip.name)
    frame = scene_frame() if frame is None else frame
    filename = frame_file(held, frame)
    if not filename:
        raise ValueError('its image sequence %s shows no image at frame %d' % (clip.name, frame))
    return FrameClip(clip, filename), held


def alpha_ignored(clip, channel):
    """Whether a clip's own Alpha says to leave its alpha out (alphaMode 0)."""
    try:
        return clip is not None and int(channel(clip, 'alphaMode', 1)) == 0
    except (TypeError, ValueError):
        return False


def layer_channel(clip, channel, source_channel):
    """A layer's image channel with its clip's Alpha: an alpha the clip leaves out is not used."""
    if source_channel == 'use' and alpha_ignored(clip, channel):
        return 'ignore'
    return source_channel


def note(node, clip, channel, layer, held=None, path=None):
    """What layers.collect records on a layer's dict of its clip: the sequence (its pattern as the frame's file was
    found, in the frame's folder), the clip's Alpha, the layer's pixel blending."""
    if held is not None:
        pattern = held['pattern']
        if path is not None:
            pattern = str(Path(str(path)).parent / Path(pattern.replace('\\', '/')).name).replace('\\', '/')
        node['sequence'] = dict(held, pattern=pattern)
    if alpha_ignored(clip, channel):
        node['clip_alpha'] = 'ignore'
    blending = channel(layer, 'pixBlend', 'bilinear')
    if blending and blending != 'bilinear':
        node['pixel_blend'] = str(blending)


# The Image node.
def image_parameters(layer):
    """The Image node's parameters beyond a still's for a layer read by layers.collect: its sequence ({} for a still).
    The file is the pattern; the frame's is found when the scene is read (framed)."""
    held = layer.get('sequence')
    if not held:
        return {}
    return {'file': held['pattern'], 'sequence': True, 'first_frame': int(held['first_frame']), 'last_frame': int(held['last_frame']),
            'start_frame': int(held['start_frame']), 'end_behavior': held['end_behavior']}


def framed_parameters(parameters, frame=None):
    """An Image node's parameters with its sequence's file for the frame (as they are for a still)."""
    if not parameters.get('sequence'):
        return parameters
    frame = scene_frame() if frame is None else frame
    held = dict(parameters)
    held['file'] = frame_file(parameters, frame)
    held['sequence'] = False
    return held


def file_of(parameters, frame=None):
    """The file an Image node reads (its sequence's at the frame)."""
    return framed_parameters(parameters, frame).get('file', '') if parameters.get('sequence') else parameters.get('file', '')


def framed_graph(graph, frame=None):
    """A graph with each sequence Image node naming the frame's file, the graph itself where it has none."""
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), dict):
        return graph
    found = [key for key, node in graph['nodes'].items()
             if isinstance(node, dict) and node.get('type') == 'image' and (node.get('parameters') or {}).get('sequence')]
    if not found:
        return graph
    frame = scene_frame() if frame is None else frame
    graph = dict(graph, nodes=dict(graph['nodes']))
    for key in found:
        node = graph['nodes'][key] = dict(graph['nodes'][key])
        node['parameters'] = framed_parameters(node['parameters'], frame)
    return graph


# Move Shader Tree Textures to MoonShine Graphs: the checks and foregrounds shader_tree_transfer calls for a layer with
# the dict key named (where layer.get(key) is set), in the form plan's check() and image() have.
def check_sequence(layer, effect):
    from .shader_tree_transfer import Refused, effect_name
    held = layer.get('sequence') or {}
    if held.get('end_behavior', 'hold') not in BEHAVIOURS:
        raise Refused('its image sequence ends by %s, which the Image node has not' % held.get('end_behavior'))
    if not is_pattern(held.get('pattern')):
        raise Refused('its image sequence names its files by no frame number')
    if effect in ('normal', 'bump'):
        raise Refused('a %s image sequence: the normal input takes one still image' % effect_name(effect))


def foreground_sequence(builder, layer, effect, alpha_of):
    """The layer's image as shader_tree_transfer.image makes it, its Image nodes reading the sequence: the pattern and
    its frames on each, so that the frame's file is found as the scene is read. A sequence that shows no image at some
    frames is laid on by its alpha too, which is nothing where there is no image (the node's default)."""
    from . import shader_tree_transfer as transfer
    value, mask = transfer.image(builder, layer, effect, alpha_of)
    extra = image_parameters(layer)
    identity = layer['identity']
    nodes = [builder.nodes.get(transfer.node_id(identity, role)) for role in ('image', 'alpha')]
    for node in nodes:
        if node is not None:
            node['parameters'].update(extra)
            node[transfer.NODE_KEY]['sequence'] = dict(layer['sequence'])
    held = layer['sequence']
    gaps = held['end_behavior'] == 'pingpong' and int(held['last_frame']) > int(held['first_frame'])
    if gaps and mask is None and nodes[0] is not None:
        image = nodes[0]
        mask = builder.add(identity, 'alpha', 'image', dict(image['parameters'], channel=4, invert=False),
                           {'texcoord': ('n', image['inputs']['texcoord'])} if 'texcoord' in image['inputs'] else None,
                           label=(layer.get('name') or identity) + ' alpha', data={'sequence': dict(held)})
    return value, mask


def foreground_clip(builder, layer, effect, alpha_of):
    """A still layer whose clip or blending says more than the image: drawn as shader_tree_transfer.image draws it (its
    clip's Alpha is in its image channel already, as layers.collect read it), the choices kept on its Image node's record."""
    from . import shader_tree_transfer as transfer
    value, mask = transfer.image(builder, layer, effect, alpha_of)
    node = builder.nodes.get(transfer.node_id(layer['identity'], 'image'))
    if node is not None:
        for key in ('clip_alpha', 'pixel_blend'):
            if layer.get(key):
                node[transfer.NODE_KEY][key] = layer[key]
    return value, mask


CHECKS = {'sequence': check_sequence}
FOREGROUNDS = {'sequence': foreground_sequence, 'clip_alpha': foreground_clip, 'pixel_blend': foreground_clip}


def hooks(layer):
    """(the checks, the foreground) that apply to a layer: CHECKS' and FOREGROUNDS' entries whose key it has, the first
    foreground that applies (sequence first), or None for shader_tree_transfer.image's own."""
    checks = [fn for key, fn in CHECKS.items() if layer.get(key)]
    foreground = next((fn for key, fn in FOREGROUNDS.items() if layer.get(key)), None)
    return checks, foreground


# shader_tree_scene: a sequence clip recorded, taken out and loaded again.
def source_of_sequence(clip, channel):
    """What a layer's image sequence is, for its node's record: its settings, its colour space, its Alpha."""
    held = read_sequence(clip, channel)
    held.update(sequence=True, colorspace=channel(clip, 'colorspace', '(default)'), clip=clip.name,
                alpha_mode=int(channel(clip, 'alphaMode', 1)))
    return held


def first_file(source):
    """A file of a recorded sequence that is there, to load it again by (clip.addSequence finds the rest)."""
    first = int(source.get('first_frame', 1))
    for number in range(first, int(source.get('last_frame', first)) + 1):
        candidate = pattern_file(source['pattern'], number)
        if Path(candidate).is_file():
            return candidate
    return None
