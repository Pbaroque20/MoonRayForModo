"""XPU2: compiling its GPU programs into OptiX's cache, and what state they are in."""
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




def compiled():
    """Whether XPU2's runtime finds its mark of compiled shaders (native.xpu2_shaders_compiled)."""
    from moonray_modo import native
    return native.xpu2_shaders_compiled()


def _counts(lines):
    """The log's last count of tasks ("N compile tasks done, M waiting, T s", every ten seconds): (done, waiting,
    seconds), or None before the first."""
    for line in reversed(lines):
        words = line.replace(',', ' ').split()
        if 'tasks' in words and 'done' in words and 'waiting' in words:
            try:
                return (int(words[words.index('tasks') - 2]), int(words[words.index('waiting') - 1]),
                        float(words[words.index('waiting') + 1]) if len(words) > words.index('waiting') + 1 else 0.0)
            except (ValueError, IndexError):
                return None
    return None


def _progress(lines):
    """How far a compile has come, in percent; None before the first count."""
    counts = _counts(lines)
    if counts is None or not counts[0] + counts[1]:
        return None
    return int(100 * counts[0] / (counts[0] + counts[1]))


def _minutes(seconds):
    return '%d min' % max(1, round(seconds / 60.0)) if seconds >= 60 else '%d s' % max(1, round(seconds))


def last_compile():
    """How long the last whole compile took on this machine, in seconds (kept beside the log as it ends), or None."""
    from moonray_modo import native
    try:
        return float(native.xpu2_shaders_log().with_suffix('.took').read_text().strip())
    except (OSError, ValueError):
        return None


def how_long():
    """What a message says of how long a compile takes: the last one here, or that the state shows it as it goes."""
    took = last_compile()
    return 'it took %s here last time' % _minutes(took) if took else 'how long it has left shows as it goes'


def _keep_took(lines):
    """A finished compile's time ("compiled in T s") kept beside the log, for the next messages."""
    from moonray_modo import native
    for line in reversed(lines):
        if 'compiled in' in line:
            try:
                seconds = float(line.split('compiled in', 1)[1].split()[0])
                native.xpu2_shaders_log().with_suffix('.took').write_text('%.0f' % seconds)
            except (OSError, ValueError, IndexError):
                pass
            return


def state():
    """The shaders' state in a few words: compiling (how far, from the compile's log), compiled, or not."""
    from moonray_modo import native
    log = native.xpu2_shaders_log()
    pid = log.with_suffix('.pid')
    try: lines = [l for l in log.read_text(encoding='utf-8', errors='replace').splitlines() if l.strip()]
    except OSError: lines = []
    try: compiling = _running(pid.read_text().strip())
    except (OSError, ValueError): compiling = False
    last = lines[-1] if lines else ''
    if compiling:
        # How far, in percent of its compile tasks: 0% from the moment it starts (asked 2026-10-30: the state changes at
        # once, no message box).
        counts = _counts(lines)
        if counts is None or not counts[0] + counts[1]:
            return 'Compiling 0%'
        done, waiting, seconds = counts
        return 'Compiling %d%%' % int(100 * done / (done + waiting))
    _keep_took(lines)
    if compiled(): return 'Compiled'
    # Just that (asked 2026-10-30); why a compile failed is in its log and the Render Log.
    return 'Not compiled'


import lxifc

# The form's own notifier: told while the shaders compile, it asks the form to look again at the button and the
# shaders' state (how far along, then Compiled and Re-compile).
NOTIFIER = 'moonray.xpu2.shaders'


class ShadersNotifier(lxifc.Notifier):
    clients = {}
    def noti_Name(self): return NOTIFIER
    def noti_SetArgs(self, args): pass
    def noti_Args(self): return ''
    def noti_AddClient(self, event): self.clients[event.__peekobj__()] = event
    def noti_RemoveClient(self, event): self.clients.pop(event.__peekobj__(), None)


def _notify():
    for event in list(ShadersNotifier.clients.values()):
        try: lx.object.CommandEvent(event).Event(lx.symbol.fCMDNOTIFY_CHANGE_ALL)
        except (RuntimeError, LookupError): pass


_ticking = []


def _tick():
    """While the shaders compile, the form told every two seconds; once more as they are done, and the watch ended."""
    if not state().startswith('Compiling'):
        for timer in _ticking: timer.stop()
        del _ticking[:]
        from moonray_modo import native
        native._shaders_asked[1] = None    # whether they are compiled, asked again at once
    _notify()


def _watch():
    """Follow a compile under way (started here, or still running from before Modo was opened)."""
    if _ticking: return
    try:
        from PySide2 import QtCore
    except ImportError:
        return
    timer = QtCore.QTimer()
    timer.setInterval(2000)
    timer.timeout.connect(_tick)
    timer.start()
    _ticking.append(timer)


class CompileShaders(lxu.command.BasicCommand):
    """Compile XPU2's GPU programs into OptiX's disk cache in the background, once (the state says how long it has left),
    after which every XPU2 preview starts in seconds. Modo stays usable meanwhile."""
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    # Greyed while a compile is under way: pressed again, it would only start another.
    def basic_Enable(self, msg): return not state().startswith('Compiling')
    # Named for what it does now: compiled, the shaders can only be compiled again (after a driver update).
    def basic_ButtonName(self): return 'Re-compile XPU2 Shaders' if state() == 'Compiled' else 'Compile XPU2 Shaders'
    def basic_Notifier(self, index): return (NOTIFIER, '') if index == 0 else None
    def basic_Execute(self, msg, flags):
        import subprocess
        from moonray_modo import native
        exe = native.xpu2_runtime() / 'moonray_xpu2.exe'
        if not exe.is_file():
            lx.out('MoonRay XPU2: no runtime-xpu2 in this kit'); return
        if state().startswith('Compiling'):
            lx.out('MoonRay XPU2: the shaders are compiling already'); return
        log = native.xpu2_shaders_log(); log.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update(native.xpu2_environment(native.default_runtime()))
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'): env.pop(key, None)
        with open(log, 'w', encoding='utf-8') as out:
            process = subprocess.Popen([str(exe), '--compile-shaders'], cwd=str(exe.parent), env=env, stdout=out,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       creationflags=0x00000008 | 0x08000000 | 0x00004000)  # detached, no window, below normal
        log.with_suffix('.pid').write_text(str(process.pid))
        native._shaders_asked[1] = None
        _watch()
        _notify()
        lx.out('MoonRay XPU2: compiling the shaders in the background (%s); see %s' % (how_long(), log))


class ShaderState(lxu.command.BasicCommand):
    """The state of XPU2's shaders (read only)."""
    def __init__(self):
        super().__init__()
        self.dyna_Add('value', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def basic_Notifier(self, index): return (NOTIFIER, '') if index == 0 else None
    def cmd_Query(self, index, query):
        held = state()
        # A compile found under way (one still running from before Modo was opened) is followed from here.
        if held.startswith('Compiling'): _watch()
        lx.object.ValueArray(query).AddString(held)
    def basic_Execute(self, msg, flags): pass


lx.bless(ShadersNotifier, NOTIFIER)
lx.bless(CompileShaders, 'moonray.xpu2.compileShaders')
lx.bless(ShaderState, 'moonray.xpu2.shaderState')
