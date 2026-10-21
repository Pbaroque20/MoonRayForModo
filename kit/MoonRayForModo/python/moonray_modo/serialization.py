"""Bounded reuse of immutable geometry arrays across camera/light updates."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
import threading
# A snapshot is made into what a renderer reads on a thread of its own while a scene is followed, and on Modo's own
# for everything else. What is kept between one writing and the next is shared, so one is written at a time.
WRITING=threading.RLock()
_active=ContextVar('moonray_serialization_revision',default=None)
_revision=None
_cache=OrderedDict()
_bytes=0
# Enough for a heavy scene's geometry as binary (rdlb.py), so that a render of it again finds it all kept.
LIMIT=512*1024*1024

@contextmanager
def revision(value):
    # Kept from one reading of the scene to the next: an entry is used only for the very list it was made from (it
    # holds the list, so no other can take its place), and a mesh that has not changed comes back as the same lists
    # (evaluated._row). What is no longer asked for goes as the cache fills.
    global _revision
    _revision=value
    token=_active.set(value)
    try:yield
    finally:_active.reset(token)

def array(kind,source,encode):
    global _bytes
    if _active.get() is None:return encode()
    key=(kind,id(source));entry=_cache.get(key)
    if entry is not None and entry[0] is source:_cache.move_to_end(key);return entry[1]
    text=encode();size=len(text) if isinstance(text,(bytes,bytearray)) else len(text)*2
    if size<=LIMIT:
        while _cache and _bytes+size>LIMIT:
            _,old=_cache.popitem(last=False);_bytes-=old[2]
        _cache[key]=(source,text,size);_bytes+=size
    return text
