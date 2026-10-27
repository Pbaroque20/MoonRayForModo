"""Make the private XPU2 test kit: the installed MoonRay for Modo kit (0.4.3.1) with XPU2 beside MoonRay XPU.

    python build_xpu2_kit.py --session <xpu2-session-N folder> [--base <kit folder>]

Writes MoonRayForModo/ next to this script (replacing an earlier one): the base kit, its runtime untouched, plus
runtime-xpu2/ (XPU2's own runtime from the session build) and these changes:
  - Preferences > MoonRay > XPU2 (experimental): GPU renderer MoonRay XPU / XPU2, XPU2's adaptive passes on the
    graphics card, Compile XPU2 Shaders and the shaders' state;
  - the preview session starts XPU2 in MoonRay's place where it is chosen and the render's execution mode is XPU
    or Auto, and starts MoonRay instead where XPU2 says it does not render the scene (@@MODO_XPU2 FALLBACK) or ends
    unexpectedly; final renders, MoonRay LS and MoonLightIPR are MoonRay's as before.
Private: never into a repository, never published. install_xpu2.py installs it, with a backup of the kit."""
import argparse
import json
import shutil
import time
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
KIT = HERE / 'MoonRayForModo'
INSTALLED = Path(os.environ['APPDATA']) / 'Luxology' / 'Kits' / 'MoonRayForModo'
MARKERS = ('XPU-PLUS-EXPERIMENTAL.txt', 'XPU2-EXPERIMENTAL.txt')


class Patch:
    def __init__(self, path):
        self.path = path
        text = path.read_bytes().decode('utf-8')
        self.crlf = '\r\n' in text
        self.text = text.replace('\r\n', '\n')

    def rep(self, old, new):
        if self.text.count(old) != 1:
            raise RuntimeError('%s: expected once: %r' % (self.path.name, old[:80]))
        self.text = self.text.replace(old, new)

    def save(self):
        text = self.text.replace('\n', '\r\n') if self.crlf else self.text
        self.path.write_bytes(text.encode('utf-8'))


NATIVE = '''

# XPU2, the private test build: its own runtime beside the kit's, chosen in Preferences > MoonRay > XPU2.
def xpu2_runtime():
    """XPU2's runtime: its preview session (moonray_xpu2.exe), GPU programs and the libraries it was built with."""
    return Path(__file__).resolve().parents[2] / 'runtime-xpu2'


def _setting(key, default):
    try:
        from PySide2 import QtCore
    except ImportError:
        return default
    return QtCore.QSettings('MoonRayForModo', settings_name()).value(key, default)


def xpu2():
    """Whether XPU2 renders the preview where MoonRay would render on the graphics card: off by default."""
    return str(_setting('xpu2/renderer', 'xpu')) == 'xpu2' and (xpu2_runtime() / 'moonray_xpu2.exe').is_file()


def xpu2_chain():
    """Whether XPU2 makes an adaptive render's passes on the graphics card: quicker, without the outlines of the work,
    which are known only where the passes are made on the processor."""
    return str(_setting('xpu2/adaptive_chain', 'false')).lower() in ('true', '1')


def xpu2_environment(runtime):
    """What XPU2's session starts with over environment(runtime): its own libraries and scene classes first, and the
    kit's MoonRay named for what XPU2 leaves to it."""
    root = xpu2_runtime()
    return {'PATH': str(root) + os.pathsep + environment(runtime)['PATH'], 'RDL2_DSO_PATH': str(root),
            'REZ_MOONRAY_ROOT': str(root), 'MOONRAY_XPU2_MOONRAY': str(Path(runtime) / 'moonray.exe'),
            'XPU2_SESSION_CHAIN': '1' if xpu2_chain() else '0'}


def xpu2_shaders_log():
    """Where Compile XPU2 Shaders writes how it is going."""
    return Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo' / 'xpu2-shaders.log'
'''

COMMANDS = '''"""XPU2, the private test build: compiling its GPU programs into OptiX's cache, and what state they are in."""
import os
import sys
package_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python")
if package_root not in sys.path: sys.path.insert(0, package_root)
import lx
import lxu.command


def _running(pid):
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle: return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259


_asked = [0.0, None]


def compiled():
    """Whether XPU2's runtime finds its mark of compiled shaders (moonray_xpu2 --shaders-compiled), asked at most
    every few seconds."""
    import subprocess, time
    from moonray_modo import native
    if time.monotonic() - _asked[0] < 5 and _asked[1] is not None: return _asked[1]
    exe = native.xpu2_runtime() / 'moonray_xpu2.exe'
    env = dict(os.environ)
    env.update(native.xpu2_environment(native.default_runtime()))
    for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'): env.pop(key, None)
    try: result = subprocess.run([str(exe), '--shaders-compiled'], cwd=str(exe.parent), env=env, capture_output=True,
                                 timeout=30, creationflags=0x08000000).returncode == 0
    except (OSError, subprocess.SubprocessError): result = False
    _asked[0], _asked[1] = time.monotonic(), result
    return result


def state():
    """The shaders' state in a few words: compiling (from the compile's log), compiled, or not."""
    from moonray_modo import native
    log = native.xpu2_shaders_log()
    pid = log.with_suffix('.pid')
    try: lines = [l for l in log.read_text(encoding='utf-8', errors='replace').splitlines() if l.strip()]
    except OSError: lines = []
    try: compiling = _running(pid.read_text().strip())
    except (OSError, ValueError): compiling = False
    last = lines[-1] if lines else ''
    if compiling: return 'Compiling: ' + (last.replace('XPU2 shaders: ', '') or 'starting')
    if compiled(): return 'Compiled'
    if last and 'compiled in' not in last: return 'Not compiled: ' + last.replace('XPU2 shaders: ', '')
    return 'Not compiled yet: XPU2 previews are rendered by MoonRay until they are'


class CompileShaders(lxu.command.BasicCommand):
    """Compile XPU2's GPU programs into OptiX's disk cache in the background: about an hour the first time, after which
    every XPU2 preview starts in seconds. Modo stays usable meanwhile."""
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def basic_Execute(self, msg, flags):
        import subprocess
        from moonray_modo import native
        exe = native.xpu2_runtime() / 'moonray_xpu2.exe'
        if not exe.is_file():
            lx.out('XPU2: no runtime-xpu2 in this kit'); return
        if state().startswith('Compiling'):
            lx.out('XPU2: the shaders are compiling already'); return
        log = native.xpu2_shaders_log(); log.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update(native.xpu2_environment(native.default_runtime()))
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'): env.pop(key, None)
        with open(log, 'w', encoding='utf-8') as out:
            process = subprocess.Popen([str(exe), '--compile-shaders'], cwd=str(exe.parent), env=env, stdout=out,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       creationflags=0x00000008 | 0x08000000 | 0x00004000)  # detached, no window, below normal
        log.with_suffix('.pid').write_text(str(process.pid))
        _asked[1] = None
        lx.out('XPU2: compiling the shaders in the background (about an hour the first time); see ' + str(log))
        try:
            import modo
            modo.dialogs.alert('XPU2 shaders', 'XPU2 is compiling its shaders in the background: about an hour the first '
                               'time, once. Modo stays usable; previews are rendered by MoonRay until it is done. The state '
                               'shows in Preferences > MoonRay > XPU2 (experimental).')
        except Exception:
            pass


class ShaderState(lxu.command.BasicCommand):
    """The state of XPU2's shaders (read only)."""
    def __init__(self):
        super().__init__()
        self.dyna_Add('value', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def cmd_Query(self, index, query): lx.object.ValueArray(query).AddString(state())
    def basic_Execute(self, msg, flags): pass


lx.bless(CompileShaders, 'moonray.xpu2.compileShaders')
lx.bless(ShaderState, 'moonray.xpu2.shaderState')
'''

SHEET_ENTRY = '''      <list type="Control" val="sub MoonRayXPU2:sheet">
        <atom type="Label">XPU2 (experimental)</atom>
        <atom type="ShowLabel">1</atom>
        <atom type="StartCollapsed">0</atom>
        <atom type="Hash">MoonRayXPU2:sheet</atom>
      </list>
'''

SHEET = '''    <!-- XPU2, the private test build: an asynchronous CPU and GPU renderer in MoonRay XPU's place for previews. -->
    <hash type="Sheet" key="MoonRayXPU2:sheet">
      <atom type="Label">XPU2 (experimental)</atom>
      <atom type="Layout">properties</atom>
      <list type="Control" val="cmd moonray.pref.xpu2 ?">
        <atom type="Label">GPU renderer</atom>
        <atom type="Tooltip">What renders the preview when its execution mode is XPU or Auto. MoonRay XPU, as before; or XPU2, the experimental asynchronous renderer: the processor and the graphics card each take their own work from one grid. A scene XPU2 does not render yet (see the Render Log) is rendered by MoonRay XPU instead. A running preview restarts with the change</atom>
      </list>
      <list type="Control" val="cmd moonray.pref.xpu2Chain ?">
        <atom type="Label">Adaptive passes on the graphics card</atom>
        <atom type="Tooltip">XPU2 makes each pass of an adaptive render on the graphics card: quicker, but the outlines of the work are not shown, since only the card knows them. Off, the passes are made on the processor between the card's work and the outlines show, for uniform and adaptive sampling alike</atom>
      </list>
      <list type="Control" val="cmd moonray.xpu2.shaderState ?">
        <atom type="Label">Shaders</atom>
        <atom type="Tooltip">Whether XPU2's GPU programs are compiled. Until they are, XPU2 previews are rendered by MoonRay</atom>
      </list>
      <list type="Control" val="cmd moonray.xpu2.compileShaders">
        <atom type="Label">Compile XPU2 Shaders</atom>
        <atom type="Tooltip">Compiles XPU2's GPU programs into the graphics driver's shader cache, in the background: about an hour the first time, once; every XPU2 preview after starts in seconds. Again after a graphics driver update</atom>
      </list>
    </hash>
'''

README = '''MoonRay for Modo {version} with XPU2 (experimental, private build - do not share)

XPU2 is an experimental renderer for MoonRay previews: MoonRay's path tracer and shader library ported to an
asynchronous design, where the processor and the graphics card each take their own work from one grid. It is not
affiliated with or endorsed by DreamWorks Animation.

Turn it on in Modo: System > Preferences > MoonRay > XPU2 (experimental) > GPU renderer > XPU2.
It renders the preview when the render's execution mode is XPU or Auto. Final renders, MoonRay LS and MoonLightIPR
are MoonRay's as before. XPU2 previews render the buffers the preview asks for (beauty, alpha and the AOVs) and are
denoised as MoonRay's are: the Denoiser, Smart Render and Safe Denoising work with it. Continue after a Safe
Denoising stop is MoonRay's still.

First, once: Compile XPU2 Shaders on the same page (a few minutes, in the background; Modo stays usable). Until the
shaders are compiled, previews are rendered by MoonRay XPU.

A scene XPU2 does not render yet is rendered by MoonRay XPU instead; the Render Log says why ("XPU2: ..."). Not
rendered yet, among others: deep output, continuing a saved render, a camera medium, normal-oriented curves, volumes bound to curves
or points, and scenes over 8 million pixels or 16 million triangles. What the graphics card's programs do not run yet
(points, geometry in motion, VDB, heterogeneous and emissive volumes) the processor renders in the same picture.

The preview shows the outlines of the work for uniform and adaptive sampling: each processor thread's 8-pixel tile,
and the grid cells the graphics card's queued work holds. With "Adaptive passes on the graphics card" on, adaptive
renders are quicker and show no outlines.

runtime-xpu2/ is XPU2's own runtime (its preview session and the libraries it was built with); runtime/ is the
kit's, with the MoonLightIPR branch's denoiser (denoise.exe, libdenoiser.dll): Keep Fine Detail only over fur, hair and
curves, and "Denoiser cleans its guides first" in MoonRay Source Overrides.
'''


REPO = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
# The denoiser changes of the MoonLightIPR branch (commit f7a4c66), carried into the release kit this one is made from:
# Keep Fine Detail only over fur, hair and curves; "Denoiser cleans its guides first" (a MoonRay Source Override) and the
# runtime's denoise.exe and libdenoiser.dll built with it.
DENOISER_COMMIT = 'f7a4c66'
DENOISER_BUILD = REPO / 'build' / 'native-renderer-avx' / 'bin'


def denoiser(kit):
    import subprocess
    py = kit / 'python' / 'moonray_modo'
    for name in ('denoising.py', 'native.py'):  # the release's were the branch's before the change
        text = subprocess.check_output(['git', '-C', str(REPO), 'show', '%s:kit/MoonRayForModo/python/moonray_modo/%s' % (DENOISER_COMMIT, name)])
        (py / name).write_bytes(text)
    p = Patch(py / 'preferences.py')
    p.rep("""    'toon_albedo': (True, bool),""", """    'toon_albedo': (True, bool),
    # Open Image Denoise cleans the albedo and normal guides first and trusts them (native.denoise_clean_guides).
    'denoise_clean_guides': (True, bool),""")
    p.save()
    p = Patch(py / 'scene_settings.py')
    p.rep("""'Hair, fur and other things a pixel or so wide, which a denoiser smooths away, are let through from the render as it was. More keeps more of them and more of their grain; Off is the denoiser alone'""",
          """'Fur, hair and curves, which a denoiser smooths away, are let through from the render as it was, where the render has them; elsewhere the picture is the denoiser\\'s. More keeps more of them and more of their grain; Off is the denoiser alone'""")
    p.save()
    p = Patch(kit / 'lxserv' / 'moonray_preferences.py')
    p.rep("""lx.bless(switch('toon_albedo'),'moonray.pref.toonAlbedo')""", """lx.bless(switch('toon_albedo'),'moonray.pref.toonAlbedo')
lx.bless(switch('denoise_clean_guides'),'moonray.pref.denoiseCleanGuides')""")
    p.save()
    p = Patch(kit / 'preferences.cfg')
    p.rep("""and a denoised toon stays as noisy as it was rendered. It takes effect when the next render starts</atom>
      </list>""", """and a denoised toon stays as noisy as it was rendered. It takes effect when the next render starts</atom>
      </list>
      <list type="Control" val="cmd moonray.pref.denoiseCleanGuides ?">
        <atom type="Label">Denoiser cleans its guides first</atom>
        <atom type="Tooltip">Open Image Denoise cleans the albedo and normal guides before the picture and then trusts them fully, so less of the render's noise is left on textured, bumpy and see-through surfaces. Off, as MoonRay itself does: the guides are used as rendered and trusted less. OptiX has no such mode and is unchanged. It takes effect at the next denoising</atom>
      </list>""")
    p.save()
    for name in ('denoise.exe', 'libdenoiser.dll'):
        shutil.copyfile(DENOISER_BUILD / name, kit / 'runtime' / name)


# XPU2's sampling generations in the Render item's MoonRay settings (Sampling, after Target Error): kept with the scene
# as 'xpu2_generations' and written into a preview's scene as UserData("/modo/xpu2/generations"), which XPU2's plan
# builder reads (cpu_scene.h) and MoonRay leaves alone. Defaults: 16 samples a pixel on average and a noise target of
# 10 (his choice, 2026-10-25); the rest are what XPU2 does without them.
GENERATION_FIELDS = [
    ('xpu2_generations', 'on', 'bool', 'XPU2 Sampling Generations',
     'XPU2 previews sample in generations: each pass goes where the picture is still noisy, and simple areas stop early. '
     'Off: XPU2 samples as MoonRay does, uniform or adaptive. MoonRay renders are unchanged', None, None, None),
    ('xpu2_samples', 'samples', 'int', 'Generation Samples',
     'What the render is worth, in samples a pixel on average: the generations share them out where the picture is '
     'still noisy. 0: as Pixel Samples gives (an adaptive scene: no budget, its Target Error ends it)', 0, 4096, None),
    ('xpu2_spend', 'spend', 'choice', 'Halting Rule',
     'Time = Gen. Samples: the render stops after about the time a plain render of Generation Samples would take, that '
     'time spent where the noise is. Exact = Gen. Samples: every pixel gets exactly Generation Samples, however long '
     'that takes', None, None,
     [('Time = Gen. Samples', 'time'), ('Exact = Gen. Samples', 'samples')]),
    ('xpu2_noise', 'noise', 'float', 'Halt at Noise',
     'A part of the picture stops early once it is this clean, in Target Error\'s units (lower is cleaner, and slower). '
     '0: a uniform scene spends all its samples; an adaptive scene uses its Target Error', 0.0, 1000.0, None),
    ('xpu2_seed', 'seed', 'int', 'First Look',
     'Samples every pixel gets first, before the generations choose where the rest go. 0: an eighth of Generation '
     'Samples, 16 at least (an adaptive scene: its Minimum Samples)', 0, 16384, None),
    ('xpu2_most', 'most', 'int', 'XPU2 Most Samples',
     'The most samples one pixel may get. 0: 16 times the average (an adaptive scene: its Maximum Samples)', 0, 16384, None),
    ('xpu2_cpu', 'cpu', 'bool', 'XPU2 CPU Workers',
     'The processor\'s workers take part in the generations beside the graphics card. Off: the graphics card takes '
     'every sample', None, None, None),
]


def generations(kit):
    py = kit / 'python' / 'moonray_modo'
    p = Patch(py / 'scene_settings.py')
    p.rep("""    'denoising': {'engine': 'off', 'preview': True, 'final': True, 'safe': False, 'smart': 'off', 'detail': 'some'},""",
          """    'denoising': {'engine': 'off', 'preview': True, 'final': True, 'safe': False, 'smart': 'off', 'detail': 'some'},
    # XPU2's sampling generations (the private test build): 16 samples a pixel on average and a noise target of 10 by
    # default; the rest are what XPU2 does without them.
    'xpu2_generations': {'on': True, 'samples': 16, 'spend': 'time', 'noise': 10.0, 'seed': 4, 'most': 0, 'cpu': True},""")
    p.rep("""key in ('recovery', 'denoising', 'deep', 'exr')""", """key in ('recovery', 'denoising', 'deep', 'exr', 'xpu2_generations')""")
    fields = ''.join("""        field(%r, ('xpu2_generations', %r), %r, %r, %r%s),
""" % (key, member, kind, label, tip,
       (', %r, %r' % (low, high) if low is not None else '') + (', choices=%r' % (choices,) if choices else ''))
                     for key, member, kind, label, tip, low, high, choices in GENERATION_FIELDS)
    p.rep("""        render_field('target_adaptive_error', 'Target Error', 'Adaptive sampling: lower is cleaner and slower'),
""", """        render_field('target_adaptive_error', 'Target Error', 'Adaptive sampling: lower is cleaner and slower'),
""" + fields)
    p.save()
    p = Patch(py / 'scene_setup.py')
    p.rep("""    scene['execution_mode'] = values['execution_mode']""", """    scene['execution_mode'] = values['execution_mode']
    # XPU2's sampling generations (the private test build), written into a preview's scene for XPU2 (rdla.py).
    scene['xpu2_generations'] = values['xpu2_generations']""")
    p.save()
    p = Patch(py / 'rdla.py')
    p.rep("""    if safe and safe.get('data'):""", """    # XPU2's sampling generations (the private test build): its render settings in a preview, as a UserData that XPU2
    # reads (cpu_scene.h: 1, on, samples, spend exactly, noise target, first generation, most samples, CPU workers,
    # realtime: the preview following the scene with RT on, panel.py) and MoonRay leaves alone.
    generation=scene.get('xpu2_generations')
    if generation and not output_file:
        values=[1,1 if generation.get('on',True) else 0,int(generation.get('samples',0)),1 if generation.get('spend')=='samples' else 0,
                float(generation.get('noise',0.0)),int(generation.get('seed',0)),int(generation.get('most',0)),1 if generation.get('cpu',True) else 0,
                1 if scene.get('_realtime') else 0]
        lines += ['UserData("/modo/xpu2/generations") {','  ["float_key"] = "xpu2_generations",',
                  '  ["float_values_0"] = {%s},' % ', '.join('%g' % v for v in values),'}']
    if safe and safe.get('data'):""")
    p.save()
    p = Patch(kit / 'lxserv' / 'moonray_render_settings.py')
    p.rep("""                if entry['key'] in NEEDS_DENOISER:""", """                # XPU2's sampling generations' own settings, greyed with generations off.
                if entry['key'] in %r:
                    try:return bool(scene_settings.complete(properties.scene_settings())['xpu2_generations'].get('on',True))
                    except Exception:return True
                if entry['key'] in NEEDS_DENOISER:""" % (tuple(f[0] for f in GENERATION_FIELDS[1:]),))
    # And the other way: with generations on, MoonRay's own sampling settings are greyed (XPU2 previews use the XPU2
    # ones; final renders, MoonRay's, still use them).
    p.rep("""            def basic_Enable(self,msg):
""", """            def basic_Enable(self,msg):
                # XPU2's sampling generations (the private test build): on, MoonRay's own sampling settings are greyed
                # (XPU2 previews use the XPU2 ones; final renders, MoonRay's, still use them).
                if entry['key'] in ('sampling_mode','samples','min_adaptive_samples','max_adaptive_samples','target_adaptive_error'):
                    try:
                        if scene_settings.complete(properties.scene_settings())['xpu2_generations'].get('on',True):return False
                    except Exception:pass
""")
    # Generation Samples left at 0 shows what XPU2 takes then: a uniform scene's Pixel Samples, squared.
    p.rep("""                value=scene_settings.get(scene_settings.complete(properties.scene_settings()),entry)
""", """                value=scene_settings.get(scene_settings.complete(properties.scene_settings()),entry)
                # Generation Samples left at 0 (the private test build): what XPU2 takes then, a uniform scene's Pixel Samples
                # squared, Pixel Samples itself being greyed while generations are on.
                if entry['key']=='xpu2_samples' and not value:
                    try:
                        held=scene_settings.complete(properties.scene_settings())
                        if held['render'].get('sampling_mode')!=ADAPTIVE:value=int(held.get('samples',0))**2
                    except Exception:pass
""")
    p.save()
    from xml.sax.saxutils import escape
    controls = ''.join("""      <list type="Control" val="cmd moonray.render.%s ?">
        <atom type="Label">%s</atom>
        <atom type="Tooltip">%s</atom>
      </list>
""" % (key, escape(label), escape(tip)) for key, _, _, label, tip, _, _, _ in GENERATION_FIELDS)
    p = Patch(kit / 'render_settings.cfg')
    p.rep("""      <list type="Control" val="cmd moonray.render.target_adaptive_error ?">
        <atom type="Label">Target Error</atom>
        <atom type="Tooltip">Adaptive sampling: lower is cleaner and slower</atom>
      </list>
""", """      <list type="Control" val="cmd moonray.render.target_adaptive_error ?">
        <atom type="Label">Target Error</atom>
        <atom type="Tooltip">Adaptive sampling: lower is cleaner and slower</atom>
      </list>
""" + controls)
    p.save()


# Realtime in the preview window: an RT switch of its own left of the engine (MoonLightIPR, or MoonRay where XPU2
# renders the preview), the Render button rendering once; the one greyed while the other is in use. A preview that
# follows the scene marks its scene _realtime, which rdla.py writes into the generations' UserData for XPU2 (its
# realtime frames, cpu_scene.h).
def realtime(kit):
    p = Patch(kit / 'python' / 'moonray_modo' / 'panel.py')
    p.rep("""        self.ipr_mode.setChecked(self._live())
        row.addWidget(self.preview_engine)
""", """        # Realtime is off as the window opens: its switch, RT, turns it on (the private test build).
        self.ipr_mode.setChecked(False)
        # Realtime (the private test build): a switch of its own left of the engine, the Render button rendering once.
        # On, the preview follows the scene as it is edited: MoonLightIPR, or MoonRay where XPU2 renders the preview.
        # Each is greyed while the other is in use: Render while RT is on, RT while a render runs or stops.
        self.rt=QtWidgets.QPushButton('RT Off');self.rt.setCheckable(True)
        self.rt.setStyleSheet('QPushButton:checked{background-color:#f49c1c;color:#1a1a1a;border:1px solid #ffb84d;border-radius:3px;font-weight:bold;}')
        self.rt.toggled.connect(self._rt_toggled)
        row.addWidget(self.rt)
        row.addWidget(self.preview_engine)
""")
    p.rep("""    def _live(self):
        \"\"\"Whether the engine chosen is the realtime one, which follows the scene as it is edited.\"\"\"""",
          """    def _rt_capable(self):
        \"\"\"Whether the engine chosen can follow the scene in realtime (the private test build): MoonLightIPR, or MoonRay
        where XPU2 renders the preview (Preferences > MoonRay > XPU2).\"\"\"
        engine=self.preview_engine.currentData()
        if engine=='moonlightipr':return True
        if engine!='moonray':return False
        try:
            from . import native
            return bool(native.xpu2())
        except Exception:return False

    def _rt_toggled(self,on):
        \"\"\"The RT switch: realtime on, the preview follows the scene from now; off, realtime ends, its picture kept, and
        the Render button is free again. Not while a render runs or stops: Stop it first.\"\"\"
        if getattr(self,'_rt_syncing',False):return
        if on and (not self._rt_capable() or self._output_busy() or self._rt_blocked()):
            if not self._rt_capable():
                self.status.setText('Realtime is MoonLightIPR\\'s, or MoonRay\\'s with XPU2 chosen in Preferences > MoonRay > XPU2.')
            self._sync_rt();return
        if on:
            self.ipr_mode.setChecked(True)
            self.start_render()
        else:
            self.ipr_mode.setChecked(False)
            # As MoonLightIPR rests when realtime goes off: the render stops where it stands, its picture kept.
            if self._rendering and not getattr(self,'_stopping',False) and not self._output_busy():self.stop()
        self._sync_rt()
        self._set_rendering(self._rendering)

    def _rt_blocked(self):
        \"\"\"Whether a render other than realtime's runs, or one stops: RT is greyed until it is done.\"\"\"
        return bool((self._rendering and not self.ipr_mode.isChecked()) or getattr(self,'_stopping',False))

    def _sync_rt(self):
        \"\"\"Keep the RT switch saying whether realtime is on, and whether it can be with the engine chosen.\"\"\"
        if not hasattr(self,'rt') or not hasattr(self,'renderer'):return
        self._rt_syncing=True
        try:
            on=bool(self.ipr_mode.isChecked())
            self.rt.setChecked(on);self.rt.setText('RT On' if on else 'RT Off')
            self.rt.setEnabled(self._rt_capable() and not self._output_busy() and not self._rt_blocked())
            self.rt.setToolTip('Realtime is on: the preview follows the scene as you edit it. Press to switch it off.' if on else
                               'A render is under way. Stop it, or let it finish, to switch realtime on.' if self._rt_blocked() else
                               'Realtime is off. Press to have the preview follow the scene as you edit it (MoonLightIPR, or '
                               'MoonRay with XPU2).' if self._rt_capable() else
                               'Realtime is MoonLightIPR\\'s, or MoonRay\\'s with XPU2 chosen in Preferences > MoonRay > XPU2.')
        finally:self._rt_syncing=False

    def _live(self):
        \"\"\"Whether the engine chosen is the realtime one, which follows the scene as it is edited.\"\"\"""")
    # A change of engine leaves realtime off; its switch turns it on.
    p.rep("""            if self.ipr_mode.isChecked()!=live:self.ipr_mode.setChecked(live)""",
          """            if self.ipr_mode.isChecked():self.ipr_mode.setChecked(False)""")
    p.rep("""        self.timer.setInterval(60 if self._engine()=='moonlightipr' else 150)""",
          """        self.timer.setInterval(60 if self._engine()=='moonlightipr' or self._rt_capable() else 150)""")
    # Render renders once and Stop stops, realtime with it.
    p.rep("""    def _render_or_stop(self):
        if self._rendering or self._following:self.stop()
        else:self.start_render()""", """    def _render_or_stop(self):
        if self._rendering or self._following:
            if self.ipr_mode.isChecked():self.ipr_mode.setChecked(False)
            self.stop();self._sync_rt()
        else:self.start_render()""")
    # The Render button is no longer realtime's: it says Render or Stop whatever the engine.
    p.rep("""        if self._live():
            # A realtime engine is switched on and off, not started and stopped.""", """        self._sync_rt()
        if self.ipr_mode.isChecked():
            # Realtime is on (the private test build): this button is greyed, and RT Off gives it back.
            self.start.setChecked(False);self.start.setCheckable(False)
            self.start.setEnabled(False);self.start.setText('Render')
            self.start.setToolTip('Realtime is on. Switch RT off to render once.')
            return
        if self._engine()=='moonlightipr' and not self._rendering:
            # MoonLightIPR renders in realtime alone: RT turns it on, and this button is greyed.
            self.start.setChecked(False);self.start.setCheckable(False)
            self.start.setEnabled(False);self.start.setText('Render')
            self.start.setToolTip('MoonLightIPR renders in realtime: switch RT on.')
            return
        if False:
            # (The private test build: realtime has its switch, RT, left of the engine; this button renders once.)
            # A realtime engine is switched on and off, not started and stopped.""")
    # A preview that follows the scene with MoonRay is XPU2's realtime: its scene says so.
    p.rep("""        if engine=='moonray':scene=dict(scene,_pixel_samples=int(grid)**2)
        self.renderer.submit(scene, self.runtime_path(), width, height, grid,""",
          """        if engine=='moonray':scene=dict(scene,_pixel_samples=int(grid)**2)
        if engine=='moonray' and self._following and not output:scene=dict(scene,_realtime=True)
        self.renderer.submit(scene, self.runtime_path(), width, height, grid,""")
    # Realtime renders at the realtime preview size (Preferences), as MoonLightIPR does; Render renders the picture.
    p.rep("""        width = scene_w if final or not (self._live() or self._low()) else min(scene_w,size)""",
          """        width = scene_w if final or not (self._live() or self._low() or (self.ipr_mode.isChecked() and self._rt_capable())) else min(scene_w,size)""")
    # A region is rendered with Render, whatever the engine; the button says Stopping while a render stops.
    p.text = p.text.replace("""%('RT Off' if self._live() else 'Render')""", """%'Render'""")
    p.rep("""        self._stopping=True
        if not self._live():
            self.start.setEnabled(False);self.start.setText('Stopping')""", """        self._stopping=True
        self._sync_rt()
        if True:
            self.start.setEnabled(False);self.start.setText('Stopping')""")
    # XPU2's realtime denoises its own pictures where Denoised Beauty is chosen (xpu2_session.cc, RealtimeDenoiser): the
    # buffer stays chosen as realtime comes on.
    p.rep("""            if self.buffer.currentData()=='denoised_beauty' and self._engine()!='moonlightipr':""",
          """            if self.buffer.currentData()=='denoised_beauty' and self._engine()!='moonlightipr' and not (self.ipr_mode.isChecked() and self._rt_capable()):""")
    p.save()
    # The buffer chosen goes to XPU2 as its view, Denoised Beauty among them; MoonRay kept loaded is given the beauty for it.
    p = Patch(kit / 'python' / 'moonray_modo' / 'render.py')
    p.rep("""        if key=='denoised_beauty':return # Post-process result, not a native render output.""",
          """        if key=='denoised_beauty' and not native.xpu2():return # Post-process result, not a native render output.""")
    p.save()
    p = Patch(kit / 'python' / 'moonray_modo' / 'persistent.py')
    p.rep("""        self.view=key
        staged=self.root/'view.tmp';staged.write_text(key,encoding='ascii');staged.replace(self.root/'view.txt')""",
          """        self.view=key
        # XPU2's realtime denoises its pictures where Denoised Beauty is chosen; MoonRay kept loaded hands over its beauty.
        if key=='denoised_beauty' and not getattr(self,'xpu2_active',False):key='beauty'
        staged=self.root/'view.tmp';staged.write_text(key,encoding='ascii');staged.replace(self.root/'view.txt')""")
    p.save()
    # A realtime frame's denoised picture, handed over in memory as it went, stays the frame's until the kit's denoiser
    # makes one from its files (or for good, where none is made).
    p = Patch(kit / 'python' / 'moonray_modo' / 'buffer_cache.py')
    p.rep("""            self.frame=frame;self.progressive=None;self.progressive_frames.clear();self.progressive_scene=None""",
          """            carried=self.progressive_frames.get('denoised_beauty')
            if carried is not None and self.progressive_scene is snapshot and 'denoised_beauty' not in copied and 'denoised_beauty' in carried.get('linear',{}):
                frame['linear']={'denoised_beauty':carried['linear']['denoised_beauty']}
            self.frame=frame;self.progressive=None;self.progressive_frames.clear();self.progressive_scene=None""")
    p.save()


# The denoised beauty and the Denoiser in Render Settings agree: OptiX unless the scene chooses otherwise, and with the
# Denoiser Off no Denoised Beauty in the preview's list, whatever the engine (MoonLightIPR's and XPU2's realtime
# denoising included, which go with the list).
def denoised_buffer(kit):
    p = Patch(kit / 'python' / 'moonray_modo' / 'scene_settings.py')
    p.rep("""    'denoising': {'engine': 'off', 'preview': True,""",
          """    # OptiX unless the scene chooses: the graphics card's denoiser, the quickest (the private test build).
    'denoising': {'engine': 'optix', 'preview': True,""")
    p.save()
    p = Patch(kit / 'python' / 'moonray_modo' / 'panel.py')
    p.rep("""        for row in range(1,self.buffer.count()):
            self.buffer.view().setRowHidden(row,low or (only and not (denoises and self.buffer.itemData(row)=='denoised_beauty')))""",
          """        # The Denoiser set to Off in Render Settings is off everywhere: the denoised beauty is not in the list.
        on=self._denoiser_on()
        for row in range(1,self.buffer.count()):
            denoised=self.buffer.itemData(row)=='denoised_beauty'
            self.buffer.view().setRowHidden(row,low or (denoised and not on) or (only and not (denoises and denoised)))
        if not on and self.buffer.currentData()=='denoised_beauty':self.buffer.setCurrentIndex(self.buffer.findData('beauty'))""")
    p.rep("""    def _moonlightipr_denoises(self):
        \"\"\"Whether MoonLightIPR's list has the denoised beauty in it: always. It denoises with the graphics card's own
        denoiser, whatever the scene's denoiser is set to, when that buffer is the one chosen.\"\"\"
        return True""", """    def _denoiser_on(self):
        \"\"\"Whether Render Settings > Denoiser names a denoiser. Off is off everywhere: no denoised beauty in the list.\"\"\"
        try:return scene_settings.complete(self._settings_values_stored())['denoising']['engine']!='off'
        except Exception:return True

    def _moonlightipr_denoises(self):
        \"\"\"Whether MoonLightIPR's list has the denoised beauty in it: whenever the scene's Denoiser is not Off. It
        denoises with the graphics card's own denoiser, whichever the scene names, when that buffer is the one chosen.\"\"\"
        return self._denoiser_on()""")
    p.rep("""        # MoonRay LS is a quick look and is not denoised. MoonLightIPR denoises as it goes.
        if self._low() and self.buffer.currentData()=='denoised_beauty':""",
          """        # MoonRay LS is a quick look and is not denoised. MoonLightIPR denoises as it goes. With the Denoiser Off
        # there is no denoised beauty.
        if (self._low() or not self._denoiser_on()) and self.buffer.currentData()=='denoised_beauty':""")
    p.rep("""        engine=self._preview_denoiser()
        self._buffer_picked=None
        if self._engine()=='moonlightipr':""", """        engine=self._preview_denoiser()
        self._buffer_picked=None
        # Denoised Beauty is in the list while a denoiser is chosen.
        self._limit_buffers()
        if self._engine()=='moonlightipr':""")
    # XPU2's realtime denoises its own pictures: a denoiser chosen with realtime on shows them.
    p.rep("""        self.renderer.buffers.denoiser.request(engine)
        self.buffer.setCurrentIndex(self.buffer.findData('beauty' if engine=='off' else 'denoised_beauty'))""",
          """        self.renderer.buffers.denoiser.request(engine)
        realtime=self.ipr_mode.isChecked() and self._rt_capable() and self._denoiser_on()
        self.buffer.setCurrentIndex(self.buffer.findData('beauty' if engine=='off' and not realtime else 'denoised_beauty'))""")
    p.save()


# The preview's engines follow Preferences > MoonRay > XPU2: with XPU2 they are MoonRay and MoonLightIPR, with XPU
# MoonRay, MoonRay LS and MoonLightIPR. Kept so as the window is open (its poll), MoonRay LS chosen, or the window's
# opening engine, becoming MoonRay as XPU2 comes on.
def engines(kit):
    p = Patch(kit / 'python' / 'moonray_modo' / 'panel.py')
    p.rep("""                                       'Output renders always use MoonRay.')
""", """                                       'Output renders always use MoonRay.')
        self._sync_engines()
""")
    p.rep("""        \"\"\"Follow the scene's settings, which are edited in Modo's properties, not here.\"\"\"
        if self.disposed:return
""", """        \"\"\"Follow the scene's settings, which are edited in Modo's properties, not here.\"\"\"
        if self.disposed:return
        # And the engines Preferences > MoonRay > XPU2 allows (the private test build).
        self._sync_engines()
""")
    p.rep("""    def _rt_capable(self):""", """    def _sync_engines(self):
        \"\"\"The engines in the list, as Preferences > MoonRay > XPU2 has it (the private test build): with XPU2, MoonRay and
        MoonLightIPR; with XPU, MoonRay LS between them. MoonRay LS chosen as XPU2 comes on becomes MoonRay, an engine
        changed as any other; the list otherwise changes without changing the engine chosen.\"\"\"
        try:
            from . import native
            xpu2=bool(native.xpu2())
        except Exception:xpu2=False
        if xpu2==getattr(self,'_engines_xpu2',None):return
        self._engines_xpu2=xpu2
        if not hasattr(self,'_engine_tip'):self._engine_tip=self.preview_engine.toolTip()
        row=self.preview_engine.findData('moonray_ls')
        if xpu2 and row>=0:
            if self.preview_engine.currentData()=='moonray_ls':self.preview_engine.setCurrentIndex(self.preview_engine.findData('moonray'))
            blocker=QtCore.QSignalBlocker(self.preview_engine)
            self.preview_engine.removeItem(self.preview_engine.findData('moonray_ls'))
            del blocker
        elif not xpu2 and row<0:
            blocker=QtCore.QSignalBlocker(self.preview_engine)
            self.preview_engine.insertItem(self.preview_engine.findData('moonray')+1,'MoonRay LS','moonray_ls')
            del blocker
        self.preview_engine.setToolTip('\\n'.join(line for line in self._engine_tip.split('\\n') if not (xpu2 and line.startswith('MoonRay LS'))))
        # RT is MoonRay's with XPU2 alone.
        if hasattr(self,'_sync_rt'):self._sync_rt()

    def _rt_capable(self):""")
    p.save()


REPO_KIT = Path(r'C:\Users\Raphael Tobar\MoonRayForModo\kit\MoonRayForModo\python\moonray_modo')


def repo_fixes(kit):
    """Two of the MoonLightIPR branch's kit commits, taken from the repo: a Shader Tree displacement whose height is black
    everywhere is left out (8f1ae7f, graph.zero_height), and the preview window's memory meter (a998b25)."""
    py = kit / 'python' / 'moonray_modo'
    source = (REPO_KIT / 'graph.py').read_text(encoding='utf-8').replace('\r\n', '\n')
    start = source.index('def zero_height(binding, lines):')
    end = source.index('    return bodies\n', start) + len('    return bodies\n')
    p = Patch(py / 'graph.py')
    p.rep('DISPLACEMENT = None\n', 'DISPLACEMENT = None\n\n\n' + source[start:end])
    p.save()
    p = Patch(py / 'rdla.py')
    p.rep("        elif shader_displacement.get(tag) and shader_displacement[tag][1]:",
          "        elif shader_displacement.get(tag) and shader_displacement[tag][1] and not graph_module.zero_height(shader_displacement[tag][0], lines):")
    p.save()
    shutil.copy2(REPO_KIT / 'memory_meter.py', py / 'memory_meter.py')
    p = Patch(py / 'panel.py')
    p.rep("""        self.image_info=QtWidgets.QLabel('');self.image_info.setEnabled(False)
        right.addStretch(1)
        right.addWidget(self.image_info)""", """        self.image_info=QtWidgets.QLabel('');self.image_info.setEnabled(False)
        right.addStretch(1)
        # The memory the renderer, the machine and the graphics card have, beside the picture's details.
        from .memory_meter import MemoryMeter
        self.memory_meter=MemoryMeter(self._renderer_processes)
        right.addWidget(self.memory_meter)
        right.addWidget(self.image_info)""")
    p.rep("""    def _focus_armed(self,armed):""", """    def _renderer_processes(self):
        \"\"\"The ids of the renderer's processes running now (a final render, the preview session, MoonLightIPR's), for the
        memory meter.\"\"\"
        renderer=getattr(self,'renderer',None)
        if renderer is None:return []
        found=[]
        for holder in (renderer,getattr(renderer,'session',None),getattr(renderer,'moonlightipr',None)):
            process=getattr(holder,'process',None) if holder is not None else None
            try:
                if process is not None and process.state()!=QtCore.QProcess.NotRunning:found.append(int(process.processId()))
            except RuntimeError:pass  # its Qt object already gone
        return found

    def _focus_armed(self,armed):""")
    p.save()


def displacement_choice(kit):
    """The main kit's displacement tessellation choice (MoonLightIPR branch, uncommitted 2026-10-26): Follow Modo (the
    render item's Displacement Rate as adaptive_error), a fixed dicing camera held at the Dicing Frame, or uniform."""
    py = kit / 'python' / 'moonray_modo'
    p = Patch(py / 'options.py')
    p.rep("""    'enable_displacement': (1, 0, 1, 'Displacement'),""", """    'enable_displacement': (1, 0, 1, 'Displacement'),
    # How a displaced polygon mesh is tessellated where the object says nothing (the kit's own, OWN): 1 follows Modo's
    # Displacement Rate from the render camera; 2 the same from a dicing camera held at the Dicing Frame; 0 uniformly.
    'displacement_tessellation': (1, 0, 2, 'Displacement tessellation'),
    'displacement_adaptive_error': (0.0, 0.0, 64.0, 'Adaptive error override (pixels; 0 = Modo\\'s Displacement Rate)'),
    'dicing_frame': (-1.0, -1000000.0, 1000000.0, 'Dicing frame (-1 = the first frame)'),""")
    p.rep("""OWN = ('batch_tile_order', 'bucket_size', 'important_first')""",
          """OWN = ('batch_tile_order', 'bucket_size', 'important_first', 'displacement_adaptive_error', 'displacement_tessellation', 'dicing_frame')""")
    p.rep("""ENUMS['bucket_size'] = """, """ENUMS['displacement_tessellation'] = [('Uniform (mesh resolution)',0),('Follow Modo (Displacement Rate)',1),('Fixed dicing camera',2)]
ENUMS['bucket_size'] = """)
    p.save()
    p = Patch(py / 'scene_settings.py')
    line = next(l for l in p.text.split('\n') if l.startswith("        render_field('enable_displacement', 'Displacement',"))
    p.rep(line + '\n', line + '\n' + """        render_field('displacement_tessellation', 'Displacement Tessellation', 'How displaced polygon meshes are cut into triangles. Follow Modo: finely where they are large on screen and coarsely where small, to Modo''s Displacement Rate (Render item), as Modo does: far less geometry and a quicker start. Fixed dicing camera: the same, worked out from the Dicing Camera (or the render camera) held at the Dicing Frame, so the triangles stay put while the camera moves (no shimmer in an animation). Uniform: by each mesh''s resolution, the same whatever the camera. An object''s own Subdivision Screen Error wins; instances stay uniform'),
        render_field('displacement_adaptive_error', 'Adaptive Error Override', 'Pixels of screen error in place of Modo''s Displacement Rate (lower is finer). 0: Modo''s'),
        render_field('dicing_frame', 'Dicing Frame', 'The frame the fixed dicing camera is held at. -1: the scene''s first frame'),
""")
    p.save()
    p = Patch(py / 'rdla.py')
    p.rep("""            mesh=dict(mesh,adaptive_error=settings['adaptive_error'])""",
          """            # The object's own screen error; else, as the scene's Displacement Tessellation says, Modo's Displacement Rate
            # (or the Adaptive Error Override) or none (uniform); an instancer's reference stays uniform.
            if settings['adaptive_error']:error=settings['adaptive_error']
            elif 'instances' in mesh or held_render['displacement_tessellation']==0:error=0.0
            else:error=held_render['displacement_adaptive_error'] or float(scene.get('displacement_rate',1.0))
            mesh=dict(mesh,adaptive_error=error)""")
    p.save()
    p = Patch(py / 'host.py')
    p.rep("""def world_matrix(item):
    rows = lx.object.Matrix(item.channel('worldMatrix').get()).Get4()""", """def world_matrix(item, time=None):
    rows = lx.object.Matrix(item.channel('worldMatrix').get() if time is None else item.channel('worldMatrix').get(time)).Get4()""")
    p.rep("""def dicing_view(scene, identity, width, height, pixel_aspect, warnings):""",
          """def dicing_view(scene, identity, width, height, pixel_aspect, warnings, time=None):""")
    p.rep("""    if item.id == scene.renderCamera.id:
        return None""", """    if item.id == scene.renderCamera.id and time is None:
        return None""")
    p.rep("""    return {'matrix': world_matrix(item), 'identity': item.id""", """    return {'matrix': world_matrix(item, time), 'identity': item.id""")
    start = p.text.index("    # Another camera for MoonRay's adaptive tessellation, where one is chosen.")
    end = p.text.index("            result['dicing_camera'] = view", start) + len("            result['dicing_camera'] = view")
    p.text = p.text[:start] + """    # Modo's Displacement Rate (pixels), which displaced meshes are tessellated to where the scene follows Modo.
    result['displacement_rate'] = float(channel(render, 'dispRate', 1.0))
    # Another camera for MoonRay's adaptive tessellation: the one chosen; with a fixed dicing camera, it (or the render
    # camera) held at the Dicing Frame.
    stored = properties.scene_settings()
    chosen = stored.get('dicing_camera') or ''
    rendering = stored.get('render', {}) if isinstance(stored.get('render'), dict) else {}
    if int(rendering.get('displacement_tessellation', 1)) == 2:
        frame = float(rendering.get('dicing_frame', -1.0))
        if frame < 0:
            frame = float(channel(render, 'first', 0))
        fps = float(scene.fps) if getattr(scene, 'fps', 0) else 24.0
        view = dicing_view(scene, chosen or scene.renderCamera.id, width, height, pixel_aspect, warnings, time=frame / fps)
        if view:
            result['dicing_camera'] = view
    elif chosen:
        view = dicing_view(scene, chosen, width, height, pixel_aspect, warnings)
        if view:
            result['dicing_camera'] = view""" + p.text[end:]
    p.save()


def geometry_rows(kit):
    """The main kit's geometry kept as Modo hands it over (MoonLightIPR branch, uncommitted 2026-10-26): rows.py, the
    adapter's rows read as the lists they stand for and written to the binary scene as they came, and the adapter's
    arithmetic on them (MR_uv_transform, MR_zigzag4). evaluated, scene_digest, coordinates and rdlb are the base kit's
    files as they are in the repo, taken whole; rdla's few lines patched; the adapter built by tools/build_modo_bridge.py
    into build/modo-bridge-rows."""
    py = kit / 'python' / 'moonray_modo'
    for name in ('rows.py', 'evaluated.py', 'scene_digest.py', 'coordinates.py', 'rdlb.py'):
        shutil.copy2(REPO_KIT / name, py / name)
    shutil.copy2(REPO_KIT.parents[3] / 'build' / 'modo-bridge-rows' / 'MoonRayGeometry.lx', kit / 'bin' / 'MoonRayGeometry.lx')
    p = Patch(py / 'rdla.py')
    p.rep("from . import rdlb, primitive_attributes\n", "from . import rdlb, primitive_attributes, rows\n")
    p.rep("""    if kind == 'vec3' or kind == 'vec2':
        size = 3 if kind == 'vec3' else 2
        encode, value_type = (lambda: rdlb.float_list(source, size)), (rdlb.VEC3F_VECTOR if size == 3 else rdlb.VEC2F_VECTOR)
    elif kind == 'indices':
        encode, value_type = (lambda: rdlb.int_list(numbers('l', chain.from_iterable(source)))), rdlb.INT_VECTOR
    elif kind == 'counts':
        encode, value_type = (lambda: rdlb.int_list(numbers('l', map(len, source)))), rdlb.INT_VECTOR
    elif kind == 'rgb':
        encode, value_type = (lambda: rdlb.float_list(source, 3)), rdlb.RGB_VECTOR""", """    # Lists as Modo handed them over (rows.Rows, rows.Faces) go as the numbers they came in: the same bytes.
    if kind == 'vec3' or kind == 'vec2':
        size = 3 if kind == 'vec3' else 2
        held = rows.numbers(source, size)
        encode, value_type = (lambda: rdlb.float_list(source if held is None else held, size)), (rdlb.VEC3F_VECTOR if size == 3 else rdlb.VEC2F_VECTOR)
    elif kind == 'indices':
        held = rows.corners(source)
        encode, value_type = (lambda: rdlb.int_list(numbers('l', chain.from_iterable(source)) if held is None else held)), rdlb.INT_VECTOR
    elif kind == 'counts':
        held = rows.counts(source)
        encode, value_type = (lambda: rdlb.int_list(numbers('l', map(len, source)) if held is None else held)), rdlb.INT_VECTOR
    elif kind == 'rgb':
        held = rows.numbers(source, 3)
        encode, value_type = (lambda: rdlb.float_list(source if held is None else held, 3)), rdlb.RGB_VECTOR""")
    p.rep("""            # face by face, which says which mesh is wrong.
            if min(map(len, faces)) >= 3:""", """            # face by face, which says which mesh is wrong. Faces as Modo handed them over (rows.Faces) are whole
            # numbers by their kind, their corners and counts looked over as they came.
            held = rows.corners(faces)
            if held is not None and min(rows.counts(faces)) >= 3 and (not len(held) or (min(held) >= 0 and max(held) < len(vertices))):
                return ''
            if min(map(len, faces)) >= 3:""")
    p.rep("""            if len(values) != sum(map(len, faces)):
                raise ValueError('Named UV set must match polygon corners: '+uv_name)""", """            if len(values) != rows.corner_count(faces):
                raise ValueError('Named UV set must match polygon corners: '+uv_name)""")
    p.rep("""('corner_attributes', 6, sum(map(len, faces)))""", """('corner_attributes', 6, rows.corner_count(faces))""")
    p.rep("""                if len(values) != sum(map(len, faces)):
                    raise ValueError('Face-varying %s must match the corner count' % source)""", """                if len(values) != rows.corner_count(faces):
                    raise ValueError('Face-varying %s must match the corner count' % source)""")
    p.save()


def binary_memory(kit):
    """XPU2 is handed the geometry's binary scene in shared memory (modo-memory-rdlb, xpu2_session.cc's readInto), not as a
    file: a heavy scene's gigabyte of geometry no longer goes to the disk and back. MoonRay is still handed the file."""
    p = Patch(kit / 'python' / 'moonray_modo' / 'persistent.py')
    p.rep("""    def _release_mappings(self):""", """    def _write_binary(self,request,payload,memory):
        \"\"\"The geometry's binary scene (rdlb.py): in shared memory where XPU2 is to read it (modo-memory-rdlb), else a
        file beside the text.\"\"\"
        if memory and payload:
            name='Local\\\\MoonRayForModoScene_%d_%s'%(os.getpid(),uuid.uuid4().hex)
            mapping=mmap.mmap(-1,len(payload),tagname=name,access=mmap.ACCESS_WRITE)
            mapping.write(payload)
            self.mappings.setdefault(request['id'],[]).append(mapping)
            return 'modo-memory-rdlb:%d:%s'%(len(payload),name)
        binary=self.root/('%d.full.rdlb'%request['id']);binary.write_bytes(payload)
        return binary

    def _release_mappings(self):""")
    p.rep("""            scene=self._write_scene(request,'full',None,split[0])
            binary=self.root/('%d.full.rdlb'%request['id']);binary.write_bytes(split[1])""", """            scene=self._write_scene(request,'full',None,split[0])
            # Whether XPU2 takes it (as below), which reads the binary scene from shared memory.
            xpu2=bool(native.xpu2() and request['mode'] in ('xpu','auto') and not getattr(self,'xpu2_refused',None))
            binary=self._write_binary(request,split[1],xpu2)""")
    p.rep("""            binary=self.root/('%d.full.rdlb'%request['id']);binary.write_bytes(prepared['binary'])
            full='%s|%s'%(full,binary)""", """            binary=self._write_binary(request,prepared['binary'],getattr(self,'xpu2_active',False))
            full='%s|%s'%(full,binary)""")
    p.save()


def xpu2_smart_render(kit):
    """Smart Render is MoonRay's: while XPU2 renders the preview (Preferences > MoonRay > XPU2) it is greyed in the render
    settings and in the picture's menu, and no XPU2 render is stopped by it. And MoonLightIPR's images at most 1280 a
    side, as the main kit has them since 2026-10-27 (realtime's textures)."""
    p = Patch(kit / 'python' / 'moonray_modo' / 'moonlightipr_materials.py')
    p.rep("MAX_TEXTURE_SIDE = 4096", "# At most 1280 a side: perceptually enough at realtime's sizes (it was 4096).\nMAX_TEXTURE_SIDE = 1280")
    p.save()
    p = Patch(kit / 'lxserv' / 'moonray_render_settings.py')
    p.rep("""                if entry['key'] in NEEDS_DENOISER:
                    try:return scene_settings.complete(properties.scene_settings())['denoising'].get('engine','off')!='off'""",
          """                # Smart Render is MoonRay's: greyed while XPU2 renders the preview (the private test build).
                if entry['key']=='smart_render':
                    try:
                        from moonray_modo import native
                        if native.xpu2():return False
                    except Exception:pass
                if entry['key'] in NEEDS_DENOISER:
                    try:return scene_settings.complete(properties.scene_settings())['denoising'].get('engine','off')!='off'""")
    p.save()
    p = Patch(kit / 'python' / 'moonray_modo' / 'render.py')
    p.rep("""            if level!='off' and not self.active['output'] and not self.active['moonlightipr'] and not self.active.get('linear_preview') and not self.active['snapshot'].get('_ipr'):""",
          """            # Not while XPU2 renders the preview (the private test build): Smart Render is MoonRay's.
            if level!='off' and not self.active['output'] and not self.active['moonlightipr'] and not self.active.get('linear_preview') and not self.active['snapshot'].get('_ipr') and not native.xpu2():""")
    p.save()
    p = Patch(kit / 'python' / 'moonray_modo' / 'panel.py')
    p.rep("""        menu.addMenu(smart);self._smart_menu=smart""",
          """        # Smart Render is MoonRay's: greyed while XPU2 renders the preview (the private test build).
        try:
            from . import native
            if native.xpu2():smart.setEnabled(False);smart.setToolTip("Smart Render is MoonRay's; XPU2 renders the preview.")
        except Exception:pass
        menu.addMenu(smart);self._smart_menu=smart""")
    p.rep("""        from . import denoising
        try:return denoising.settings(self._settings_values()['denoising'])['smart']!='off'""",
          """        from . import denoising, native
        try:
            if native.xpu2():return False
            return denoising.settings(self._settings_values()['denoising'])['smart']!='off'""")
    p.save()


def meter_switch(kit):
    """A preference for the preview window's memory meter (Preferences > MoonRay, on): off, the meter is hidden and reads
    nothing, to tell whether its once-a-second reading is what makes the preview hesitate (asked 2026-10-27)."""
    py = kit / 'python' / 'moonray_modo'
    p = Patch(py / 'preferences.py')
    p.rep("""    'low_latency': (True, bool),""", """    'low_latency': (True, bool),
    # The preview window's memory meter (memory_meter.py).
    'memory_meter': (True, bool),""")
    p.save()
    p = Patch(kit / 'lxserv' / 'moonray_preferences.py')
    p.rep("""lx.bless(switch('low_latency'),'moonray.pref.lowLatency')""", """lx.bless(switch('low_latency'),'moonray.pref.lowLatency')
lx.bless(switch('memory_meter'),'moonray.pref.memoryMeter')""")
    p.save()
    p = Patch(kit / 'preferences.cfg')
    p.rep("""      <list type="Control" val="cmd moonray.pref.binaryGeometry ?">""", """      <list type="Control" val="cmd moonray.pref.memoryMeter ?">
        <atom type="Label">Memory meter</atom>
        <atom type="Tooltip">The preview window shows the renderer's RAM, the machine's free RAM and the graphics card's memory beside the picture's details, read once a second. Off, it is hidden and reads nothing</atom>
      </list>
      <list type="Control" val="cmd moonray.pref.binaryGeometry ?">""")
    p.save()
    p = Patch(py / 'memory_meter.py')
    p.rep("""    def refresh(self):
        self.reader.pids = [p for p in (self.processes() or []) if p]""", """    def refresh(self):
        # Off in Preferences > MoonRay (Memory meter): hidden, and nothing read.
        try:
            from . import native
            on = native._switch('memory_meter', 'MOONRAY_MODO_MEMORY_METER')
        except Exception:
            on = True
        self.reader.active = on
        if not on:
            self.hide()
            return
        self.show()
        self.reader.pids = [p for p in (self.processes() or []) if p]""")
    p.save()


def motion_skip(kit):
    """MoonLightIPR's motion-blurred readings left out where they cannot change the picture (the main kit, 2026-10-27):
    a move of items none of whose channels is animated, in a scene last found to hold nothing that moves, is read once
    (a fur scene held Modo 0.8 s at each release for three readings); a scene so found keeps its meshes for the next
    move; clip folders (imageFolder) count as steady items. The block is taken from the repo's panel.py as it is."""
    py = kit / 'python' / 'moonray_modo'
    source = (REPO_KIT / 'panel.py').read_text(encoding='utf-8').replace('\r\n', '\n')
    start = source.index('            # MoonLightIPR with motion blur: once an edit is let go')
    end = source.index('            if not blurred:', start)
    p = Patch(py / 'panel.py')
    begin = p.text.index('            # MoonLightIPR with motion blur: once an edit is let go')
    finish = p.text.index('            if not blurred:', begin)
    p.text = p.text[:begin] + source[start:end] + p.text[finish:]
    p.save()
    inc = (REPO_KIT / 'incremental.py').read_text(encoding='utf-8').replace('\r\n', '\n')
    a = inc.index('def animated(scene,identities):')
    b = inc.index('def item_matrices(scene,snapshot):')
    p = Patch(py / 'incremental.py')
    p.rep("""'scene','videoStill'}|LIGHTS|MATERIALS""", """'scene','videoStill','imageFolder'}|LIGHTS|MATERIALS""")
    p.rep("""def item_matrices(scene,snapshot):""", inc[a:b] + """def item_matrices(scene,snapshot):""")
    p.save()


def build(session, base):
    base, session = Path(base).resolve(), Path(session).resolve()
    if any((base / m).exists() for m in MARKERS):
        raise SystemExit('The base kit is an experimental one; give the release kit with --base')
    report = json.loads((session / 'build.json').read_text(encoding='utf-8'))
    if report.get('status') != 'passed':
        raise SystemExit('The session build did not pass')
    if KIT.exists():
        shutil.rmtree(KIT)
    shutil.copytree(base, KIT, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'runtime-xpu2'))
    shutil.copytree(session / 'runtime-xpu2', KIT / 'runtime-xpu2')
    py = KIT / 'python' / 'moonray_modo'
    denoiser(KIT)
    generations(KIT)
    realtime(KIT)
    denoised_buffer(KIT)
    engines(KIT)
    repo_fixes(KIT)
    displacement_choice(KIT)
    geometry_rows(KIT)
    xpu2_smart_render(KIT)
    meter_switch(KIT)
    motion_skip(KIT)

    p = Patch(py / 'preferences.py')
    p.rep("""    'auto_xpu': (True, bool),""", """    'auto_xpu': (True, bool),
    # XPU2, the private test build: what renders on the graphics card, and where its adaptive passes are made.
    'xpu2/renderer': ('xpu', str), 'xpu2/adaptive_chain': (False, bool),""")
    p.save()

    p = Patch(py / 'native.py')
    p.rep("""        globals()[key]() for key in ('usd_specular', 'opaque_alpha', 'transmission_roughness', 'auto_xpu'))""",
          """        globals()[key]() for key in ('usd_specular', 'opaque_alpha', 'transmission_roughness', 'auto_xpu')) + (xpu2(), xpu2_chain())""")
    p.rep("""        if 'falling back to cpu' in line: result='Vector active (CPU fallback — see Render Log)'""",
          """        if 'falling back to cpu' in line: result='Vector active (CPU fallback — see Render Log)'
        if 'xpu2 preview session' in line: result='XPU2 active (%s + %s)'%(_gpu() or 'NVIDIA GPU',_cpu() or 'CPU')""")
    p.text = p.text.rstrip('\n') + '\n' + NATIVE
    p.save()

    p = Patch(py / 'persistent.py')
    p.rep("""        self.process.setProcessEnvironment(env);self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(str(request['runtime']/'moonray.exe'))""",
          """        # XPU2 (the private test build) renders in MoonRay's place where it is chosen, the render's execution mode is
        # XPU or Auto, and XPU2 has not left this scene to MoonRay (@@MODO_XPU2 FALLBACK).
        program=request['runtime']/'moonray.exe'
        self.xpu2_active=bool(native.xpu2() and request['mode'] in ('xpu','auto') and not getattr(self,'xpu2_refused',None))
        # The view again, now that it is known whose: Denoised Beauty is XPU2's own (realtime), the beauty MoonRay's.
        self.select_view(self.view)
        if self.xpu2_active:
            program=native.xpu2_runtime()/'moonray_xpu2.exe'
            for key,value in native.xpu2_environment(request['runtime']).items():env.insert(key,value)
        self.process.setProcessEnvironment(env);self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(str(program))""")
    p.rep("""            if not line.startswith('@@MODO_SESSION '):continue""",
          """            if line.startswith('@@MODO_XPU2 FALLBACK'):
                # XPU2 does not render this scene: MoonRay is started in its place with the scene, as after a restart.
                self.xpu2_refused=line[len('@@MODO_XPU2 FALLBACK'):].strip() or 'it does not render this scene'
                self.status.emit('XPU2: %s. MoonRay renders this preview instead.'%self.xpu2_refused)
                if not self.closed:self.stopping=True
                continue
            if not line.startswith('@@MODO_SESSION '):continue""")
    p.rep("""        if self.running() and signature!=self.signature:
            self.stopping=True;self.process.kill();return""",
          """        if self.running() and signature!=self.signature:
            # A preference changed (XPU2's among them): XPU2 may try again.
            self.xpu2_refused=None
            self.stopping=True;self.process.kill();return""")
    p.rep("""    def _exit(self,code,status):
        self.idle.cancel()
        self._read()""",
          """    def _exit(self,code,status):
        self.idle.cancel()
        self._read()
        if getattr(self,'xpu2_active',False) and not self.stopping and not self.closed:
            # XPU2 ended without saying why: MoonRay takes the preview over.
            self.xpu2_refused='ended unexpectedly (0x%08X; see Render Log)'%(code&0xffffffff)
            self.status.emit('XPU2 %s. MoonRay renders this preview instead.'%self.xpu2_refused)
            self.stopping=True""")
    p.rep("""    def stop(self):
        self.idle.cancel()""",
          """    def stop(self):
        self.idle.cancel()
        self.xpu2_refused=None""")
    p.save()
    binary_memory(KIT)

    # Where XPU2 renders the preview: the snapshot says so.
    p = Patch(py / 'render.py')
    p.rep("""        snapshot = dict(request['snapshot'],preview_buffer=self.buffer_key)
""", """        snapshot = dict(request['snapshot'],preview_buffer=self.buffer_key)
        # XPU2 (the private test build) renders it where it is chosen, the mode is XPU or Auto and it has not left this
        # session to MoonRay.
        snapshot['_xpu2']=bool(request.get('persistent') and mode in ('xpu','auto') and native.xpu2() and not getattr(self.session,'xpu2_refused',None))
""")
    # XPU2 tells of the GPU's cells apart from the CPU's workers (@@MODO_GPU_WORKERS): they reach the view through the
    # workers' signal, marked 'gpu', and are drawn in a colour of their own beside the CPU's.
    p.rep("""                    (self.workers if line.startswith('@@MODO_WORKERS ') else self.buckets).emit(packet)""",
          """                    if line.startswith('@@MODO_GPU_WORKERS '):self.workers.emit(('gpu',)+tuple(packet))
                    else:(self.workers if line.startswith('@@MODO_WORKERS ') else self.buckets).emit(packet)""")
    p.save()
    p = Patch(py / 'buckets.py')
    p.rep("""parts[0] not in ('@@MODO_TILES','@@MODO_WORKERS')""", """parts[0] not in ('@@MODO_TILES','@@MODO_WORKERS','@@MODO_GPU_WORKERS')""")
    p.save()
    p = Patch(py / 'viewer.py')
    p.rep("""        self.workers=None
        self.show_workers=True""", """        self.workers=None
        self.gpu_workers=None  # XPU2: the cells the GPU's launches hold
        self.show_workers=True""")
    p.rep('''    def _note_outlines(self):
        """Take in what MoonRay last told of: each outline is new, or has been seen again just now."""
        told=self._outlines()''', '''    def _note_outlines(self,told=None,kind='cpu'):
        """Take in what MoonRay last told of: each outline is new, or has been seen again just now. XPU2's GPU cells
        (kind 'gpu') are told of apart from the rest."""
        told=told if told is not None else self._outlines()''')
    p.rep("""        hold=self.HOLD_WORKER if told is self.workers else self.HOLD
        for rectangle in rectangles:
            key=(width,height,rectangle)""", """        hold=self.HOLD_WORKER if told is self.workers or kind=='gpu' else self.HOLD
        for rectangle in rectangles:
            key=(width,height,rectangle,kind)""")
    p.rep("""        if packet is None:self.workers=None""", """        if packet is None:self.workers=self.gpu_workers=None""")
    p.rep("""    def set_workers(self,packet):
        self.workers=packet""", """    def set_workers(self,packet):
        if packet and packet[0]=='gpu':
            # XPU2: the GPU's cells, beside the CPU's workers.
            self.gpu_workers=packet[1:]
            if self.show_workers:self._note_outlines(self.gpu_workers,'gpu')
            return
        self.workers=packet""")
    p.rep("""drawn=[(width,height,rectangle,min(1.0,""", """drawn=[(width,height,rectangle,kind,min(1.0,""")
    p.rep("""for (width,height,rectangle),(first,last,hold) in self._fading.items()]""",
          """for (width,height,rectangle,kind),(first,last,hold) in self._fading.items()]""")
    p.rep("""for width,height,(x0,y0,x1,y1),strength in drawn:""", """for width,height,(x0,y0,x1,y1),kind,strength in drawn:""")
    # The GPU's a pastel violet beside the CPU's pastel blue.
    p.rep("""colour=QtGui.QColor('#a9cdf2');""", """colour=QtGui.QColor('#bfaef5' if kind=='gpu' else '#a9cdf2');""")
    p.save()
    # XPU2 renders the preview's outputs as MoonRay would (its AOVs), the denoiser's guides among them (albedo and normal
    # match MoonRay's), drains on Stop and Smart Render, and saves checkpoints for Safe Denoising: the kit's own
    # denoising.py, outputs.py and Stop paths serve it as they serve MoonRay.

    p = Patch(KIT / 'lxserv' / 'moonray_preferences.py')
    p.rep("""lx.bless(switch('auto_xpu'),'moonray.pref.autoXpu')""",
          """lx.bless(switch('auto_xpu'),'moonray.pref.autoXpu')
lx.bless(choice('xpu2/renderer',(('xpu','MoonRay XPU'),('xpu2','XPU2 (experimental)'))),'moonray.pref.xpu2')
lx.bless(switch('xpu2/adaptive_chain'),'moonray.pref.xpu2Chain')""")
    p.save()
    (KIT / 'lxserv' / 'moonray_xpu2.py').write_text(COMMANDS, encoding='utf-8')

    p = Patch(KIT / 'preferences.cfg')
    p.rep("""        <atom type="Hash">MoonRaySourceOverrides:sheet</atom>
      </list>
""", """        <atom type="Hash">MoonRaySourceOverrides:sheet</atom>
      </list>
""" + SHEET_ENTRY)
    p.rep("""    </hash>
  </atom>
  <atom type="Filters">""", """    </hash>
""" + SHEET + """  </atom>
  <atom type="Filters">""")
    p.save()

    version = 'unknown'
    for line in (KIT / 'index.cfg').read_text(encoding='utf-8').splitlines():
        if 'version="' in line:
            version = line.split('version="', 1)[1].split('"', 1)[0]
    (KIT / 'XPU2-EXPERIMENTAL.txt').write_text(README.format(version=version), encoding='utf-8')
    manifest = {'built': time.strftime('%Y-%m-%d %H:%M:%S'), 'base': str(base), 'session': str(session),
                'runtime_xpu2': json.loads((KIT / 'runtime-xpu2' / 'xpu2-runtime.json').read_text(encoding='utf-8'))}
    (HERE / 'kit-build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('XPU2 kit made in', KIT)


if __name__ == '__main__':
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--session', type=Path, required=True)
    a.add_argument('--base', type=Path, default=INSTALLED)
    args = a.parse_args()
    build(args.session, args.base)
