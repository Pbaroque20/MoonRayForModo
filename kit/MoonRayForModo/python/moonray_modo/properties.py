"""Scene-owned settings; writes are invoked inside undoable Modo commands."""
import base64
import json
import modo
from . import options

TAG = 'MRAY'


def read(item):
    try:
        data = json.loads(item.readTag(TAG))
        return data if isinstance(data, dict) else {}
    except (LookupError, RuntimeError, ValueError, TypeError):
        return {}


def write(item, values):
    item.setTag(TAG, json.dumps(values, sort_keys=True, separators=(',', ':')))
    from .property_notifications import notify
    notify()


def selected_meshes():
    return [item for item in modo.Scene().selected if item.type == 'mesh']


def selected_geometry():
    return [item for item in modo.Scene().selected if item.type in ('mesh','meshInst','replicator')]


def scene_settings():
    return read(modo.Scene().renderItem)


def encode(values):
    return base64.urlsafe_b64encode(json.dumps(values).encode('utf-8')).decode('ascii')


def decode(value):
    result = json.loads(base64.urlsafe_b64decode(value.encode('ascii')).decode('utf-8'))
    if not isinstance(result, dict):
        raise ValueError('Settings must be an object')
    return result
