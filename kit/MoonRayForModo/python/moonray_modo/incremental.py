"""Conservative edit classification; unknown dependencies force a full capture."""
LIGHTS={'camera','sunLight','pointLight','areaLight','spotLight','lightMaterial','environment','envMaterial'}
MATERIALS={'advancedMaterial','material.moonrayMoonShine','material.moonrayMaterialX','imageMap','constant','checker','noise','grid','dots','gradient','videoStill'}

def deformers(scene):
    """Whether the scene has anything that deforms a mesh. Where Modo cannot be asked, it is taken to have."""
    for kind in ('deform',):
        try:
            if scene.items(kind,superType=True):return True
        except (RuntimeError,LookupError,AttributeError):return True
    return False


def classify(scene, identities, cache):
    # A native material added from Add Layer has a type of its own; it is a material like the rest.
    types={'advancedMaterial' if kind.startswith('material.dw.') or kind=='material.mtlx' else kind for kind in (scene.item(identity).type for identity in identities)}
    if 'mesh' in types and types<=LIGHTS|{'mesh'}:
        if cache.get('_evaluated_data') is None and not cache.get('extra_geometry'):
            try:
                if not deformers(scene) and not scene.items('meshInst',superType=False) and not scene.items('replicator',superType=False):
                    return {'dirty_meshes':{identity for identity in identities if scene.item(identity).type=='mesh'}}
            except (RuntimeError,LookupError,AttributeError):pass
        return False
    if types<=LIGHTS:return True
    if types<=LIGHTS|MATERIALS:return 'materials'
    if types<=LIGHTS|{'translation','rotation','scale'}:
        owners=[]
        try:
            for identity in identities:
                item=scene.item(identity)
                if item.type not in LIGHTS:owners.extend(item.itemGraph('xfrmCore').forward())
            if owners and all(item.type in LIGHTS for item in owners):return True
            # Meshes read as Modo evaluates them stand where their items do, when that was found to be so at the
            # time they were read: moving one is then a matter of asking its item where it now is.
            plain=cache.get('_evaluated_data') is None
            # A light or the camera moved along with them is read again in any case.
            if (plain or cache.get('_item_transforms')) and owners and all(item.type in LIGHTS or item.type in (('mesh','meshInst') if plain else ('mesh',)) for item in owners):
                from .coordinates import descriptors
                if any(d.get('projection','uv')!='uv' for d in descriptors(cache['materials']).values()):return False
                # A deformer may depend on world transforms. Retain the full path
                # whenever the scene declares one, even for an unrelated mesh.
                if deformers(scene):return False
                return 'transforms'
        except (RuntimeError,LookupError,AttributeError):return False
    # Texture locators can change baked coordinate data; mesh/deformer changes can
    # affect other items. They use the full path until dependency evidence exists.
    return False


def moves_sky(scene,identities,cache):
    """Whether an edit turns or changes the sun of a physically based sky. That sky is painted from where its sun is,
    so each step of such an edit paints the whole sky again; a drag of it is shown when the button comes up."""
    suns={layer.get('sun_identity') for environment in (cache or {}).get('environments',[]) for layer in environment.get('layers',[]) if layer.get('kind')=='physical'}-{None}
    if not suns:return False
    try:
        for identity in identities:
            if identity in suns:return True
            item=scene.item(identity)
            if item.type in ('translation','rotation','scale') and any(owner.id in suns for owner in item.itemGraph('xfrmCore').forward()):return True
    except (RuntimeError,LookupError,AttributeError):pass
    return False


def surroundings(snapshot):
    """What lights the scene from all around, as something to compare: Modo's environments with their layers, where
    a sky's sun stands, and MoonRay's own environment lights. Each change to it has the preview make and load the
    whole environment again, which a drag cannot keep up with."""
    import json
    lights=[entity for entity in snapshot.get('entities') or [] if entity.get('class') in ('EnvLight','PortalLight')]
    return json.dumps([snapshot.get('environments') or [],lights],sort_keys=True,default=str)


def refresh_transforms(scene,snapshot):
    from .host import world_matrix
    for mesh in snapshot['meshes']:
        if 'instances' in mesh:
            mesh['instances']=[world_matrix(scene.item(identity)) for identity in mesh['instance_ids']]
        else:
            identity=mesh.get('source_item') or mesh['identity'].split('|')[0]
            mesh['matrix']=world_matrix(scene.item(identity))
    snapshot['extra_geometry']=[dict(item,matrix=world_matrix(scene.item(item.get('source_item') or item['identity'].split('|')[0]))) for item in snapshot.get('extra_geometry',[])]
