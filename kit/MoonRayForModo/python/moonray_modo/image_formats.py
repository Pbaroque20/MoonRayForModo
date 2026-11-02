"""The picture file types the plugin saves: the render's own OpenEXR, and the standard types a picture is passed on in.

MoonRay always writes OpenEXR. A render or an output saved in another type is converted from it by the image tool:
the types that hold a picture to look at (8 and 16 bits a channel) take it as the preview shows it, through the view
transform; those that hold numbers (OpenEXR, 32-bit TIFF) keep the render's own linear values."""
from pathlib import Path

# (what it is called in a file's name, what it is called, its extension, its numbers, whether it holds the picture as
# shown rather than the render's linear values)
FORMATS = (
    ('exr32', 'OpenEXR, 32-bit float (linear)', 'exr', 'float', False),
    ('exr16', 'OpenEXR, 16-bit half (linear)', 'exr', 'half', False),
    ('png8', 'PNG, 8-bit', 'png', 'uint8', True),
    ('png16', 'PNG, 16-bit', 'png', 'uint16', True),
    ('jpg', 'JPEG, 8-bit', 'jpg', 'uint8', True),
    ('tif8', 'TIFF, 8-bit', 'tif', 'uint8', True),
    ('tif16', 'TIFF, 16-bit', 'tif', 'uint16', True),
    ('tif32', 'TIFF, 32-bit float (linear)', 'tif', 'float', False),
    ('tga', 'Targa, 8-bit', 'tga', 'uint8', True),
)
# The extensions each type is known by in a file's name, for the one a file dialog was given.
EXTENSIONS = {'exr': 'exr32', 'png': 'png8', 'jpg': 'jpg', 'jpeg': 'jpg', 'tif': 'tif8', 'tiff': 'tif8', 'tga': 'tga'}


def find(key):
    """A type by its key: (key, label, extension, numbers, shown). Unknown keys are refused."""
    for held in FORMATS:
        if held[0] == key:
            return held
    raise ValueError('Unknown picture type: %s' % key)


def from_path(path, fallback='exr32'):
    """The type a file's name asks for by its extension."""
    return EXTENSIONS.get(Path(path).suffix.lower().lstrip('.'), fallback)


def name_filter():
    """The file dialog's list of types, OpenEXR first."""
    seen, filters = set(), []
    for key, label, extension, numbers, shown in FORMATS:
        if extension in seen:
            continue
        seen.add(extension)
        patterns = ' '.join('*.' + e for e, k in EXTENSIONS.items() if find(k)[2] == extension)
        filters.append('%s (%s)' % (label.split(',')[0], patterns))
    return ';;'.join(filters)


def picture_filters():
    """The file dialog's list for a render's picture: OpenEXR, and each other type by its own name, so that the one
    picked says how many bits as well. Returns (the filter, {its entries: the type each is})."""
    entries = {'OpenEXR (*.exr)': 'exr32'}
    for key, label, extension, numbers, shown in FORMATS:
        if extension != 'exr':
            entries['%s (*.%s)' % (label, extension)] = key
    return ';;'.join(entries), entries


def holds_alpha(key):
    """Whether a type keeps a picture's alpha beside its colour: all but JPEG, and OpenEXR is copied whole."""
    return find(key)[2] in ('png', 'tif', 'tga')


def convert(runtime, key, source, target, display=None, quality=92, alpha=False, background=None):
    """Write the picture of a render saved at source as target, in a type, from its beauty, with its alpha where alpha is
    asked for and the type holds it. background: the render's own file, whose Environment background is taken out where
    it has one (a denoised source has its beauty and alpha alone). Raises RuntimeError where the image tool could not."""
    import subprocess
    from . import native
    runtime = Path(runtime)
    if background and alpha and holds_alpha(key):
        from .composite_output import channel_names
        if BACKGROUND[0] not in channel_names(runtime, background):
            background = None
    done = subprocess.run([str(runtime / 'oiiotool.exe')] + (with_alpha(key, source, target, display, background) if alpha and holds_alpha(key) else arguments(key, 'beauty', source, target, display, quality)),
                          env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if done.returncode or not Path(target).is_file():
        raise RuntimeError(done.stdout.decode('utf-8', errors='replace')[-300:])
    return Path(target)


BACKGROUND = ('environment_background.R', 'environment_background.G', 'environment_background.B')


def with_alpha(key, source, target, display=None, background=None, alpha=None):
    """The image tool's arguments that write a beauty with its alpha. These types keep colour apart from alpha: the
    render's is divided by it first, in linear, and the view transform then applies to the colour alone. Where the
    alpha is 0 the colour stays as it is. background: a file holding the Environment background, which is taken out
    first: a soft edge is part surface, part visible environment, and alpha counts the surface alone, so that dividing
    the two made the edge flare; or (file, its three channels). Colour where the alpha is 0 is then black.

    alpha: (file, channel) where the alpha is a file of its own, as a preview's outputs are, and the colour is then the
    first three channels of source; otherwise source's R, G, B and A, as the render's own file has them."""
    key, label, extension, numbers, shown = find(key)
    colour = 'R,G,B' if alpha is None else '0,1,2'
    taken = [str(source), '--ch', 'A'] if alpha is None else [str(alpha[0]), '--ch', str(alpha[1]), '--chnames', 'A']
    if background:
        held, channels = (background, ','.join(BACKGROUND)) if isinstance(background, (str, Path)) else background
        args = ['--no-autopremult', str(source), '--fixnan', 'black', '--ch', colour, '--chnames', 'R,G,B', str(held), '--fixnan', 'black',
                '--ch', channels, '--chnames', 'R,G,B', '--sub', '--clamp:min=0'] + taken + ['--chappend', '--unpremult', '--ch', '0,1,2']
    elif alpha is None:
        args = ['--no-autopremult', str(source), '--fixnan', 'black', '--ch', 'R,G,B,A', '--unpremult', '--ch', '0,1,2']
    else:
        args = ['--no-autopremult', str(source), '--fixnan', 'black', '--ch', colour, '--chnames', 'R,G,B'] + taken + ['--chappend', '--unpremult', '--ch', '0,1,2']
    if shown:
        from .display import arguments as view
        args += view(display or {})
    return args + taken + ['--chappend', '-d', numbers, '--attrib:type=int', 'oiio:UnassociatedAlpha', '1', '-o', str(target)]


def exr_with_alpha(key, source, alpha, target):
    """The image tool's arguments that write a beauty and its alpha (file, channel) as one OpenEXR: R, G, B and A, the
    colour premultiplied as the render made it."""
    numbers = find(key)[3]
    return [str(source), '--ch', '0,1,2', '--chnames', 'R,G,B', str(alpha[0]), '--ch', str(alpha[1]), '--chnames', 'A', '--chappend',
            '-d', numbers, '-o', str(target)]


def layer_names(key, names, beauty=False):
    """A buffer's channels as a layer of a multilayer OpenEXR: the beauty as R, G, B (and A), the rest under their own
    name, render_albedo's R as albedo.R. A Cryptomatte keeps the names its readers look for."""
    if beauty:
        return ['RGBA'[i] if i < 4 else '%s.%s' % (key, name) for i, name in enumerate(names)]
    return ['%s.%s' % (key, name.rsplit('.', 1)[-1]) for name in names]


def multilayer(key, layers, target):
    """The image tool's arguments that write several buffers into one OpenEXR, each a layer: layers are (file, the
    channels taken from it, their names in the file written, whether they must stay 32-bit float). The beauty's alpha
    is a layer of its own channel, A, after the beauty."""
    numbers = find(key)[3]
    args, kept, written = [], [], set()
    for index, (source, channels, names, exact) in enumerate(layers):
        # A name already written gets the buffer's file name in front, so that no layer hides another.
        names = [name if name not in written else '%s.%s' % (Path(source).stem, name) for name in names]
        written.update(names)
        args += [str(source), '--ch', ','.join(channels), '--chnames', ','.join(names)] + (['--chappend'] if index else [])
        if exact:
            kept += names
    return args + ['-d', numbers] + [item for name in kept for item in ('-d', '%s=float' % name)] + ['-o', str(target)]


def linear(key):
    return not find(key)[4]


def arguments(key, kind, source, target, display=None, quality=95):
    """The image tool's arguments that write a buffer of a kind (outputs.display_kind) in a type: as shown, for the types
    of a picture to look at, or its own values, for the linear ones. A Cryptomatte keeps every channel at full
    precision, which only OpenEXR can hold."""
    key, label, extension, numbers, shown = find(key)
    if kind == 'cryptomatte':
        if extension != 'exr':
            raise ValueError('a Cryptomatte is saved as OpenEXR only: its IDs are numbers the other types cannot hold')
        return [str(source), '-d', 'float', '-o', str(target)]
    if not shown:
        if extension == 'exr':
            return [str(source), '-d', numbers, '-o', str(target)]
        return ['--no-autopremult', str(source), '--fixnan', 'black', '--ch', '0,1,2', '-d', numbers, '-o', str(target)]
    from .buffers import conversion
    args = conversion(kind, source, target, display)
    # The display conversion writes 8 bits; the type says how many, and a JPEG how finely.
    at = args.index('-d')
    args[at + 1] = numbers
    if extension == 'jpg':
        args[at:at] = ['--compression', 'jpeg:%d' % max(1, min(100, int(quality)))]
    return args
