"""Reduce translated materials to the MoonLight uber-shader and its layer stacks.

A material becomes starting values for each channel plus an ordered list of layers, each a
constant or an image blended over the rows below it, as graph.py builds for MoonRay. What has
no counterpart yet (masks, groups, procedurals, lobes MoonLight lacks) is collected by name
so the caller can report it.
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
            'groupMask': 14}
LAYER_GROUP_BEGIN, LAYER_GROUP_END, LAYER_MASK_BASE, MASK_REGISTERS, GROUP_DEPTH = 32, 33, 40, 4, 4
LAYER_MASKED, LAYER_MASK_SHIFT = 1 << 11, 12
COLORS = ('diffCol', 'lumiCol', 'tranCol')
MATERIAL_THIN, MATERIAL_COAT_DIMS = 1, 2
LAYER_INVERT, LAYER_FLIP_RED, LAYER_FLIP_GREEN, LAYER_FLIP_BLUE = 2, 4, 8, 16
LAYER_ALPHA_MASK, LAYER_ALPHA_ONLY, LAYER_COVERAGE_U, LAYER_COVERAGE_V, LAYER_PICK_SHIFT = 32, 64, 128, 256, 9
WRAP = {'repeat': 0, 'edge': 1, 'mirror': 2, 'reset': 3}
TEXTURE_FLOAT, TEXTURE_SRGB, TEXTURE_WRAP_U_SHIFT, TEXTURE_WRAP_V_SHIFT = 1, 2, 2, 4
UV_SLOTS = 8
MAX_TEXTURE_SIDE = 4096
HDR_SUFFIXES = ('.exr', '.hdr', '.tx')
KNOWN_SPACES = ('', '(default)', '(none)', 'raw', 'Linear', 'linear', 'lin_rec709', 'srgb_texture', 'sRGB')
# Lobes and controls the uber-shader has no counterpart for, by the material value that enables them.
MISSING_LOBES = (('subsurface_amount', 0, 'subsurface scattering, shown as plain diffuse'), ('anisotropy', 0, 'anisotropy'), ('diffuse_roughness', 0, 'diffuse roughness'),
                 ('dispersion_abbe', 0, 'dispersion'))


def triple(value):
    values = [float(v) for v in (value if isinstance(value, (list, tuple)) else [value] * 3)]
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError('Material contains an invalid value')
    return values


class Compiler:
    """Collects the materials of one scene; textures and coordinate slots are shared between them."""

    def __init__(self, runtime=None):
        self.runtime = runtime
        self.textures = {}      # record -> index, in first-use order
        self.slots = {}         # coordinate key -> scene-wide slot
        self.layers = []
        self.missing = {}       # what was left out -> the materials it was left out of

    def note(self, what, name):
        self.missing.setdefault(what, [])
        if name not in self.missing[what]:
            self.missing[what].append(name)

    def warnings(self):
        return ['MoonLight leaves out %s (%s).' % (what, ', '.join(names[:6]) + (' ...' if len(names) > 6 else ''))
                for what, names in sorted(self.missing.items())]

    def slot(self, key):
        if key not in self.slots:
            if len(self.slots) >= UV_SLOTS:
                return None
            self.slots[key] = len(self.slots)
        return self.slots[key]

    def texture(self, layer):
        """Convert an image once to a file the session reads directly; return its index."""
        source = Path(layer['path'])
        stat = source.stat()
        hdr = source.suffix.lower() in HDR_SUFFIXES
        digest = hashlib.sha256(repr((str(source.resolve()), stat.st_size, stat.st_mtime_ns, MAX_TEXTURE_SIDE, 'moonlight-v1')).encode()).hexdigest()
        cache = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo/MoonLight'
        target = cache / (digest + ('.pfm' if hdr else '.tga'))
        if not target.is_file() or not target.stat().st_size:
            self.convert(source, target, hdr)
        tile_u = layer.get('tile_u', 'repeat' if layer.get('repeat', True) else 'edge')
        tile_v = layer.get('tile_v', tile_u)
        if tile_u not in WRAP or tile_v not in WRAP:
            raise ValueError('Unsupported texture repeat mode')
        flags = ((TEXTURE_FLOAT if hdr else 0) | (TEXTURE_SRGB if layer.get('srgb') and not hdr else 0)
                 | WRAP[tile_u] << TEXTURE_WRAP_U_SHIFT | WRAP[tile_v] << TEXTURE_WRAP_V_SHIFT)
        path = str(target).encode('utf-8')
        record = hashlib.blake2b(path + struct.pack('<I', flags), digest_size=8).digest() + struct.pack('<2I', flags, len(path)) + path
        return self.textures.setdefault(record, len(self.textures))

    def convert(self, source, target, hdr, resample=None):
        """Write source as a Targa, or a PFM when hdr; resample replaces the default size limit."""
        from . import native
        runtime = Path(self.runtime or native.default_runtime())
        tool = runtime / 'oiiotool.exe'
        if not tool.is_file():
            raise ValueError('Texture conversion needs oiiotool.exe in the MoonRay runtime')
        def run(args):
            result = subprocess.run([str(tool)] + args, env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                raise ValueError('Texture conversion failed for %s: %s' % (source.name, result.stdout[-600:]))
            return result.stdout
        found = re.search(r'(\d+)\s*x\s*(\d+),\s*(\d+)\s+channel', run(['--info', str(source)]))
        if not found:
            raise ValueError('Cannot read texture ' + source.name)
        width, height, channels = (int(v) for v in found.groups())
        # Grey and grey-alpha images spread to RGB; a missing alpha is opaque.
        order = {1: '0,0,0,=1.0', 2: '0,0,0,1', 3: '0,1,2,=1.0'}.get(channels, '0,1,2,3')
        args = [str(source), '--ch', order.rsplit(',', 1)[0] if hdr else order]
        if not hdr and channels in (2, 4):
            # The session blends with alpha itself, so colours must not arrive already multiplied by it.
            args += ['--unpremult', '--attrib', 'oiio:UnassociatedAlpha', '1']
        if resample is not None:
            args += list(resample)
        elif max(width, height) > MAX_TEXTURE_SIDE:
            args += ['--fit', '%dx%d' % (MAX_TEXTURE_SIDE, MAX_TEXTURE_SIDE)]
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.stem + '-' + uuid.uuid4().hex + target.suffix)
        try:
            run(args + (['-d', 'float'] if hdr else ['-d', 'uint8', '--compression', 'none']) + ['-o', str(staged)])
            staged.replace(target)
        finally:
            if staged.exists():
                staged.unlink()

    def layer(self, channel, blend=0, flags=0, texture=-1, slot=0, value=(0, 0, 0), opacity=1.0, gain=1.0, offset=0.0):
        opacity = float(opacity)
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError('Layer opacity must be between zero and one')
        self.layers.append(struct.pack('<3Ii1I6f', channel, blend, flags, texture, slot, *triple(value), opacity, gain, offset))

    def material(self, material, name):
        """Append the material's layers; return its packed record."""
        from . import graph, textures
        from .layers import BLENDS
        from .material_groups import merged, supported
        from .working_space import color as working_color, enabled as working_enabled
        stack = material.get('material_stack')
        if stack and supported(stack):
            source = merged(stack)
        else:
            # A native shader or node graph has no channel stack to translate.
            source = stack[-1] if stack else material
        defaults = graph.defaults_for(source)
        layers = source.get('layers')
        if layers is None:
            layers = [dict(value, effect=key, kind=value.get('kind', 'imageMap')) for key, value in source.get('textures', {}).items()]
        if source.get('node_graph') or source.get('native_shader'):
            self.note('native shaders and node graphs, shown with their base values', name)
            layers = []
        for key, off, label in MISSING_LOBES:
            if source.get(key, off) != off:
                self.note(label, name)
        if source.get('opacity', 1) < 1:
            self.note('opacity', name)
        if source.get('absorption_distance', 0) > 0 and source.get('transmission', 0) > 0 and not source.get('thin_geometry'):
            self.note('absorption inside glass', name)

        start = len(self.layers)
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
                    if effect_name in ('normal', 'bump', 'groupMask'):
                        continue
                    value = triple(base[effect_name])
                    if layer.get('invert') and effect_name in textures.COLOR_EFFECTS:
                        value = [1 - v for v in value]
                    self.layer(channel, BLENDS.get(blend, 0), mask, value=working_color(value) if effect_name in COLORS else value,
                               opacity=layer.get('opacity', 1))
                continue
            if effect in textures.INTERNAL_EFFECTS:
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
            if blend == 'normalblend':
                self.note('normal map blending', name)
                blend = 'normal'
            flags, texture, slot, value = (LAYER_INVERT if layer.get('invert') else 0), -1, 0, (0, 0, 0)
            if effect != 'layerMask':
                flags |= masked(layer.get('identity'))
            if kind == 'constant':
                value = working_color(triple(layer['value'])) if effect in COLORS else layer['value']
            elif kind == 'imageMap':
                if '<UDIM>' in layer['path']:
                    self.note('UDIM textures', name)
                    continue
                if layer.get('color_space', '') not in KNOWN_SPACES:
                    self.note('OCIO texture colour spaces', name)
                if effect in COLORS and working_enabled():
                    self.note('the ACEScg conversion of texture colours', name)
                try:
                    texture = self.texture(layer)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    self.note('a texture that could not be read (%s)' % exc, name)
                    continue
                # Named coordinates are baked per mesh with their transform; otherwise the primary UVs.
                slot = self.slot(layer.get('coordinate_key') or '')
                if slot is None:
                    self.note('textures beyond %d UV projections' % UV_SLOTS, name)
                    continue
                source_channel = layer.get('image_channel', 'use' if layer.get('use_alpha') else 'ignore')
                flags |= {'use': LAYER_ALPHA_MASK, 'only': LAYER_ALPHA_ONLY, 'red': 1 << LAYER_PICK_SHIFT,
                          'green': 2 << LAYER_PICK_SHIFT, 'blue': 3 << LAYER_PICK_SHIFT}.get(source_channel, 0)
                for key, flag in (('flip_red', LAYER_FLIP_RED), ('flip_green', LAYER_FLIP_GREEN), ('flip_blue', LAYER_FLIP_BLUE)):
                    if layer.get(key):
                        flags |= flag
                tile_u = layer.get('tile_u', 'repeat' if layer.get('repeat', True) else 'edge')
                if tile_u == 'reset':
                    flags |= LAYER_COVERAGE_U
                if layer.get('tile_v', tile_u) == 'reset':
                    flags |= LAYER_COVERAGE_V
            else:
                self.note('%s layers' % kind, name)
                if effect == 'layerMask':
                    pending.pop(layer.get('mask_target', ''), None)
                continue
            corrections = layer.get('corrections') or {}
            contrast, brightness = float(corrections.get('contrast', 1)), float(corrections.get('brightness', 1))
            if corrections.get('gamma', 1) != 1:
                self.note('texture gamma', name)
            if layer.get('bias', .5) != .5 or layer.get('gain', .5) != .5:
                self.note('texture bias and gain', name)
            bumped = bumped or effect == 'bump'
            self.layer(channel, BLENDS.get(blend, 0), flags, texture, slot, value, layer.get('opacity', 1),
                       contrast * brightness, .5 * (1 - contrast) * brightness)
        enter([])

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
        values = (working_color(triple(defaults['diffCol'])) + [min(1.0, max(0.0, float(defaults['metallic']))),
                  min(1.0, max(0.0, float(defaults['rough']))), max(1.0, ior)] + working_color(triple(defaults['lumiCol']))
                  + [float(defaults['diffAmt']), float(defaults['lumiAmt']), under, min(1.0, max(0.0, float(defaults['tranAmt'])))]
                  + working_color(triple(defaults['tranCol']))
                  + [min(1.0, max(0.0, float(v))) for v in (defaults['tranRough'],)] + [max(1.0, float(source.get('ior', 1.5)))]
                  + [min(1.0, max(0.0, float(defaults[key]))) for key in ('coatAmt', 'coatRough', 'dissolve')]
                  + [float(source.get('bump_strength', .005)) if bumped else 0.0])
        # A stack's coat is DwaBaseMaterial's outer specular, which shades what is beneath it.
        flags = (MATERIAL_THIN if source.get('thin_geometry') else 0) | (MATERIAL_COAT_DIMS if stack else 0)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Material %s contains a non-finite number' % name)
        return struct.pack('<22f3I', *values, flags, start, len(self.layers) - start)
