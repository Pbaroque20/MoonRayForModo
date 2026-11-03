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

# What every control of a material's form asks first, by the material's tag as it stands: whether it is MoonRay's and
# which shader it is. Asked by each of a DwaBaseMaterial's hundred and more controls each time the Properties panel
# looks again, which read the tag, parsed it and copied the graph each time: once for each version of the tag now.
_SUMMARY={}

def summary(item):
    """(enabled, the effective native shader) of a material item, as enabled(properties.read(item)) and
    effective(properties.read(item)).get('native_shader','') give them, found once for each version of its tag."""
    from . import properties
    try:text=item.readTag(properties.TAG)
    except (LookupError,RuntimeError,AttributeError,TypeError):text=None
    try:key=(item.id,item.type,text)
    except (LookupError,RuntimeError,AttributeError):key=None
    held=_SUMMARY.get(key) if key is not None else None
    if held is None:
        data=properties.read(item)
        held=(enabled(data),effective(data).get('native_shader',''))
        if key is not None:
            if len(_SUMMARY)>4096:_SUMMARY.clear()
            _SUMMARY[key]=held
    return held

# The inputs of a material's output node wired in its graph, by the material's tag as it stands: asked by every control
# of the Properties panel each time the panel looks again, so read once for each version of the tag.
_DRIVEN={}

def driven_inputs(text):
    """{input: the type of the node wired to it} of the graph's output node, overrides applied, for a material's tag
    text (properties.TAG); {} where there is no graph."""
    held=_DRIVEN.get(text)
    if held is None:
        held={}
        try:
            import json
            from . import nodes
            data=json.loads(text) if text else {}
            graph=data.get('node_graph') if isinstance(data,dict) and enabled(data) else None
            if graph:
                resolved=nodes.effective(graph);graph_nodes=resolved['nodes']
                for key,source in (graph_nodes[resolved['root']].get('inputs') or {}).items():
                    if source is not None and source in graph_nodes:held[key]=str(graph_nodes[source].get('type',''))
        except Exception:
            held={}
        if len(_DRIVEN)>2048:_DRIVEN.clear()
        _DRIVEN[text]=held
    return held

def driver(item,key):
    """The type of the node in the graph that drives this input of the material item, or None where nothing does: its
    value is then the graph's, not one to type in Properties."""
    from . import properties
    try:text=item.readTag(properties.TAG)
    except (LookupError,RuntimeError,AttributeError,TypeError):return None
    return driven_inputs(text).get(key)

def effective(settings):
    result=copy.deepcopy(settings)
    if not enabled(result):
        result.update(native_shader='',native_parameters={},node_graph=None,node_override=False)
    elif result.get('node_graph'):
        result=_synchronized(result,result['node_graph'])
    return result
