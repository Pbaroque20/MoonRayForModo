"""Normalize Modo polygon-tag mask names without widening unknown selections."""
def tag_kind(value):
    if value is None: return ''
    if isinstance(value,bytes): value=value.decode('ascii',errors='replace')
    if type(value) is int:
        if value==0: return ''
        if 0<value<2**32:
            for order in ('big','little'):
                code=value.to_bytes(4,order).decode('ascii',errors='replace').lower()
                if code=='matr': return 'material'
                if code=='part': return 'part'
        return str(value)
    key=str(value).strip().lower()
    return {'matr':'material','material':'material','part':'part'}.get(key,key)

def needs_cache(kind,value,has_targets=False):
    kind=tag_kind(kind)
    return has_targets or kind not in ('','material') or (kind=='' and bool(value))


# The kinds of item a group mask can be for, as Modo renders it: a group mask naming anything else (a plain Locator) is
# for every surface.
MASK_ITEM_KINDS = ('mesh', 'meshInst', 'replicator', 'groupLocator', 'group')


def item_kind(item):
    """An item's type by name. Modo's Python gives a Group's (of the Groups list) as '' from item.type, so it is looked
    up in the scene's type list from the item's own type number."""
    if item.type:
        return item.type
    try:
        import lx
        return lx.service.Scene().ItemTypeName(lx.object.Item(item).Type()) or ''
    except Exception:
        return ''


def mask_items(mask):
    """The items a group mask is for, of the kinds Modo goes by (MASK_ITEM_KINDS); none where it is for every surface."""
    try:
        linked = mask.itemGraph('shadeLoc').forward()
    except (LookupError, RuntimeError, AttributeError):
        return []
    return [item for item in linked if item_kind(item) in MASK_ITEM_KINDS]


def covered(target, cache=None):
    """The identifiers of the items a group mask's item covers, as Modo renders it: the item itself; under a Group
    Locator, the items under it (Group Locators among them followed further); for a Group of the Groups list, its
    members and the members of the groups inside it, followed the same way. A Group holding a plain Locator does not
    reach what is under the locator. The same rule as the geometry adapter's (shader_stacks.cpp). cache, a dict, keeps
    each item's answer for a reading."""
    if cache is not None and target.id in cache:
        return cache[target.id]
    found = set()

    def walk(item):
        if item.id in found:
            return
        found.add(item.id)
        kind = item_kind(item)
        if kind == 'groupLocator':
            for child in item.children():
                if item_kind(child) == 'groupLocator':
                    walk(child)
                else:
                    found.add(child.id)
        elif kind == 'group':
            for child in item.children():
                if item_kind(child) == 'group':
                    walk(child)
            try:
                members = item.itemGraph('itemGroups').forward()
            except (LookupError, RuntimeError, AttributeError):
                members = []
            for member in members:
                walk(member)
    walk(target)
    if cache is not None:
        cache[target.id] = found
    return found
