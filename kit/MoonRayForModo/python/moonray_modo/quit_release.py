"""What the kit has given Modo to hold for good, let go of while Python still stands, as Modo quits.

Modo keeps a listener of the kit's until it is removed, and Modo quits by finalizing Python first and letting go of
what it still holds after. lxPython3.lx's exit code then frees Python objects in a Python that is gone: Modo crashed so
on the way out, python39.dll 0xC0000005 in PyErr_Occurred or PyDict_Pop, under lxPython3.lx in ucrtbase's
execute_onexit_table (debug_modo.py capture of 2026-11-04, RtlExitUserProcess). Those crashes left no session in Modo's
usage log and nothing in the kit's fault log (Python's faulthandler is off by then), and never came with modo_cl.

So each listener the kit adds for good comes through listen(), and is taken out when Qt says the application is about
to quit; the notifiers' tables of Modo's events are emptied then too (forget).

The kit's windows likewise: Modo destroys Qt's application after Python is finalized, and the application destroys the
windows still standing, a graph editor (a child of Modo's window), the asset library, Rhizome or Convert LXO to RDL,
each of them a Python class: their destructors called into the Python that was gone, and Modo crashed (python39
PyErr_Occurred+7 under QtWidgets' wrapper, in QApplication::~QApplication from front3000's WManShutdown;
tools/probe_quit_release.py with PROBE_QUIT_EXTRA, the 0.5.5.1 kit). They are destroyed at Python's own exit
(windows), which comes after every handler of Qt's aboutToQuit and before Python is torn down.

No Qt object of Modo's may be asked for anything on the way (its parent, its windows): that alone wraps it, and the
mark PySide leaves on a wrapped object crashed Modo at the very end (see windows)."""
import atexit

_LISTENERS = []     # (listener, the COM object Modo was given) pairs, in the order added
_FORGET = []        # callables run as Modo quits, such as a notifier's clients.clear
_hooked = [False]
released = [False]
destroyed = []      # the windows' class names, as windows() destroyed them


def listen(listener):
    """lx.service.Listener().AddListener for good: through one COM object kept for it, as Modo's SDK asks (Modo's Python
    makes a new one at every call, so removing by the listener itself names one Modo never had). The COM object, which
    RemoveListener takes; raises as AddListener does."""
    import lx
    com = lx.object.Unknown(listener)
    lx.service.Listener().AddListener(com)
    _LISTENERS.append((listener, com))
    hook()
    return com


def forget(clear):
    """clear() as Modo quits: for a notifier's table of Modo's events, say."""
    _FORGET.append(clear)
    hook()


def hook():
    """Release on Qt's aboutToQuit, once Qt's application stands. True where hooked."""
    if _hooked[0]:
        return True
    try:
        from PySide2 import QtCore
    except ImportError:
        return False
    application = QtCore.QCoreApplication.instance()
    if application is None:
        return False
    application.aboutToQuit.connect(release)
    _hooked[0] = True
    return True


def release():
    """Every listener taken out, newest first, and every table forgotten. Faults are passed over: Modo is quitting."""
    released[0] = True
    try:
        import lx
        service = lx.service.Listener()
    except Exception:
        service = None
    while _LISTENERS:
        listener, com = _LISTENERS.pop()
        if service is not None:
            try:
                service.RemoveListener(com)
            except Exception:
                pass
    while _FORGET:
        clear = _FORGET.pop()
        try:
            clear()
        except Exception:
            pass


def kits_own(widget):
    """Whether a window is of a class of the kit's (python/moonray_modo, or an lxserv module of the kit's)."""
    module = type(widget).__module__ or ''
    return module.startswith('moonray_')


def windows():
    """At Python's exit: every window of the kit's still standing destroyed, with all it holds, while Python stands."""
    try:
        from PySide2 import QtWidgets
        import shiboken2
    except ImportError:
        return
    release()
    # Found among the wrappers Python holds, never through Qt's list of windows: asking Qt for its windows makes Python
    # wrap each of Modo's, PySide marks every object it wraps, and the mark calls into Python when Modo frees the
    # object at the very end, after Python is gone (shiboken2 0xC0000005 in BindingManager::retrieveWrapper, from a
    # static destructor of front3000's).
    for widget in [w for w in shiboken2.getAllValidWrappers() if isinstance(w, QtWidgets.QWidget)]:
        try:
            if shiboken2.isValid(widget) and kits_own(widget) and widget.isWindow():
                destroyed.append(type(widget).__name__)
                shiboken2.delete(widget)
        except Exception:
            pass


atexit.register(windows)
