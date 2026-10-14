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
        if len(_held) > 512:
            _held.clear()
        found = _held[key] = kind(*args)
    return found
