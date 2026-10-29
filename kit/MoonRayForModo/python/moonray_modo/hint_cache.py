"""One popup description for each set of choices.

Modo asks a command for the choices of its popup each time it builds a form that shows it, which is every time the
selection changes, and holds on to what it is given. Made anew each time, the descriptions piled up, six for every
mesh selected; the same set of choices is now always the same description."""
_held = {}


def same(kind, *args):
    """kind(*args), made once for these arguments and given again after that."""
    key = (kind, repr(args))
    found = _held.get(key)
    if found is None:
        # Never let go: Modo holds on to what it is given, and a description freed here while Modo still held it would
        # be read after it was gone. Likely what a tester's Modo crashed on from 0.4.2, when this cache came (cleared
        # past 512), on opening a viewport's menu. The sets of choices are few, so all are kept.
        found = _held[key] = kind(*args)
    return found
