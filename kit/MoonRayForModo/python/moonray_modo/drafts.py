"""Materials as they stand in an open graph editor, before they are applied to the scene.

The preview shows these in place of what the scene holds, so that an edit in the graph editor
is seen as it is made. Nothing here changes the scene: closing the editor without applying
puts the preview back to what the scene has.
"""
_drafts = {}
_changed = set()


def publish(identity, settings):
    """Show a material with these settings from now on."""
    _drafts[identity] = settings
    _changed.add(identity)


def withdraw(identity):
    """Go back to showing a material as the scene has it."""
    if _drafts.pop(identity, None) is not None:
        _changed.add(identity)


def settings(item):
    """A material's settings: the draft if an editor holds one, or else None."""
    return _drafts.get(item.id)


def consume():
    """The materials whose drafts changed since this was last asked."""
    changed = set(_changed)
    _changed.clear()
    return changed
