"""Bounded reuse of immutable geometry arrays across camera/light updates."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
_active=ContextVar('moonray_serialization_revision',default=None)
_revision=None
_cache=OrderedDict()
_bytes=0
LIMIT=64*1024*1024

@contextmanager
def revision(value):
    global _revision,_bytes
    if value!=_revision:_cache.clear();_bytes=0;_revision=value
    token=_active.set(value)
    try:yield
    finally:_active.reset(token)

def array(kind,source,encode):
    global _bytes
    if _active.get() is None:return encode()
    key=(kind,id(source));entry=_cache.get(key)
    if entry is not None and entry[0] is source:_cache.move_to_end(key);return entry[1]
    text=encode();size=len(text)*2
    if size<=LIMIT:
        while _cache and _bytes+size>LIMIT:
            _,old=_cache.popitem(last=False);_bytes-=old[2]
        _cache[key]=(source,text,size);_bytes+=size
    return text
