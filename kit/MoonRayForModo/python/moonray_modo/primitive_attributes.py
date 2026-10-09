"""Values an item carries for its materials to read: MoonRay's primitive attributes.

A material's AttributeMap reads a named value from the shape it is on: a colour, a number, a direction. Here each
Modo item holds such values of its own, one of each name, in a tag beside the plugin's other settings; an instance
holds its own, so that every instance of a mesh can have, say, its own colour. They are written into the scene as
MoonRay UserData: on a shape, one value for all of it; on an instancer, one for each instance.

An attribute is {'name': 'Cd', 'type': 'color', 'value': [1, 0, 0]}."""
import json

TAG = 'MRPA'
# type: (UserData's word for it, how many numbers, how a value is written)
KINDS = {'color': ('color', 3, 'Rgb'), 'float': ('float', 1, None), 'vec2': ('vec2f', 2, 'Vec2'), 'vec3': ('vec3f', 3, 'Vec3'),
         'int': ('int', 1, None), 'string': ('string', 0, None), 'bool': ('bool', 0, None)}
# UserData's own names, for reading a MoonRay scene.
READ = {'color': 'color', 'float': 'float', 'vec2f': 'vec2', 'vec3f': 'vec3', 'int': 'int', 'string': 'string', 'bool': 'bool'}


def checked(attributes):
    """The attributes as they must be to be written out; raises ValueError for what cannot be."""
    result, names = [], set()
    for entry in attributes or []:
        name, kind, value = entry.get('name'), entry.get('type'), entry.get('value')
        if not isinstance(name, str) or not name or len(name) > 128 or name in names:
            raise ValueError('Attribute names must be given and differ: ' + str(name))
        if kind not in KINDS:
            raise ValueError('Unknown attribute type for ' + name)
        size = KINDS[kind][1]
        if kind == 'string':
            value = str(value)
        elif kind == 'bool':
            value = bool(value)
        elif kind == 'int':
            value = int(value)
        elif size == 1:
            value = float(value)
        else:
            value = [float(v) for v in value]
            if len(value) != size:
                raise ValueError('%s needs %d numbers' % (name, size))
        names.add(name)
        result.append({'name': name, 'type': kind, 'value': value})
    return result


def read(item):
    """An item's attributes; none if it has none or they cannot be followed."""
    try:
        return checked(json.loads(item.readTag(TAG)))
    except (LookupError, RuntimeError, ValueError, TypeError, AttributeError):
        return []


def write(item, attributes):
    item.setTag(TAG, json.dumps(checked(attributes), sort_keys=True, separators=(',', ':')))


def _literal(kind, value):
    from .rdla import number, string, vector
    constructor = KINDS[kind][2]
    if constructor:
        return vector(value, constructor)
    if kind == 'string':
        return string(value)
    if kind == 'bool':
        return 'true' if value else 'false'
    return str(int(value)) if kind == 'int' else number(value)


def _zero(kind):
    return '' if kind == 'string' else False if kind == 'bool' else 0 if KINDS[kind][1] == 1 else [0.0] * KINDS[kind][1]


def emit(path, rows, lines):
    """Write UserData for the attributes of one shape (rows is a single list of attributes) or of the instances of an
    instancer (one list for each instance, in order). Returns what to put in primitive_attributes.

    Instances need not all hold the same names: one without a name is given nothing of it (zero, empty, off)."""
    from .rdla import string
    kinds = {}
    for row in rows:
        for entry in row:
            kinds.setdefault(entry['name'], entry['type'])
    made = []
    for index, (name, kind) in enumerate(sorted(kinds.items())):
        values = []
        for row in rows:
            held = next((entry['value'] for entry in row if entry['name'] == name and entry['type'] == kind), None)
            values.append(_literal(kind, _zero(kind) if held is None else held))
        word = KINDS[kind][0]
        store = word + ('_values' if kind in ('string', 'bool') else '_values_0')
        reference = 'UserData(%s)' % string('%s/%d' % (path, index))
        lines += [reference + ' {', '  ["%s_key"] = %s,' % (word, string(name)), '  ["%s"] = {%s},' % (store, ', '.join(values)), '}']
        made.append(reference)
    return made


def from_userdata(record):
    """What one UserData of a MoonRay scene holds: [(name, type, list of values)]. Kinds the plugin does not hold are left out."""
    a, found = record.get('attributes', {}), []
    for word, kind in READ.items():
        name = a.get(word + '_key')
        values = a.get(word + '_values_0') or a.get(word + '_values') or []
        if name and values:
            found.append((name, kind, values))
    return found
