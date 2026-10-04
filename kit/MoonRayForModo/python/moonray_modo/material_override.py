"""Explicit native surface override and graph-output synchronization."""
import copy

def enabled(settings):
    # Preserve existing native materials authored before the checkbox existed.
    return bool(settings.get('moonshine_override',bool(settings.get('native_shader') or settings.get('node_graph'))))

def synchronize(settings,graph):
    from . import nodes
    resolved=nodes.validate(graph);root=resolved['nodes'][resolved['root']]
    result=copy.deepcopy(settings)
    result.update(moonshine_override=True,node_override=True,node_graph=copy.deepcopy(graph),
                  native_shader=root['type'],native_parameters=copy.deepcopy(root.get('parameters',{})),shader='DwaBaseMaterial')
    return result

def effective(settings):
    result=copy.deepcopy(settings)
    if not enabled(result):
        result.update(native_shader='',native_parameters={},node_graph=None,node_override=False)
    elif result.get('node_graph'):
        result=synchronize(result,result['node_graph'])
    return result
