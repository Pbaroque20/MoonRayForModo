"""A scene's compositor: a graph of nodes over the buffers of a finished render, and what it makes of them.

The graph is kept with the scene's settings. Its nodes take the render's buffers (the beauty, the denoised beauty, any
output the scene asks for), put them together and correct them, and one node, the output, is the Composite buffer the
preview window lists beside the others. Nothing here renders: the picture is made from buffers a render has left, by
the image tool the runtime carries, one node after another.

A graph is {'nodes': {identity: {'type', 'parameters', 'inputs': {input: identity of the node wired to it},
'position'}}, 'root': the output node}. All the arithmetic is on linear values, before the display's transform.
"""
import copy
import hashlib
import json

# How two pictures are put together. a is what is beneath, b what is laid over it.
MODES = ('normal', 'add', 'multiply', 'screen', 'lighten', 'darken', 'difference')

MATH = ('add', 'subtract', 'multiply', 'divide', 'power', 'least of', 'most of')
FLIPS = ('left to right', 'top to bottom', 'both')
TAKES = ('the bright', 'the dark')
CHANNELS = ('brightness', 'red', 'green', 'blue')
RAMPS = ('left to right', 'top to bottom')

# Each kind of node: the pictures it takes, and its settings as (kind, default, least, most) or (kind, default, choices).
NODES = {
    'input': {'label': 'Buffer', 'inputs': (), 'tip': 'One of the render\'s buffers.',
              'parameters': {'buffer': ('buffer', 'beauty')}},
    'merge': {'label': 'Merge', 'inputs': ('a', 'b', 'mask'),
              'tip': 'Lays b over a. Mix is how much of the result is taken; a mask, where one is wired, says where.',
              'parameters': {'mode': ('choice', 'normal', MODES), 'mix': ('number', 1.0, 0.0, 1.0)}},
    'grade': {'label': 'Grade', 'inputs': ('image',), 'tip': 'Exposure in stops, then gamma, saturation and a tint.',
              'parameters': {'exposure': ('number', 0.0, -10.0, 10.0), 'gamma': ('number', 1.0, 0.1, 5.0),
                             'saturation': ('number', 1.0, 0.0, 4.0), 'tint': ('color', [1.0, 1.0, 1.0])}},
    'blur': {'label': 'Blur', 'inputs': ('image',), 'tip': 'A soft blur, its radius in pixels of the render.',
             'parameters': {'radius': ('number', 4.0, 0.0, 200.0)}},
    'glow': {'label': 'Glow', 'inputs': ('image',),
             'tip': 'What is brighter than the threshold, blurred and added back over the picture.',
             'parameters': {'threshold': ('number', 1.0, 0.0, 100.0), 'radius': ('number', 12.0, 0.0, 200.0),
                            'strength': ('number', 0.5, 0.0, 10.0)}},
    'output': {'label': 'Composite', 'inputs': ('image',), 'tip': 'The picture the Composite buffer shows.', 'parameters': {}},
    # Colour.
    'levels': {'label': 'Levels', 'inputs': ('image',), 'family': 'colour',
               'tip': 'What is at Black becomes Out Black and what is at White becomes Out White, with a gamma between.',
               'parameters': {'black': ('number', 0.0, -10.0, 100.0), 'white': ('number', 1.0, -10.0, 100.0), 'gamma': ('number', 1.0, 0.1, 5.0),
                              'out_black': ('number', 0.0, -10.0, 100.0), 'out_white': ('number', 1.0, -10.0, 100.0)}},
    'contrast': {'label': 'Contrast', 'inputs': ('image',), 'family': 'colour',
                 'tip': 'Pushes values away from the pivot, or draws them towards it. The pivot is the grey that stays as it is.',
                 'parameters': {'contrast': ('number', 1.2, 0.0, 4.0), 'pivot': ('number', 0.18, 0.0, 10.0)}},
    'invert': {'label': 'Invert', 'inputs': ('image',), 'family': 'colour', 'tip': 'One less each value: black for white.', 'parameters': {}},
    'clamp': {'label': 'Clamp', 'inputs': ('image',), 'family': 'colour', 'tip': 'Nothing under Least or over Most.',
              'parameters': {'least': ('number', 0.0, -100.0, 100.0), 'most': ('number', 1.0, -100.0, 1000.0)}},
    'tonemap': {'label': 'Tone Map', 'inputs': ('image',), 'family': 'colour',
                'tip': 'Brings bright values under one, the brightest most (Reinhard), after an exposure in stops.',
                'parameters': {'exposure': ('number', 0.0, -10.0, 10.0)}},
    'math': {'label': 'Math', 'inputs': ('image',), 'family': 'colour', 'tip': 'Every value with a number: added, multiplied and so on.',
             'parameters': {'operation': ('choice', 'multiply', MATH), 'value': ('number', 1.0, -1000.0, 1000.0)}},
    # Filters.
    'sharpen': {'label': 'Sharpen', 'inputs': ('image',), 'family': 'filter', 'tip': 'Edges made crisper: by how much, and how wide an edge is.',
                'parameters': {'amount': ('number', 0.5, 0.0, 5.0), 'radius': ('number', 1.5, 0.5, 20.0)}},
    'median': {'label': 'Median', 'inputs': ('image',), 'family': 'filter',
               'tip': 'Each pixel the middle value of those around it: takes out specks and keeps edges.',
               'parameters': {'radius': ('number', 1.0, 1.0, 6.0)}},
    'grow': {'label': 'Grow / Shrink', 'inputs': ('image',), 'family': 'filter',
             'tip': 'What is bright spread by so many pixels, or with a number under nothing, eaten back: for a matte\'s edge.',
             'parameters': {'pixels': ('number', 2.0, -20.0, 20.0)}},
    'edges': {'label': 'Edges', 'inputs': ('image',), 'family': 'filter', 'tip': 'Where the picture changes sharply, bright; black elsewhere.',
              'parameters': {'strength': ('number', 1.0, 0.0, 100.0)}},
    'grain': {'label': 'Grain', 'inputs': ('image',), 'family': 'filter', 'tip': 'A film\'s grain, the same in every colour, added over the picture.',
              'parameters': {'amount': ('number', 0.02, 0.0, 1.0), 'seed': ('number', 1.0, 0.0, 9999.0)}},
    'vignette': {'label': 'Vignette', 'inputs': ('image',), 'family': 'filter',
                 'tip': 'Darkens towards the edges: by how much at the corners, and how soon it begins.',
                 'parameters': {'amount': ('number', 0.5, 0.0, 1.0), 'falloff': ('number', 0.5, 0.05, 4.0)}},
    'flip': {'label': 'Flip', 'inputs': ('image',), 'family': 'filter', 'tip': 'The picture mirrored.',
             'parameters': {'direction': ('choice', 'left to right', FLIPS)}},
    # Mattes: grey pictures to wire to a Merge's mask.
    'luma_matte': {'label': 'Brightness Matte', 'inputs': ('image',), 'family': 'matte',
                   'tip': 'White where the picture is as bright as High, black where it is as dark as Low, grey between. For a Merge\'s mask.',
                   'parameters': {'low': ('number', 0.0, -10.0, 1000.0), 'high': ('number', 1.0, -10.0, 1000.0), 'take': ('choice', 'the bright', TAKES)}},
    'channel': {'label': 'Channel', 'inputs': ('image',), 'family': 'matte', 'tip': 'One channel of the picture, or its brightness, as grey.',
                'parameters': {'channel': ('choice', 'brightness', CHANNELS)}},
    # Pictures made from nothing.
    'constant': {'label': 'Colour', 'inputs': (), 'family': 'make', 'tip': 'A picture of one colour.',
                 'parameters': {'color': ('color', [0.5, 0.5, 0.5])}},
    'ramp': {'label': 'Ramp', 'inputs': (), 'family': 'make', 'tip': 'A picture running from one colour to another, across or down.',
             'parameters': {'direction': ('choice', 'left to right', RAMPS), 'start': ('color', [0.0, 0.0, 0.0]), 'end': ('color', [1.0, 1.0, 1.0])}},
}
# Buffers that are not pictures to put together.
UNUSABLE = ('cryptomatte',)


def new():
    """The graph a scene starts with: the beauty, as it is, to the output."""
    return {'nodes': {'beauty': {'type': 'input', 'parameters': {'buffer': 'beauty'}, 'inputs': {}, 'position': [0, 0]},
                      'out': {'type': 'output', 'parameters': {}, 'inputs': {'image': 'beauty'}, 'position': [260, 0]}},
            'root': 'out'}


def parameters(node):
    """A node's settings, each at its default where the node does not say."""
    schema = NODES[node['type']]['parameters']
    held = node.get('parameters') or {}
    return {key: copy.deepcopy(held.get(key, spec[1])) for key, spec in schema.items()}


def validate(graph):
    """The graph, checked and with nothing in it that is not understood. Raises ValueError saying what is wrong."""
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), dict):
        raise ValueError('The compositor graph is not a graph')
    nodes = {}
    for identity, node in graph['nodes'].items():
        if not isinstance(identity, str) or not identity or not isinstance(node, dict) or node.get('type') not in NODES:
            raise ValueError('Unknown compositor node: %s' % (node.get('type') if isinstance(node, dict) else identity))
        schema = NODES[node['type']]
        values = {}
        for key, spec in schema['parameters'].items():
            value = (node.get('parameters') or {}).get(key, spec[1])
            if spec[0] == 'number':
                value = float(value)
                if value != value or not spec[2] <= value <= spec[3]:
                    raise ValueError('%s of %s must be between %g and %g' % (key, schema['label'], spec[2], spec[3]))
            elif spec[0] == 'choice':
                if value not in spec[2]:
                    raise ValueError('%s of %s cannot be %s' % (key, schema['label'], value))
            elif spec[0] == 'color':
                value = [float(v) for v in value]
                if len(value) != 3 or not all(0.0 <= v <= 100.0 for v in value):
                    raise ValueError('%s of %s is not a colour' % (key, schema['label']))
            elif spec[0] == 'buffer':
                value = str(value)
                if not value or not all(c.isalnum() or c == '_' for c in value):
                    raise ValueError('Unknown buffer: ' + value)
            values[key] = value
        inputs = {key: source for key, source in (node.get('inputs') or {}).items() if key in schema['inputs'] and source}
        position = [float(v) for v in (node.get('position') or [0, 0])][:2]
        nodes[identity] = {'type': node['type'], 'parameters': values, 'inputs': inputs, 'position': position}
    for identity, node in nodes.items():
        for key, source in node['inputs'].items():
            if source not in nodes:
                raise ValueError('%s is wired to a node that is not there' % NODES[node['type']]['label'])
            if nodes[source]['type'] == 'output':
                raise ValueError('The Composite node is where the graph ends: nothing is wired from it')
    root = graph.get('root')
    if root not in nodes or nodes[root]['type'] != 'output':
        raise ValueError('The compositor graph has no Composite node')
    if sum(node['type'] == 'output' for node in nodes.values()) != 1:
        raise ValueError('The compositor graph has more than one Composite node')
    order(dict(nodes=nodes, root=root))
    return {'nodes': nodes, 'root': root}


def order(graph):
    """The nodes the output is made from, each after those it takes from. Raises ValueError on a loop."""
    nodes, found, on_path = graph['nodes'], [], set()

    def visit(identity):
        if identity in found:
            return
        if identity in on_path:
            raise ValueError('The compositor graph feeds a node from itself')
        on_path.add(identity)
        for source in nodes[identity]['inputs'].values():
            visit(source)
        on_path.discard(identity)
        found.append(identity)
    visit(graph['root'])
    return found


def trivial(graph):
    """Whether the graph does nothing: none, or the beauty wired straight to the output."""
    if not graph or not graph.get('nodes'):
        return True
    try:
        graph = validate(graph)
    except ValueError:
        return False
    wired = graph['nodes'][graph['root']]['inputs'].get('image')
    return wired is None or (graph['nodes'][wired]['type'] == 'input' and graph['nodes'][wired]['parameters']['buffer'] == 'beauty')


def buffers(graph):
    """The buffers the output is made from."""
    graph = validate(graph)
    return sorted({graph['nodes'][identity]['parameters']['buffer'] for identity in order(graph) if graph['nodes'][identity]['type'] == 'input'})


def signature(graph):
    """What tells one graph's picture from another's: the graph without where its nodes are placed."""
    graph = validate(graph)
    kept = {identity: {'type': graph['nodes'][identity]['type'], 'parameters': graph['nodes'][identity]['parameters'],
                       'inputs': graph['nodes'][identity]['inputs']} for identity in order(graph)}
    return hashlib.sha256(json.dumps([kept, graph['root']], sort_keys=True).encode('utf-8')).hexdigest()


def _channels(kind):
    """A buffer of any kind as three numbers a pixel."""
    if kind in ('alpha', 'depth', 'wireframe', 'sample_count'):
        return ['--ch', '0,0,0']
    if kind in ('uv', 'motion', 'motion_vectors'):
        return ['--ch', '0,1,B=0']
    return ['--ch', '0,1,2']


def _number(value):
    return repr(round(float(value), 6))


def _kernel(radius):
    """A blur's kernel for a radius in pixels: an odd number of pixels across, wide enough for the bell to die away."""
    across = max(1, int(round(float(radius) * 4)) | 1)
    return '%dx%d' % (across, across)


# The widest blur done on the picture as it is. The image tool's blur is not done a row and a column at a time: its
# cost grows with the square of the radius, and a radius of 20 on a 1280 x 720 picture took eight seconds.
DIRECT = 4.0


def _blur(radius):
    """What blurs the picture on top of the stack by a radius in pixels. A wide blur is done on the picture made
    smaller, by as much as brings the radius down to DIRECT, and the result made as large as the picture was: the
    same softness to the eye, in a fraction of a second."""
    radius = float(radius)
    if radius <= DIRECT:
        return ['--blur', _kernel(radius)]
    return ['--dup', '--resize', '%s%%' % _number(100.0 * DIRECT / radius), '--blur', _kernel(DIRECT),
            '--resize', '{IMG[1].width}x{IMG[1].height}', '--swap', '--pop']


LUMA = '--chsum:weight=0.2126,0.7152,0.0722'


def _colour(values):
    return ','.join(_number(v) for v in values)


def _levels(image, held):
    span = float(held['white']) - float(held['black'])
    span = span if abs(span) > 1e-6 else 1e-6
    return [image, '--subc', _number(held['black']), '--mulc', _number(1.0 / span), '--maxc', '0', '--powc', _number(1.0 / float(held['gamma'])),
            '--mulc', _number(float(held['out_white']) - float(held['out_black'])), '--addc', _number(held['out_black'])]


def _math(image, held):
    value = float(held['value'])
    if held['operation'] == 'divide':
        return [image, '--mulc', _number(1.0 / value if abs(value) > 1e-9 else 0.0)]
    if held['operation'] == 'power':
        # A power of a negative number is not a number: what is under black stays black.
        return [image, '--maxc', '0', '--powc', _number(value)]
    return [image, {'add': '--addc', 'subtract': '--subc', 'multiply': '--mulc', 'least of': '--minc', 'most of': '--maxc'}[held['operation']], _number(value)]


def _grow(image, held):
    pixels = int(round(float(held['pixels'])))
    if not pixels:
        return None
    across = 2 * abs(pixels) + 1
    return [image, '--dilate' if pixels > 0 else '--erode', '%dx%d' % (across, across)]


def _vignette(image, held):
    # Across the picture and down it, a hump that is one in the middle and nothing at the edge; the two multiplied
    # are one at the centre and nothing along every edge. The picture is darkened by Amount where that is nothing.
    hump = lambda first, second: ['--pattern', 'fill:%s=0,0,0:%s=1,1,1' % (first, second), '{TOP.width}x{TOP.height}', '3',
                                  '--dup', '--invert', '--mul', '--mulc', '4']
    amount = float(held['amount'])
    return ([image] + hump('left', 'right') + hump('top', 'bottom') + ['--mul', '--maxc', '0', '--powc', _number(held['falloff']),
            '--mulc', _number(amount), '--addc', _number(1.0 - amount), '--mul'])


def _luma_matte(image, held):
    span = float(held['high']) - float(held['low'])
    span = span if abs(span) > 1e-6 else 1e-6
    args = [image, LUMA, '--ch', '0,0,0', '--subc', _number(held['low']), '--mulc', _number(1.0 / span), '--maxc', '0', '--minc', '1']
    return args + (['--invert'] if held['take'] == 'the dark' else [])


def _ramp(black, held):
    first, second = ('left', 'right') if held['direction'] == 'left to right' else ('top', 'bottom')
    return [black, '--pattern', 'fill:%s=%s:%s=%s' % (first, _colour(held['start']), second, _colour(held['end'])),
            '{TOP.width}x{TOP.height}', '3', '--swap', '--pop']


# What each node that works on one picture asks of the image tool, given the picture and its settings; None where it
# is set to do nothing. And the same for those that make a picture, given a black one of the render's size.
WORKERS = {
    'levels': _levels,
    'contrast': lambda image, held: [image, '--subc', _number(held['pivot']), '--mulc', _number(held['contrast']), '--addc', _number(held['pivot'])],
    'invert': lambda image, held: [image, '--invert'],
    'clamp': lambda image, held: [image, '--maxc', _number(held['least']), '--minc', _number(held['most'])],
    'tonemap': lambda image, held: [image, '--mulc', _number(2.0 ** float(held['exposure'])), '--maxc', '0', '--dup', '--addc', '1', '--div'],
    'math': _math,
    'sharpen': lambda image, held: None if float(held['amount']) < 1e-4 else
        [image, '--unsharp:kernel=gaussian:width=%s:contrast=%s:threshold=0' % (_number(2 * float(held['radius']) + 1), _number(held['amount']))],
    'median': lambda image, held: [image, '--median', '%dx%d' % ((2 * int(round(float(held['radius']))) + 1,) * 2)],
    'grow': _grow,
    'edges': lambda image, held: [image, '--laplacian', '--abs', '--mulc', _number(held['strength'])],
    'grain': lambda image, held: None if float(held['amount']) < 1e-6 else
        [image, '--noise:type=gaussian:mean=0:stddev=%s:mono=1:seed=%d' % (_number(held['amount']), int(float(held['seed'])))],
    'vignette': _vignette,
    'flip': lambda image, held: [image, {'left to right': '--flop', 'top to bottom': '--flip', 'both': '--rotate180'}[held['direction']]],
    'luma_matte': _luma_matte,
    'channel': lambda image, held: [image, LUMA, '--ch', '0,0,0'] if held['channel'] == 'brightness' else
        [image, '--ch', ','.join([str(('red', 'green', 'blue').index(held['channel']))] * 3)],
}
MAKERS = {
    'constant': lambda black, held: [black, '--addc', _colour(held['color'])],
    'ramp': _ramp,
}


def jobs(graph, files, kinds, folder, channels=None):
    """What the image tool is to be run with, node after node: [(arguments, the file that run makes)], and the file
    that is the output's picture. files has each buffer's file and kinds what kind of buffer each is. A wired input
    that is left out of a node is black; a node with nothing to work on is black too. channels, where given, says
    for a buffer what picks it out of its file, in place of what its kind would: for buffers that are channels of
    one EXR."""
    from pathlib import Path
    graph = validate(graph)
    folder = Path(folder)
    made, steps = {}, []
    black = None

    def none():
        nonlocal black
        if black is None:
            # As large as the render, and black: made from a buffer the frame is sure to have.
            source = files.get('beauty') or next(iter(files.values()))
            black = folder / 'black.exr'
            steps.append((['--no-autopremult', str(source), '--fixnan', 'black', '--ch', '0,1,2', '--mulc', '0', '-d', 'float', '-o', str(black)], black))
        return black

    for identity in order(graph):
        node = graph['nodes'][identity]
        kind, held = node['type'], node['parameters']
        taken = {key: made[source] for key, source in node['inputs'].items()}
        target = folder / (identity + '.exr')
        if kind == 'input':
            key = held['buffer']
            if key not in files or kinds.get(key) in UNUSABLE:
                raise ValueError('The render has no %s buffer for the compositor to take' % key)
            args = ['--no-autopremult', str(files[key]), '--fixnan', 'black'] + ((channels or {}).get(key) or _channels(kinds.get(key, key)))
        elif kind == 'output':
            made[identity] = taken.get('image') or none()
            continue
        elif kind == 'merge':
            a, b = str(taken.get('a') or none()), taken.get('b')
            if b is None:
                made[identity] = taken.get('a') or none()
                continue
            b = str(b)
            merged = {'normal': [b], 'add': [a, b, '--add'], 'multiply': [a, b, '--mul'],
                      'screen': [a, '--invert', b, '--invert', '--mul', '--invert'],
                      'lighten': [a, b, '--max'], 'darken': [a, b, '--min'], 'difference': [a, b, '--absdiff']}[held['mode']]
            # a + (merged - a) * mix * mask
            args = merged + [a, '--sub']
            if taken.get('mask') is not None:
                args += [str(taken['mask']), '--mul']
            args += ['--mulc', _number(held['mix']), a, '--add']
        elif kind == 'grade':
            if taken.get('image') is None:
                made[identity] = none()
                continue
            gain = 2.0 ** float(held['exposure'])
            args = [str(taken['image']), '--mulc', ','.join(_number(gain * v) for v in held['tint'])]
            if abs(float(held['gamma']) - 1.0) > 1e-6:
                # A power of a negative number is not a number: what is under black stays black.
                args += ['--maxc', '0', '--powc', _number(1.0 / float(held['gamma']))]
            if abs(float(held['saturation']) - 1.0) > 1e-6:
                args += ['--saturate', _number(held['saturation'])]
        elif kind == 'blur':
            if taken.get('image') is None:
                made[identity] = none()
                continue
            if float(held['radius']) < 0.25:
                made[identity] = taken['image']
                continue
            args = [str(taken['image'])] + _blur(held['radius'])
        elif kind == 'glow':
            if taken.get('image') is None:
                made[identity] = none()
                continue
            image = str(taken['image'])
            args = [image, '--subc', _number(held['threshold']), '--maxc', '0']
            if float(held['radius']) >= 0.25:
                args += _blur(held['radius'])
            args += ['--mulc', _number(held['strength']), image, '--add']
        elif kind in MAKERS:
            args = MAKERS[kind](str(none()), held)
        elif kind in WORKERS:
            if taken.get('image') is None:
                made[identity] = none()
                continue
            args = WORKERS[kind](str(taken['image']), held)
            if args is None:
                # Set to do nothing: the picture passes as it is.
                made[identity] = taken['image']
                continue
        steps.append((args + ['-d', 'float', '-o', str(target)], target))
        made[identity] = target
    return steps, made[graph['root']]
