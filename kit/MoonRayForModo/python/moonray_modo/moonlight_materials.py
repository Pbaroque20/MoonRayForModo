"""Reduce translated materials to the MoonLightIPR uber-shader and its layer stacks.

A material becomes starting values for each channel plus an ordered list of layers, each a
constant, an image, a gradient or a pattern blended over the rows below it, as graph.py builds
for MoonRay. What has no counterpart is collected by name so the caller can report it.
"""
import hashlib
import math
import os
import re
import struct
import subprocess
import tempfile
import uuid
from pathlib import Path

# Channel, flag and wrap numbers; keep in step with moonlight/src/device/shared.h.
CHANNELS = {'diffCol': 0, 'diffAmt': 1, 'rough': 2, 'metallic': 3, 'lumiCol': 4, 'lumiAmt': 5, 'normal': 6,
            'tranAmt': 7, 'tranCol': 8, 'tranRough': 9, 'coatAmt': 10, 'coatRough': 11, 'dissolve': 12, 'bump': 13,
            'groupMask': 14, 'aniso': 15, 'subsAmt': 16, 'subsCol': 17,
            'driverA': 18, 'driverB': 19, 'driverC': 20, 'driverD': 21}
# Channels a material row does not set: the maps, the mask, and values only gradients read.
UNSET_BY_ROWS = ('normal', 'bump', 'groupMask', 'driverA', 'driverB', 'driverC', 'driverD')
# Channels whose constant rows can be worked out here instead of on the GPU, with the range the
# material record keeps a single number in (None for colours, which it keeps whole).
FOLDED = {'diffCol': None, 'diffAmt': (-math.inf, math.inf), 'rough': (0, 1), 'metallic': (0, 1), 'lumiCol': None,
          'lumiAmt': (-math.inf, math.inf), 'tranAmt': (0, 1), 'tranCol': None, 'tranRough': (0, 1), 'coatAmt': (0, 1),
          'coatRough': (0, 1), 'dissolve': (0, 1), 'aniso': (-1, 1), 'subsAmt': (0, 1), 'subsCol': None}
LAYER_GROUP_BEGIN, LAYER_GROUP_END, LAYER_MASK_BASE, MASK_REGISTERS, GROUP_DEPTH = 32, 33, 40, 4, 4
LAYER_MASKED, LAYER_MASK_SHIFT = 1 << 11, 12
MATERIAL_THIN, MATERIAL_COAT_DIMS, MATERIAL_BECKMANN = 1, 2, 16
LAYER_INVERT, LAYER_FLIP_RED, LAYER_FLIP_GREEN, LAYER_FLIP_BLUE = 2, 4, 8, 16
LAYER_ALPHA_MASK, LAYER_ALPHA_ONLY, LAYER_COVERAGE_U, LAYER_COVERAGE_V, LAYER_PICK_SHIFT = 32, 64, 128, 256, 9
LAYER_RAMP, LAYER_CHECKER, LAYER_NOISE, LAYER_UDIM = 1 << 16, 1 << 17, 1 << 18, 1 << 19
BLEND_REORIENTED_NORMAL = 15
WRAP = {'repeat': 0, 'edge': 1, 'mirror': 2, 'reset': 3}
TEXTURE_FLOAT, TEXTURE_SRGB, TEXTURE_WRAP_U_SHIFT, TEXTURE_WRAP_V_SHIFT = 1, 2, 2, 4
UV_SLOTS = 8
MAX_TEXTURE_SIDE = 4096
RAMP_STEPS = 257
HDR_SUFFIXES = ('.exr', '.hdr', '.tx')
SPACE_ALIASES = {'(default)': '', '(none)': 'raw', 'Linear': 'linear', 'lin_rec709': 'linear', 'srgb_texture': 'sRGB'}


def triple(value):
    values = [float(v) for v in (value if isinstance(value, (list, tuple)) else [value] * 3)]
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError('Material contains an invalid value')
    return values


def cache_folder():
    return Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo/MoonLight'


def color_space(source, authored, srgb):
    """The space an image is read in, as textures.prepare decides it: (name, OCIO config or None)."""
    from . import textures
    policy = textures._policy.get()
    space = textures.color_rule(source) or authored or ''
    space = SPACE_ALIASES.get(space, space)
    if not space:
        space = 'sRGB' if srgb else 'raw'
    if space in ('sRGB', 'linear', 'raw'):
        return space, None
    config = policy.get('config', '')
    if not config or not Path(config).is_file():
        raise ValueError('an input OCIO config is required for color space ' + space)
    return space, (str(Path(config).resolve()), Path(config).stat().st_mtime_ns, policy.get('linear_space', 'Linear Rec.709 (sRGB)'))


# What each native shader's switched-on extras are called, for the lobes the uber-shader lacks.
NATIVE_EXTRAS = (('show_fuzz', 'fuzz'), ('show_glitter', 'glitter'))


def native_surface(shader, parameters, note):
    """A native MoonRay material as the values the uber-shader starts from, or None for a shader
    it has no reading of.

    The Dwa surface shaders share one set of attribute names; each is read with MoonRay's own
    default where the user has not set it. note(what) records a lobe that is left out.
    """
    from . import node_defaults, shader_library
    if shader not in ('DwaBaseMaterial', 'DwaMetalMaterial', 'DwaSolidDielectricMaterial', 'DwaRefractiveMaterial', 'DwaEmissiveMaterial'):
        return None
    attributes = shader_library.catalog()[shader]['attributes']
    def get(key, missing):
        if key in parameters:
            return parameters[key]
        if key in attributes:
            try:
                return node_defaults.value(attributes[key])
            except ValueError:
                pass
        return missing
    black, white = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    if shader == 'DwaEmissiveMaterial':
        emission = get('emission', white) if get('show_emission', True) else black
        return {'shader': 'DwaBaseMaterial', 'standard_material': False, 'color': black, 'raw_color': black, 'diffuse_amount': 1.0,
                'roughness': 1.0, 'metallic': 0.0, 'specular_amount': 0.0, 'emission': emission, 'raw_emission': emission,
                'emission_amount': 1.0, 'presence': float(get('presence', 1.0)), 'ior': 1.5}
    metal = shader == 'DwaMetalMaterial'
    glass = shader == 'DwaRefractiveMaterial'
    metallic = 1.0 if metal else 0.0 if glass or shader == 'DwaSolidDielectricMaterial' else min(1.0, max(0.0, float(get('metallic', 0.0))))
    albedo = get('albedo', white) if get('show_diffuse', True) and not glass else black
    # The uber-shader has one colour for the diffuse lobe and the metal's reflection.
    color = [a + (m - a) * metallic for a, m in zip(albedo, get('metallic_color', white))]
    roughness = float(get('roughness', .5))
    transmission = (1.0 if glass else float(get('transmission', 0.0))) if get('show_transmission', True) and shader in (
        'DwaBaseMaterial', 'DwaRefractiveMaterial') else 0.0
    ior = float(get('refractive_index', 1.5))
    emission = get('emission', white) if get('show_emission', False) else black
    radius = float(get('scattering_radius', 0.0))
    for switch, label in NATIVE_EXTRAS:
        if get(switch, False):
            note(label)
    if float(get('iridescence', 0.0)) > 0:
        note('iridescence')
    if 0 < float(get('specular', 1.0)) < 1:
        note('a specular weight between 0 and 1, shown at full strength')
    return {
        'shader': 'DwaBaseMaterial', 'standard_material': False, 'color': color, 'raw_color': color, 'diffuse_amount': 1.0,
        'roughness': roughness, 'metallic': metallic, 'ior': ior,
        'specular_amount': float(get('specular', 1.0)) if get('show_specular', True) else 0.0,
        'transmission': transmission, 'transmission_color': get('transmission_color', white),
        'refraction_roughness': float(get('independent_transmission_roughness', .5)) if get('use_independent_transmission_roughness', False) else roughness,
        'transmission_ior': float(get('independent_transmission_refractive_index', 1.5)) if get('use_independent_transmission_refractive_index', False) else ior,
        'clearcoat': float(get('clearcoat', 1.0)) if get('show_clearcoat', False) else 0.0, 'clearcoat_roughness': float(get('clearcoat_roughness', .1)),
        'emission': emission, 'raw_emission': emission, 'emission_amount': 1.0, 'presence': float(get('presence', 1.0)),
        'anisotropy': float(get('anisotropy', 0.0)), 'thin_geometry': bool(get('thin_geometry', False)),
        'subsurface_amount': 1.0 if radius > 0 else 0.0, 'subsurface_distance': radius, 'subsurface_color': get('scattering_color', white),
        'diffuse_roughness': float(get('diffuse_roughness', 0.0)),
        'dispersion_abbe': float(get('dispersion_abbe_number', 34.0)) if get('use_dispersion', False) else 0.0,
        # 0 is Beckmann, 1 GGX; only DwaBaseMaterial offers the choice.
        '_beckmann': get('specular_model', 1) == 0}


class Compiler:
    """Collects the materials of one scene; textures and coordinate slots are shared between them."""

    def __init__(self, runtime=None):
        self.runtime = runtime
        self.textures = {}      # record -> index, in first-use order
        self.slots = {}         # coordinate key -> scene-wide slot
        self.layers = []
        self.tiles = []         # runs of a count and that many texture indices, one per UDIM tile
        self.tile_runs = {}     # what a run was made from -> where it starts
        self.missing = {}       # what was left out -> the materials it was left out of

    def note(self, what, name):
        self.missing.setdefault(what, [])
        if name not in self.missing[what]:
            self.missing[what].append(name)

    def warnings(self):
        return ['MoonLightIPR leaves out %s (%s).' % (what, ', '.join(names[:6]) + (' ...' if len(names) > 6 else ''))
                for what, names in sorted(self.missing.items())]

    def slot(self, key):
        if key not in self.slots:
            if len(self.slots) >= UV_SLOTS:
                return None
            self.slots[key] = len(self.slots)
        return self.slots[key]

    def record(self, target, flags):
        path = str(target).encode('utf-8')
        record = hashlib.blake2b(path + struct.pack('<I', flags), digest_size=8).digest() + struct.pack('<2I', flags, len(path)) + path
        return self.textures.setdefault(record, len(self.textures))

    def texture(self, layer, source=None, wrap=None):
        """Convert an image once to a file the session reads directly; return its index."""
        source = Path(source or layer['path'])
        stat = source.stat()
        hdr = source.suffix.lower() in HDR_SUFFIXES
        space, ocio = color_space(source, layer.get('color_space', ''), layer.get('srgb'))
        digest = hashlib.sha256(repr((str(source.resolve()), stat.st_size, stat.st_mtime_ns, MAX_TEXTURE_SIDE, 'moonlight-v2', ocio and (space, ocio))).encode()).hexdigest()
        target = cache_folder() / (digest + ('.pfm' if hdr else '.tga'))
        if not target.is_file() or not target.stat().st_size:
            if ocio:
                self.convert_space(source, target, hdr, space, ocio)
            else:
                self.convert(source, target, hdr)
        tile_u = layer.get('tile_u', 'repeat' if layer.get('repeat', True) else 'edge')
        tile_v = layer.get('tile_v', tile_u)
        if wrap:
            tile_u = tile_v = wrap
        if tile_u not in WRAP or tile_v not in WRAP:
            raise ValueError('Unsupported texture repeat mode')
        # An OCIO conversion leaves ordinary images sRGB encoded, so eight bits hold them well.
        decoded = (space == 'sRGB' or ocio) and not hdr
        return self.record(target, (TEXTURE_FLOAT if hdr else 0) | (TEXTURE_SRGB if decoded else 0)
                           | WRAP[tile_u] << TEXTURE_WRAP_U_SHIFT | WRAP[tile_v] << TEXTURE_WRAP_V_SHIFT)

    def run(self, args, name):
        from . import native
        runtime = Path(self.runtime or native.default_runtime())
        tool = runtime / 'oiiotool.exe'
        if not tool.is_file():
            raise ValueError('Texture conversion needs oiiotool.exe in the MoonRay runtime')
        result = subprocess.run([str(tool)] + args, env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('Texture conversion failed for %s: %s' % (name, result.stdout[-600:]))
        return result.stdout

    def convert(self, source, target, hdr, resample=None, encode=False):
        """Write source as a Targa, or a PFM when hdr; resample replaces the default size limit.

        encode stores linear pixels sRGB encoded.
        """
        found = re.search(r'(\d+)\s*x\s*(\d+),\s*(\d+)\s+channel', self.run(['--info', str(source)], source.name))
        if not found:
            raise ValueError('Cannot read texture ' + source.name)
        width, height, channels = (int(v) for v in found.groups())
        # Grey and grey-alpha images spread to RGB; a missing alpha is opaque.
        order = {1: '0,0,0,=1.0', 2: '0,0,0,1', 3: '0,1,2,=1.0'}.get(channels, '0,1,2,3')
        args = [str(source), '--ch', order.rsplit(',', 1)[0] if hdr else order]
        if not hdr and channels in (2, 4):
            # The session blends with alpha itself, so colours must not arrive already multiplied by it.
            args += ['--unpremult', '--attrib', 'oiio:UnassociatedAlpha', '1']
        if encode:
            args += ['--colorconvert', 'linear', 'sRGB']
        if resample is not None:
            args += list(resample)
        elif max(width, height) > MAX_TEXTURE_SIDE:
            args += ['--fit', '%dx%d' % (MAX_TEXTURE_SIDE, MAX_TEXTURE_SIDE)]
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.stem + '-' + uuid.uuid4().hex + target.suffix)
        try:
            self.run(args + (['-d', 'float'] if hdr else ['-d', 'uint8', '--compression', 'none']) + ['-o', str(staged)], source.name)
            staged.replace(target)
        finally:
            if staged.exists():
                staged.unlink()

    def convert_space(self, source, target, hdr, space, ocio):
        """Take an image from an OCIO colour space to linear first, as the plugin's maketx step does."""
        config, _, linear = ocio
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.stem + '-' + uuid.uuid4().hex + '.exr')
        try:
            self.run(['--colorconfig', config, str(source), '--colorconvert', space, linear, '-d', 'float', '-o', str(staged)], source.name)
            self.convert(staged, target, hdr, encode=not hdr)
        finally:
            if staged.exists():
                staged.unlink()

    def ramp(self, data, exact=False):
        """Write a gradient as a small float image the session reads as is; return its index.

        exact keeps every point given, for ramps that do not go through MoonRay's RampMap.
        """
        from .gradients import reduced, sample
        # MoonRay's RampMap holds 20 points, so that is the gradient the final render shows.
        data = data if exact else reduced(data)
        steps = [i / (RAMP_STEPS - 1) for i in range(RAMP_STEPS)]
        colors = data['colors'] if list(data['positions']) == steps else [sample(data, x) for x in steps]
        alpha = data.get('alpha')
        if alpha is not None and (len(alpha) != RAMP_STEPS or colors is not data['colors']):
            alpha = [sample(dict(data, colors=[[a] * 3 for a in alpha]), x)[0] for x in steps]
        pixels = struct.pack('<%df' % (RAMP_STEPS * 4), *(v for i, color in enumerate(colors)
                                                         for v in triple(color) + [1.0 if alpha is None else float(alpha[i])]))
        target = cache_folder() / (hashlib.sha256(pixels).hexdigest() + '.mlf')
        if not target.is_file() or target.stat().st_size != len(pixels) + 12:
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(target.stem + '-' + uuid.uuid4().hex + target.suffix)
            try:
                staged.write_bytes(b'MLF1' + struct.pack('<2I', RAMP_STEPS, 1) + pixels)
                staged.replace(target)
            finally:
                if staged.exists():
                    staged.unlink()
        return self.record(target, TEXTURE_FLOAT | WRAP['edge'] << TEXTURE_WRAP_U_SHIFT | WRAP['edge'] << TEXTURE_WRAP_V_SHIFT)

    def udim(self, layer):
        """One texture per tile; return where the run starts in the tile list."""
        from . import textures
        tiles = textures.source_tiles(layer['path'])
        if not tiles:
            raise ValueError('no UDIM tiles found for ' + Path(layer['path']).name)
        # Tile 1001 is the unit square at the origin; each tile is looked up within itself.
        indices = {number - 1001: self.texture(layer, path, wrap='edge') for number, path in tiles.items() if number >= 1001}
        key = tuple(sorted(indices.items()))
        if key not in self.tile_runs:
            self.tile_runs[key] = len(self.tiles)
            count = max(indices) + 1
            self.tiles += [count] + [indices.get(i, -1) for i in range(count)]
        return self.tile_runs[key]

    def layer(self, channel, blend=0, flags=0, texture=-1, slot=0, value=(0, 0, 0), opacity=1.0, gain=1.0, offset=0.0,
              scale=(1, 1), gamma=1.0, bias=.5, gain_curve=.5, color2=(1, 1, 1), alpha1=1.0, alpha2=1.0,
              octaves=4, lacunarity=2.0, persistence=.5):
        opacity = float(opacity)
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError('Layer opacity must be between zero and one')
        numbers = triple(value) + [opacity, gain, offset, float(scale[0]), float(scale[1]), gamma, bias, gain_curve] + triple(color2) + [
            alpha1, alpha2, octaves, lacunarity, persistence]
        if not all(math.isfinite(float(v)) for v in numbers):
            raise ValueError('Layer contains a non-finite number')
        self.layers.append(struct.pack('<3Ii1I19f', channel, blend, flags, texture, slot, *numbers))

    def material(self, material, name):
        """Append the material's layers; return its packed record."""
        from . import absorption, graph, textures
        from .layers import BLENDS
        from .material_groups import merged, supported
        from .material_settings import values as shader_controls
        stack = material.get('material_stack')
        if stack and supported(stack):
            source = merged(stack)
        else:
            # A native shader or node graph has no channel stack to translate.
            source = stack[-1] if stack else material
        native, surface = source.get('native_shader'), None
        if native:
            # A native MoonRay material: its own attributes say what it looks like, not the Modo
            # material it rides on.
            surface = native_surface(native, source.get('native_parameters') or {}, lambda what: self.note(what, name))
            graph_root = None
            if source.get('node_graph'):
                nodes = source['node_graph'].get('nodes', {})
                graph_root = nodes.get(source['node_graph'].get('root'))
            if surface is None:
                self.note('%s, shown with the values of the Modo material' % native, name)
            else:
                if graph_root and graph_root.get('inputs'):
                    self.note('the maps wired into a material graph, shown with the values beneath them', name)
                source = dict(source, **surface)
        defaults = graph.defaults_for(source)
        layers = source.get('layers')
        if layers is None:
            layers = [dict(value, effect=key, kind=value.get('kind', 'imageMap')) for key, value in source.get('textures', {}).items()]
        if native and surface is None:
            layers = []
        elif source.get('node_graph') and not native:
            self.note('node graphs, shown with their base values', name)
            layers = []
        if source.get('diffuse_roughness', 0):
            self.note('diffuse roughness', name)
        if source.get('opacity', 1) < 1:
            self.note('opacity', name)
        effects = {textures.EFFECT_ALIASES.get(layer['effect'], layer['effect']) for layer in layers}

        start = len(self.layers)
        # A constant row blended over a constant is still a constant. Until a channel gets a row
        # that varies across the surface, its rows are folded into the value it starts from, which
        # leaves most materials with no layers for the GPU to run at each hit. Gradients read
        # other channels as they stand part way up the stack, so with one present nothing is folded.
        folded = {effect: triple(defaults[effect]) for effect in FOLDED}
        foldable = set() if any(layer.get('kind') == 'gradient' for layer in layers) else set(FOLDED)

        def put(effect, channel, blend_name, mode, flags=0, value=(0, 0, 0), opacity=1.0, constant=False):
            """Blend a constant row here if its channel is still constant; otherwise leave it to the GPU."""
            from .environment_layers import blend as blended
            if constant and effect in foldable and not path and not flags & LAYER_MASKED and blend_name in BLENDS:
                over = [1 - v for v in triple(value)] if flags & LAYER_INVERT else triple(value)
                result = blended(folded[effect], over, blend_name, float(opacity))
                limits = FOLDED[effect]
                if all(math.isfinite(v) for v in result) and (limits is None or (
                        max(result) - min(result) <= 1e-7 and limits[0] <= result[0] <= limits[1])):
                    folded[effect] = result
                    return
            foldable.discard(effect)
            self.layer(channel, mode, flags, value=value, opacity=opacity)

        path = []           # the groups the current row sits in, outermost first
        pending = {}        # target identity -> mask register, written by a mask row before its target
        bumped = False

        def masked(identity):
            """Flags for a row or group whose mask was written earlier; the register is then free."""
            register = pending.pop(identity, None)
            return 0 if register is None else LAYER_MASKED | register << LAYER_MASK_SHIFT

        def enter(groups):
            """Close and open groups until the current path is the row's, as compositing.Groups does."""
            common = 0
            while common < min(len(groups), len(path)) and groups[common] == path[common]:
                common += 1
            while len(path) > common:
                group = path.pop()
                if len(path) < GROUP_DEPTH:
                    self.layer(LAYER_GROUP_END, BLENDS.get(group.get('blend', 'normal'), 0),
                               (LAYER_INVERT if group.get('invert') else 0) | masked(group.get('id')), opacity=group.get('opacity', 1))
            for group in groups[common:]:
                if len(path) < GROUP_DEPTH:
                    self.layer(LAYER_GROUP_BEGIN)
                else:
                    self.note('groups nested more than %d deep' % GROUP_DEPTH, name)
                path.append(group)

        for layer in layers:
            layer = dict(layer)
            effect = textures.EFFECT_ALIASES.get(layer['effect'], layer['effect'])
            if layer.get('procedural'):
                # The plugin bakes these patterns to an image for MoonRay too.
                try:
                    from .procedurals import bake
                    baked = bake(layer['procedural'])
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.note('a procedural layer that could not be baked (%s)' % exc, name)
                    continue
                layer.update(kind='imageMap', path=str(baked[0]), image_channel='ignore', srgb=False, color_space='raw', bias=.5, gain=.5)
                layer.pop('procedural')
                self.note('the alpha of procedural layers', name)
            kind = layer.get('kind', 'imageMap')
            enter(layer.get('groups') or [])
            blend = layer.get('blend', 'normal')
            if kind == 'materialBase':
                # A material row sets every channel at once, blended over the rows below it.
                base = graph.defaults_for(layer['material'])
                mask = masked(layer.get('identity'))
                for effect_name, channel in CHANNELS.items():
                    if effect_name in UNSET_BY_ROWS:
                        continue
                    value = triple(base[effect_name])
                    if layer.get('invert') and effect_name in textures.COLOR_EFFECTS:
                        value = [1 - v for v in value]
                    put(effect_name, channel, blend, BLENDS.get(blend, 0), mask, value, layer.get('opacity', 1), constant=True)
                continue
            if effect == 'layerMask':
                # Held in a register until the row or group it masks comes up.
                free = [r for r in range(MASK_REGISTERS) if r not in pending.values()]
                if not free:
                    self.note('more than %d layer masks waiting at once' % MASK_REGISTERS, name)
                    continue
                channel = LAYER_MASK_BASE + free[0]
                pending[layer.get('mask_target', '')] = free[0]
            elif effect not in CHANNELS:
                self.note('%s layers' % textures.EFFECTS.get(effect, effect), name)
                continue
            else:
                channel = CHANNELS[effect]
            mode = BLENDS.get(blend, 0)
            if blend == 'normalblend':
                # Only normal maps are combined this way; elsewhere the plugin rejects it.
                mode = BLEND_REORIENTED_NORMAL if effect == 'normal' else 0
            flags, texture, slot, value = (LAYER_INVERT if layer.get('invert') else 0), -1, 0, (0, 0, 0)
            extra = {}
            if effect != 'layerMask':
                flags |= masked(layer.get('identity'))

            def abandon():
                if effect == 'layerMask':
                    pending.pop(layer.get('mask_target', ''), None)

            if kind == 'constant':
                value = layer['value']
            elif kind == 'gradient':
                data = layer['gradient']
                if data.get('input') not in CHANNELS:
                    self.note('gradients driven by %s' % textures.EFFECTS.get(data.get('input'), data.get('input')), name)
                    abandon()
                    continue
                try:
                    texture = self.ramp(data)
                except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                    self.note('a gradient that could not be read (%s)' % exc, name)
                    abandon()
                    continue
                flags |= LAYER_RAMP
                slot = CHANNELS[data['input']]
            elif kind in ('checker', 'noise'):
                slot = self.slot(layer.get('coordinate_key') or '')
                if slot is None:
                    self.note('textures beyond %d UV projections' % UV_SLOTS, name)
                    abandon()
                    continue
                flags |= LAYER_CHECKER if kind == 'checker' else LAYER_NOISE
                value = layer['color1']
                extra = dict(color2=layer['color2'], alpha1=float(layer.get('alpha1', 1)), alpha2=float(layer.get('alpha2', 1)),
                             octaves=float(layer.get('octaves', 4)), lacunarity=float(layer.get('lacunarity', 2)),
                             persistence=float(layer.get('persistence', .5)),
                             scale=(1, 1) if layer.get('coordinate_key') else layer.get('scale', [1, 1]))
            elif kind == 'imageMap':
                tile_u = layer.get('tile_u', 'repeat' if layer.get('repeat', True) else 'edge')
                tile_v = layer.get('tile_v', tile_u)
                tiled = '<UDIM>' in layer['path']
                try:
                    if tiled and (tile_u, tile_v) != ('repeat', 'repeat'):
                        raise ValueError('UDIM tiles need Repeat on both axes')
                    texture = self.udim(layer) if tiled else self.texture(layer)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    self.note('a texture that could not be read (%s)' % exc, name)
                    abandon()
                    continue
                # Named coordinates are baked per mesh with their transform; otherwise the primary UVs.
                slot = self.slot(layer.get('coordinate_key') or '')
                if slot is None:
                    self.note('textures beyond %d UV projections' % UV_SLOTS, name)
                    abandon()
                    continue
                if tiled:
                    flags |= LAYER_UDIM
                source_channel = layer.get('image_channel', 'use' if layer.get('use_alpha') else 'ignore')
                flags |= {'use': LAYER_ALPHA_MASK, 'only': LAYER_ALPHA_ONLY, 'red': 1 << LAYER_PICK_SHIFT,
                          'green': 2 << LAYER_PICK_SHIFT, 'blue': 3 << LAYER_PICK_SHIFT}.get(source_channel, 0)
                for key, flag in (('flip_red', LAYER_FLIP_RED), ('flip_green', LAYER_FLIP_GREEN), ('flip_blue', LAYER_FLIP_BLUE)):
                    if layer.get(key):
                        flags |= flag
                if tile_u == 'reset':
                    flags |= LAYER_COVERAGE_U
                if tile_v == 'reset':
                    flags |= LAYER_COVERAGE_V
                if not layer.get('coordinate_key') and effect not in ('normal', 'bump'):
                    extra = dict(scale=layer.get('scale', [1, 1]))
            else:
                self.note('%s layers' % kind, name)
                abandon()
                continue
            corrections = layer.get('corrections') or {}
            contrast, brightness = float(corrections.get('contrast', 1)), float(corrections.get('brightness', 1))
            bumped = bumped or effect == 'bump'
            plain = (contrast, brightness, corrections.get('gamma', 1), layer.get('bias', .5), layer.get('gain', .5)) == (1, 1, 1, .5, .5)
            if kind == 'constant' and plain and effect != 'layerMask':
                put(effect, channel, blend, mode, flags, value, layer.get('opacity', 1), constant=True)
                continue
            foldable.discard(effect)
            self.layer(channel, mode, flags, texture, slot, value, layer.get('opacity', 1),
                       contrast * brightness, .5 * (1 - contrast) * brightness, gamma=float(corrections.get('gamma', 1)),
                       bias=float(layer.get('bias', .5)), gain_curve=float(layer.get('gain', .5)), **extra)
        enter([])
        defaults = dict(defaults, **{effect: value if FOLDED[effect] is None else value[0] for effect, value in folded.items()})

        # What rdla.py renders through DwaBaseMaterial rather than UsdPreviewSurface.
        glass = source.get('transmission', 0) > 0 or source.get('presence', 1) < 1 or 'dissolve' in effects or any(
            e.startswith('tran') for e in effects)
        dwa = bool(stack) or glass or source.get('dispersion_abbe', 0) > 0 or source.get('shader') == 'DwaBaseMaterial' or bool(
            {'aniso', 'subsCol', 'subsAmt', 'normalCoat', 'coatBump', 'diffRough'} & effects) or source.get(
            'subsurface_amount', 0) > 0 or source.get('diffuse_roughness', 0) > 0
        ior, under = float(source.get('ior', 1.5)), -1.0
        if stack:
            # DwaBaseMaterial dims diffuse by its transmission roughness, which the plugin sets apart
            # from the surface roughness.
            under = min(1.0, max(0.0, float(source.get('refraction_roughness', 0))))
            # Stacks render through DwaBaseMaterial, where a standard material's specular amount is
            # its reflectance at normal incidence and no amount means no specular lobe.
            if source.get('standard_material') and not source.get('metallic', 0):
                f0 = max(0.0, min(.99, sum(source.get('specular', [.04] * 3)) / 3))
                ior = (1 + math.sqrt(f0)) / (1 - math.sqrt(f0))
            if source.get('specular_amount', .04) <= 0:
                ior = 1.0
        # A stack's coat is DwaBaseMaterial's outer specular, which shades what is beneath it.
        flags = (MATERIAL_THIN if source.get('thin_geometry') else 0) | (MATERIAL_COAT_DIMS if stack else 0)
        # A stack binds every channel, anisotropy included, and the plugin selects DwaBaseMaterial's
        # Beckmann lobe whenever anisotropy is bound or set. Everything else gets GGX.
        stretched = bool(stack and supported(stack)) or bool(dwa and (source.get('anisotropy', 0) or 'aniso' in effects))
        if stretched or source.get('anisotropy', 0) or source.get('_beckmann'):
            flags |= MATERIAL_BECKMANN
        controls = shader_controls(source)
        # The lobe is stretched along a tangent measured from texture u of the primary coordinates,
        # which a mesh then has to carry.
        uneven = defaults['aniso'] or 'aniso' in effects or any(m.get('anisotropy', 0) for m in stack or [])
        tangent_slot = self.slot('') if stretched and uneven else None
        # Light scatters beneath the surface over the material's distance when any of it does.
        scattering = dwa and (defaults['subsAmt'] > 0 or 'subsAmt' in effects or bool(stack and supported(stack)))
        radius = max(0.0, float(source.get('subsurface_distance', 0))) if scattering else 0.0
        if radius > 0 and controls['subsurface_model'] != 0:
            self.note('the dipole and random walk subsurface models, shown as normalized diffusion', name)
        # A solid with an absorption distance takes its colour from the depth crossed.
        depth = 0.0
        if dwa and not source.get('thin_geometry'):
            try:
                medium = absorption.medium(material)
            except ValueError:
                medium = None
                self.note('absorption inside a material whose layers have different interiors', name)
            if medium is not None:
                inner = [m for m in medium['stack_medium'] if absorption.enabled(m)] if medium.get('stack_medium') else [medium]
                depth = float(inner[-1]['absorption_distance'])
        values = (triple(defaults['diffCol']) + [min(1.0, max(0.0, float(defaults['metallic']))),
                  min(1.0, max(0.0, float(defaults['rough']))), max(1.0, ior)] + triple(defaults['lumiCol'])
                  + [float(defaults['diffAmt']), float(defaults['lumiAmt']), under, min(1.0, max(0.0, float(defaults['tranAmt'])))]
                  + triple(defaults['tranCol'])
                  + [min(1.0, max(0.0, float(v))) for v in (defaults['tranRough'],)]
                  + [max(1.0, float(source.get('transmission_ior', source.get('ior', 1.5))))]
                  + [min(1.0, max(0.0, float(defaults[key]))) for key in ('coatAmt', 'coatRough', 'dissolve')]
                  + [float(source.get('bump_strength', .005)) if bumped else 0.0]
                  + [max(-1.0, min(1.0, float(defaults['aniso']))) if stretched else 0.0,
                     math.cos(controls['anisotropy_angle']), math.sin(controls['anisotropy_angle'])]
                  + [min(1.0, max(0.0, float(defaults['subsAmt']))) if radius > 0 else 0.0] + triple(defaults['subsCol'])
                  + [radius, depth, max(0.0, float(source.get('dispersion_abbe', 0))) if dwa else 0.0])
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Material %s contains a non-finite number' % name)
        return struct.pack('<32f4I', *values, flags, start, len(self.layers) - start, UV_SLOTS if tangent_slot is None else tangent_slot)
