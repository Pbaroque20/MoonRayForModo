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
