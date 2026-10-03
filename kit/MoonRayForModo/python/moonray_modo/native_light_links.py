"""Capture unambiguous host shading-group links without touching selection."""

def linked_members(item):
    import modo
    linked=[v for v in item.itemGraph('shadeLoc').forward() if v.type in ('group','groupLocator')]
    if len(linked)!=1:raise ValueError('Expected one connected Modo group; use explicit MoonRay Object links for this item')
    members=set()
    def visit(group,trail):
        if group.id in trail:raise ValueError('Cyclic light-link group')
        if group.type=='group':children=modo.Group(group).items
        elif group.type=='groupLocator':children=group.children()
        else:members.add(group.id);return
        for child in children:visit(child,trail+(group.id,))
    visit(linked[0],())
    return sorted(members)


def capture(scene,snapshot,warnings):
    from .host import channel
    from .layers import ordered_items,material_tag
    lights={};shaders={}
    if any(channel(item,'linkEnable',False) for item in scene.items('light')):
        warnings.append('Native Modo group light linking is experimental; verify against Modo. Explicit MoonRay Object links take precedence.')
    def rule(item,mode):
        value=channel(item,mode,'include')
        if value not in ('include','exclude',0,1):raise ValueError('Unknown light-link mode')
        return {'mode':'exclude' if value in ('exclude',1) else 'include','members':linked_members(item)}
    for item in scene.items('light'):
        if not channel(item,'linkEnable',False):continue
        try:lights[item.id]=rule(item,'linkMode')
        except (ValueError,LookupError,RuntimeError,AttributeError) as exc:warnings.append('Light links for '+item.name+': '+str(exc))
    ordered=list(ordered_items(scene.renderItem));order={item.id:i for i,item in enumerate(ordered)}
    for item in ordered:
        if item.type!='defaultShader' or not channel(item,'enable',True) or not channel(item,'render',True) or not channel(item,'lgtEnable',False):continue
        try:shaders[item.id]=(item,rule(item,'lightLink'))
        except (ValueError,LookupError,RuntimeError,AttributeError) as exc:warnings.append('Shader links for '+item.name+': '+str(exc))
    materials={};data=snapshot.get('_evaluated_data')
    if data:
        for surface in data['surfaces']:
            candidates=[identity for identity in surface.get('layers',[]) if identity in shaders]
            if candidates:materials[surface['material']]=shaders[min(candidates,key=lambda v:order[v])][1]
    else:
        for tag in snapshot['materials']:
            for item,value in sorted(shaders.values(),key=lambda row:order[row[0].id]):
                try:
                    parent=item.parent
                    while parent and parent.type!='polyRender':
                        if parent.itemGraph('shadeLoc').forward():raise ValueError('Item-scoped shader links require evaluated geometry')
                        parent=parent.parent
                    scope=material_tag(item)
                    if scope in ('',tag):materials[tag]=value;break
                except (ValueError,LookupError,RuntimeError) as exc:warnings.append('Shader links for '+item.name+': '+str(exc))
    return {'lights':lights,'materials':materials}


def allowed(links,owner,tag,light_ids):
    """Per-light include/exclude overrides the shader rule, as in Modo."""
    rule=links.get('materials',{}).get(tag)
    result=set(light_ids)
    if rule:
        selected=set(rule['members']) & result
        result=selected if rule['mode']=='include' else result-selected
    for light,rule in links.get('lights',{}).items():
        if light not in light_ids:continue
        member=owner.split('|')[0] in rule['members']
        use=member if rule['mode']=='include' else not member
        if use:result.add(light)
        else:result.discard(light)
    return sorted(result)


def emit(scene,meshes,refs,environment_refs,lines):
    from .rdla import string,array
    from .lighting import owner
    links=scene.get('native_light_links',{})
    lines.append('local nativeLightSets = {}')
    if not any(links.values()):return
    light_ids=set(refs)-{'__environment__'}
    pairs=set()
    for mesh in list(meshes)+scene.get('extra_geometry',[]):
        for tag in set(mesh.get('face_materials',[]) or [mesh.get('material','')]):pairs.add((owner(mesh),tag))
    shared={}
    for identity,tag in sorted(pairs):
        selected=tuple(allowed(links,identity,tag,light_ids))
        if selected not in shared:
            name='/modo/nativeLinks/'+str(len(shared));shared[selected]='LightSet('+string(name)+')'
            members=[ref for light in selected for ref in refs[light]]+environment_refs
            lines.append(shared[selected]+'('+array(members)+')')
        lines.append('nativeLightSets[%s] = nativeLightSets[%s] or {}'%(string(identity),string(identity)))
        lines.append('nativeLightSets[%s][%s] = %s'%(string(identity),string(tag),shared[selected]))
