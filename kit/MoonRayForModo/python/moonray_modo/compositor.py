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


def jobs(graph, files, kinds, folder):
    """What the image tool is to be run with, node after node: [(arguments, the file that run makes)], and the file
    that is the output's picture. files has each buffer's file and kinds what kind of buffer each is. A wired input
    that is left out of a node is black; a node with nothing to work on is black too."""
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
            args = ['--no-autopremult', str(files[key]), '--fixnan', 'black'] + _channels(kinds.get(key, key))
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
        steps.append((args + ['-d', 'float', '-o', str(target)], target))
        made[identity] = target
    return steps, made[graph['root']]
