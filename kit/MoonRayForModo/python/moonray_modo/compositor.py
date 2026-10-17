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
# A Sum node's inputs: as many pictures as are wired, added up. The editor shows those wired and one free.
SUM_INPUTS = tuple('in%d' % n for n in range(1, 33))

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
    'sum': {'label': 'Sum', 'inputs': SUM_INPUTS, 'tip': 'Every picture wired in, added up: render passes back into one picture.',
            'parameters': {}},
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


def ports(node):
    """The inputs a node shows: all of its kind's, but for a Sum, those wired and the next free one."""
    kind = node['type']
    if kind != 'sum':
        return list(NODES[kind]['inputs'])
    wired = [key for key in SUM_INPUTS if (node.get('inputs') or {}).get(key)]
    free = next((key for key in SUM_INPUTS if key not in wired), None)
    return sorted(wired + ([free] if free else []), key=SUM_INPUTS.index)


def port_label(key):
    """What an input is called on the canvas."""
    return 'input %s' % key[2:] if key in SUM_INPUTS else key


# Render passes that together make the beauty: what the camera's ray meets first tells them apart, and diffuse and
# glossy are split into the light that comes straight from the lights and the light that has bounced first. What none
# of them takes (fog, and any path these leave out) is the remainder, worked out from the beauty (pass_graph).
# (what it is called, the output's name, the light path expression)
PASSES = (('Emission', 'pass_emission', 'CO'),
          ('Lights and sky seen', 'pass_lights_seen', 'CL'),
          ('Direct diffuse', 'pass_diffuse_direct', 'C<RD>[<L.>O]'),
          ('Indirect diffuse', 'pass_diffuse_indirect', 'C<RD>[DSG]+[<L.>O]'),
          ('Direct glossy', 'pass_glossy_direct', 'C<RG>[<L.>O]'),
          ('Indirect glossy', 'pass_glossy_indirect', 'C<RG>[DSG]+[<L.>O]'),
          ('Mirror reflection', 'pass_mirror', 'C<RS>[DSG]*[<L.>O]'),
          ('Refraction', 'pass_refraction', 'C<TS>[DSG]*[<L.>O]'),
          ('Glossy transmission', 'pass_transmission_glossy', 'C<TG>[DSG]*[<L.>O]'),
          ('Translucency', 'pass_translucency', 'C<TD>[DSG]*[<L.>O]'))


# Modo's environment (the plugin's, and each in the scene) carries this label: its light is a group of its own.
ENVIRONMENT_LABEL = 'modo_environment'


def light_groups(production, entities=()):
    """The light groups to build from, as (what it is called, label): the environment's light, then each label the
    scene's lights carry."""
    return [('Environment', ENVIRONMENT_LABEL)] + [(label, label) for label in light_labels(production, entities) if label != ENVIRONMENT_LABEL]


def light_group_expression(label):
    """All the light that comes from the lights of one group (their label), by any path."""
    return "C.*<L.'%s'>" % label


def scene_passes(custom_aovs, wanted):
    """The light path outputs a scene has besides the wanted passes, as passes to offer too: (name, name, expression)."""
    known = {expression for words, name, expression in wanted}
    return [(entry['name'], entry['name'], entry['expression'].strip()) for entry in custom_aovs or []
            if entry.get('kind') == 'lpe' and entry.get('expression', '').strip() and entry['expression'].strip() not in known]


def pass_outputs(custom_aovs, wanted):
    """The scene's outputs with each wanted pass ((what it is called, name, expression)) that it lacks added, and the
    name each pass has in it: an output with the same expression is taken as it is, whatever it is called."""
    entries = [dict(entry) for entry in custom_aovs or []]
    taken = {entry.get('name', '').casefold() for entry in entries}
    names = []
    for words, name, expression in wanted:
        same = next((entry for entry in entries if entry.get('kind') == 'lpe' and entry.get('expression', '').strip() == expression), None)
        if same is not None:
            names.append(same['name'])
            continue
        made, number = name, 1
        while made.casefold() in taken:
            number += 1
            made = '%s_%d' % (name, number)
        taken.add(made.casefold())
        entries.append({'name': made, 'kind': 'lpe', 'expression': expression})
        names.append(made)
    return entries, names


def pass_graph(passes, remainder=True, beauty='beauty'):
    """A graph that puts render passes back together: each pass, [(buffer, what it is called)], through a Grade of its
    own into a Sum, and the Sum to the Composite. With remainder, what the passes leave out of the beauty (the beauty
    less all the passes) is a pass too, so that with every Grade left alone the Composite is the beauty itself."""
    # Laid out in columns: the passes, the remainder worked out beside them, a Grade for each, the Sum, the Composite.
    # The remainder is a row of its own below the passes, its beauty above the Sum of the passes it is taken from.
    nodes, row = {}, 80.0
    grades, adding, out = 720.0, 980.0, 1220.0
    total = {'type': 'sum', 'parameters': {}, 'inputs': {}}
    rows = list(passes) + ([(None, 'Remainder')] if remainder else [])
    for index, (buffer, words) in enumerate(rows):
        y = index * row
        grade = 'grade_%d' % (index + 1)
        if buffer is None:
            # The beauty less the sum of the passes as they were rendered.
            y += row / 2
            nodes['remainder_beauty'] = {'type': 'input', 'parameters': {'buffer': beauty}, 'inputs': {}, 'position': [0.0, y]}
            nodes['remainder_passes'] = {'type': 'sum', 'parameters': {}, 'inputs': {SUM_INPUTS[n]: 'pass_%d' % (n + 1) for n in range(len(passes))},
                                         'position': [0.0, y + row]}
            nodes['remainder_negative'] = {'type': 'math', 'parameters': {'operation': 'multiply', 'value': -1.0},
                                           'inputs': {'image': 'remainder_passes'}, 'position': [240.0, y + row]}
            nodes['remainder'] = {'type': 'sum', 'parameters': {}, 'inputs': {'in1': 'remainder_beauty', 'in2': 'remainder_negative'},
                                  'position': [480.0, y]}
            source = 'remainder'
        else:
            source = 'pass_%d' % (index + 1)
            nodes[source] = {'type': 'input', 'parameters': {'buffer': buffer}, 'inputs': {}, 'position': [0.0, y]}
        nodes[grade] = {'type': 'grade', 'parameters': {}, 'inputs': {'image': source}, 'position': [grades, y]}
        total['inputs'][SUM_INPUTS[index]] = grade
    middle = (len(rows) - 1) * row / 2
    total['position'] = [adding, middle]
    nodes['sum'] = total
    nodes['out'] = {'type': 'output', 'parameters': {}, 'inputs': {'image': 'sum'}, 'position': [out, middle]}
    return validate({'nodes': nodes, 'root': 'out'})


def light_labels(production, entities=()):
    """The light-group labels lights carry in a scene, sorted: Modo's lights and mesh lights (set in the Lighting
    scene controls) and MoonRay's own light items."""
    found = set()
    for settings in ((production or {}).get('lights') or {}).values():
        found.add(str(settings.get('label') or ''))
    for settings in ((production or {}).get('objects') or {}).values():
        if settings.get('mesh_light'):
            found.add(str(settings.get('light_label') or ''))
    for entity in entities or ():
        found.add(str((entity.get('parameters') or {}).get('label') or ''))
    return sorted(label for label in found if label and all(c.isalnum() or c == '_' for c in label) and label[0].isalpha())


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
    if kind in ('alpha', 'depth', 'wireframe', 'sample_count', 'time_per_pixel'):
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


# ---- The compositor program ------------------------------------------------------------------------------------------
# modo_composite (moonlightipr/composite) runs the whole graph in one go, on the graphics card where there is one and on
# the processor otherwise, with the same code for every pixel either way. Its steps follow what the image tool does node
# by node (measured: tools/measure_oiiotool_ops.py); where a runtime has no such program, the image tool does it as
# before. A step the runners give to it is ['@run', program, ...arguments] in place of the image tool's arguments.
PROGRAM = 'modo_composite.exe'
STEP_KINDS = {'copy': 0, 'merge': 2, 'grade': 3, 'levels': 4, 'contrast': 5, 'invert': 6, 'clamp': 7, 'tonemap': 8, 'math': 9,
              'blur_x': 10, 'blur_y': 11, 'sharpen': 12, 'median': 13, 'dilate': 14, 'erode': 15, 'edges': 16, 'grain': 17,
              'vignette': 18, 'flip': 19, 'luma_matte': 20, 'channel': 21, 'constant': 22, 'ramp': 23, 'glow_add': 24, 'bright': 25}


def program(runtime):
    """The compositor program to use with a runtime, or None where there is none: in the MoonLightIPR folder the
    preview uses (the kit's own, a development one named by MOONRAY_MODO_MOONLIGHTIPR, or the runtime's)."""
    import os
    from pathlib import Path
    supplied = os.environ.get('MOONRAY_MODO_MOONLIGHTIPR', '')
    places = [Path(supplied)] if supplied else []
    places += [Path(__file__).resolve().parents[2] / 'runtime' / 'moonlightipr', Path(runtime) / 'moonlightipr']
    for place in places:
        if (place / PROGRAM).is_file() and (place / 'MoonLightIPRComposite.ptx').is_file():
            return place / PROGRAM
    return None


def gaussian_taps(across):
    """A Gaussian blur's weights across one row: as many as across (odd), of a standard deviation a quarter of it,
    sampled at the pixel centres and made to add up to one, as the image tool makes them."""
    import math
    sigma = across / 4.0
    half = across // 2
    weights = [math.exp(-(k * k) / (2.0 * sigma * sigma)) for k in range(-half, half + 1)]
    total = sum(weights)
    return [w / total for w in weights]


def program_jobs(graph, files, kinds, folder, channels, composite):
    """The same picture as jobs(), made by the compositor program: the buffers read as the image tool reads them, the
    graph run by the program, its picture written as an EXR. Returns (steps, the output's file) as jobs() does."""
    from pathlib import Path
    graph = validate(graph)
    folder = Path(folder)
    steps, lines = [], []
    slot_of, count = {}, [0]

    def slot():
        count[0] += 1
        return count[0] - 1

    kernels_weights = []

    def kernel(weights):
        start = sum(len(k) for k in kernels_weights)
        kernels_weights.append(weights)
        return start

    def step(kind, a=-1, b=-1, m=-1, i0=0, i1=0, f=()):
        out = slot()
        values = list(f) + [0.0] * (6 - len(f))
        lines.append('step %d %d %d %d %d %d %d %s' % (STEP_KINDS[kind], a, b, m, out, i0, i1, ' '.join(repr(float(v)) for v in values)))
        return out

    black = [None]

    def none():
        if black[0] is None:
            black[0] = step('constant', f=(0.0, 0.0, 0.0))
        return black[0]

    def blur(source, radius):
        across = max(1, int(round(float(radius) * 4)) | 1)
        start = kernel(gaussian_taps(across))
        return step('blur_y', step('blur_x', source, i0=across, i1=start), i0=across, i1=start)

    # The render's size comes from a buffer: the beauty, or the first there is, read whether or not the graph takes it.
    size_source = files.get('beauty') or next(iter(files.values()))
    loads = []
    for identity in order(graph):
        node = graph['nodes'][identity]
        kind, held = node['type'], node['parameters']
        taken = {key: slot_of[source] for key, source in node['inputs'].items()}
        image = taken.get('image')
        if kind == 'input':
            key = held['buffer']
            if key not in files or kinds.get(key) in UNUSABLE:
                raise ValueError('The render has no %s buffer for the compositor to take' % key)
            target = folder / (identity + '.pfm')
            steps.append((['--no-autopremult', str(files[key]), '--fixnan', 'black'] + ((channels or {}).get(key) or _channels(kinds.get(key, key)))
                          + ['-d', 'float', '-o', str(target)], target))
            slot_of[identity] = slot()
            loads.append('load %d %s' % (slot_of[identity], target))
            continue
        if kind == 'output':
            slot_of[identity] = image if image is not None else none()
            continue
        if kind == 'merge':
            a, b = taken.get('a'), taken.get('b')
            if b is None:
                slot_of[identity] = a if a is not None else none()
                continue
            slot_of[identity] = step('merge', a if a is not None else none(), b, taken.get('mask', -1), i0=MODES.index(held['mode']), f=(float(held['mix']),))
            continue
        if kind == 'sum':
            wired = [taken[key] for key in SUM_INPUTS if key in taken]
            total = wired[0] if wired else none()
            for picture in wired[1:]:
                total = step('merge', total, picture, -1, i0=MODES.index('add'), f=(1.0,))
            slot_of[identity] = total
            continue
        if kind == 'constant':
            slot_of[identity] = step('constant', f=[float(v) for v in held['color']])
            continue
        if kind == 'ramp':
            slot_of[identity] = step('ramp', i0=RAMPS.index(held['direction']), f=[float(v) for v in held['start']] + [float(v) for v in held['end']])
            continue
        if image is None:
            slot_of[identity] = none()
            continue
        out = None
        if kind == 'grade':
            gain = 2.0 ** float(held['exposure'])
            gamma = float(held['gamma']) if abs(float(held['gamma']) - 1.0) > 1e-6 else 1.0
            saturation = float(held['saturation']) if abs(float(held['saturation']) - 1.0) > 1e-6 else 1.0
            out = step('grade', image, f=[gain * float(v) for v in held['tint']] + [gamma, saturation])
        elif kind == 'blur':
            out = image if float(held['radius']) < 0.25 else blur(image, held['radius'])
        elif kind == 'glow':
            bright = step('bright', image, f=(float(held['threshold']),))
            if float(held['radius']) >= 0.25:
                bright = blur(bright, held['radius'])
            out = step('glow_add', image, bright, f=(float(held['strength']),))
        elif kind == 'levels':
            span = float(held['white']) - float(held['black'])
            span = span if abs(span) > 1e-6 else 1e-6
            out = step('levels', image, f=(float(held['black']), 1.0 / span, 1.0 / float(held['gamma']),
                                           float(held['out_white']) - float(held['out_black']), float(held['out_black'])))
        elif kind == 'contrast':
            out = step('contrast', image, f=(float(held['contrast']), float(held['pivot'])))
        elif kind == 'invert':
            out = step('invert', image)
        elif kind == 'clamp':
            out = step('clamp', image, f=(float(held['least']), float(held['most'])))
        elif kind == 'tonemap':
            out = step('tonemap', image, f=(2.0 ** float(held['exposure']),))
        elif kind == 'math':
            value = float(held['value'])
            if held['operation'] == 'divide':
                value = 1.0 / value if abs(value) > 1e-9 else 0.0
            out = step('math', image, i0=MATH.index(held['operation']), f=(value,))
        elif kind == 'sharpen':
            if float(held['amount']) < 1e-4:
                out = image
            else:
                # The image tool's unsharp mask: its kernel as many pixels across as the width rounded up, one fewer if
                # that is even; a Gaussian of a quarter of the width.
                import math
                width = 2 * float(held['radius']) + 1
                across = int(math.ceil(width))
                across -= 0 if across % 2 else 1
                sigma = width / 4.0
                half = across // 2
                weights = [math.exp(-(k * k) / (2.0 * sigma * sigma)) for k in range(-half, half + 1)]
                total = sum(weights)
                start = kernel([w / total for w in weights])
                blurred = step('blur_y', step('blur_x', image, i0=across, i1=start), i0=across, i1=start)
                out = step('sharpen', image, blurred, f=(float(held['amount']),))
        elif kind == 'median':
            out = step('median', image, i0=2 * int(round(float(held['radius']))) + 1)
        elif kind == 'grow':
            pixels = int(round(float(held['pixels'])))
            out = image if not pixels else step('dilate' if pixels > 0 else 'erode', image, i0=2 * abs(pixels) + 1)
        elif kind == 'edges':
            out = step('edges', image, f=(float(held['strength']),))
        elif kind == 'grain':
            out = image if float(held['amount']) < 1e-6 else step('grain', image, i0=int(float(held['seed'])), f=(float(held['amount']),))
        elif kind == 'vignette':
            out = step('vignette', image, f=(float(held['amount']), float(held['falloff'])))
        elif kind == 'flip':
            out = step('flip', image, i0={'left to right': 1, 'top to bottom': 2, 'both': 3}[held['direction']])
        elif kind == 'luma_matte':
            span = float(held['high']) - float(held['low'])
            span = span if abs(span) > 1e-6 else 1e-6
            out = step('luma_matte', image, i0=1 if held['take'] == 'the dark' else 0, f=(float(held['low']), 1.0 / span))
        elif kind == 'channel':
            out = step('channel', image, i0=CHANNELS.index(held['channel']))
        else:
            raise ValueError('The compositor program has no %s node' % kind)
        slot_of[identity] = out
    result = slot_of[graph['root']]
    if not loads:
        # A graph of made pictures only: a buffer is read all the same, for the render's size.
        steps.append((['--no-autopremult', str(size_source), '--ch', '0,1,2', '-d', 'float', '-o', str(folder / 'size.pfm')], folder / 'size.pfm'))
        loads.append('load %d %s' % (slot(), folder / 'size.pfm'))
    plan = folder / 'composite.txt'
    picture, final = folder / 'composite.pfm', folder / 'composite.exr'
    text = ['size 0 0'] + ['kernel %d %s' % (len(w), ' '.join(repr(float(v)) for v in w)) for w in kernels_weights] + loads + lines + ['save %d %s' % (result, picture)]
    plan.write_text('\n'.join(text) + '\n', encoding='utf-8')
    steps.append((['@run', str(composite), str(plan)], picture))
    steps.append(([str(picture), '-d', 'float', '-o', str(final)], final))
    return steps, final


def jobs(graph, files, kinds, folder, channels=None, composite=None):
    """What the image tool is to be run with, node after node: [(arguments, the file that run makes)], and the file
    that is the output's picture. files has each buffer's file and kinds what kind of buffer each is. A wired input
    that is left out of a node is black; a node with nothing to work on is black too. channels, where given, says
    for a buffer what picks it out of its file, in place of what its kind would: for buffers that are channels of
    one EXR."""
    from pathlib import Path
    if composite is not None:
        # The compositor program, given: the whole graph in one go, on the graphics card or the processor.
        return program_jobs(graph, files, kinds, folder, channels, composite)
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
            # Named R, G and B whatever the buffer's channels were called (an EXR's pass_x.R and so on): the image tool
            # keeps the first picture's names through every step, and the Composite is read by them.
            args = ['--no-autopremult', str(files[key]), '--fixnan', 'black'] + ((channels or {}).get(key) or _channels(kinds.get(key, key))) + ['--chnames', 'R,G,B']
        elif kind == 'output':
            made[identity] = taken.get('image') or none()
            continue
        elif kind == 'sum':
            wired = [taken[key] for key in SUM_INPUTS if key in taken]
            if len(wired) < 2:
                made[identity] = wired[0] if wired else none()
                continue
            args = [str(wired[0])]
            for picture in wired[1:]:
                args += [str(picture), '--add']
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
