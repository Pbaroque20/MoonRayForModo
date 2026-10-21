"""Explicit native surface override and graph-output synchronization."""
import copy

def enabled(settings):
    # Preserve existing native materials authored before the checkbox existed.
    return bool(settings.get('moonshine_override',bool(settings.get('native_shader') or settings.get('node_graph'))))

def synchronize(settings,graph):
    return _synchronized(copy.deepcopy(settings),copy.deepcopy(graph))

# A graph's surface (its root's type and parameters), by the graph's content: a scene from Modo has thousands of
# materials, most with the same graph, and checking a graph (nodes.validate) is the slow part of reading them.
_ROOTS={}

def _root(graph):
    import json
    try:key=json.dumps(graph,sort_keys=True)
    except (TypeError,ValueError):key=None
    held=_ROOTS.get(key) if key is not None else None
    if held is None:
        from . import nodes
        resolved=nodes.validate(graph);root=resolved['nodes'][resolved['root']]
        held=(root['type'],copy.deepcopy(root.get('parameters',{})))
        if key is not None:
            if len(_ROOTS)>4096:_ROOTS.clear()
            _ROOTS[key]=held
    return held[0],copy.deepcopy(held[1])

def _synchronized(result,graph):
    """synchronize() on a settings dict and graph already copied for the result."""
    shader,parameters=_root(graph)
    result.update(moonshine_override=True,node_override=True,node_graph=graph,
                  native_shader=shader,native_parameters=parameters,shader='DwaBaseMaterial')
    return result

def effective(settings):
    result=copy.deepcopy(settings)
    if not enabled(result):
        result.update(native_shader='',native_parameters={},node_graph=None,node_override=False)
    elif result.get('node_graph'):
        result=_synchronized(result,result['node_graph'])
    return result
