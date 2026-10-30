"""Conservative edit classification; unknown dependencies force a full capture."""
LIGHTS={'camera','sunLight','pointLight','areaLight','spotLight','lightMaterial','environment','envMaterial'}
MATERIALS={'advancedMaterial','material.moonrayMoonShine','material.moonrayMaterialX','imageMap','constant','checker','noise','grid','dots','cellular','wood','weave','ripples','gradient','videoStill'}

def deformers(scene):
    """Whether the scene has anything that deforms a mesh. Where Modo cannot be asked, it is taken to have."""
    for kind in ('deform',):
        try:
            if scene.items(kind,superType=True):return True
        except (RuntimeError,LookupError,AttributeError):return True
    return False


def deformed_meshes(scene):
    """The meshes something in the scene bends: those its deformers' graph leads to, through falloffs and the
    deformers they feed. None where Modo cannot be asked (then every mesh may be)."""
    try:
        bent,seen=set(),set()
        stack=list(scene.items('deform',superType=True))
        while stack:
            item=stack.pop()
            if item.id in seen:continue
            seen.add(item.id)
            for target in item.itemGraph('deformers').forward():
                if target.type=='mesh':bent.add(target.id)
                else:stack.append(target)
        return bent
    except (RuntimeError,LookupError,AttributeError):return None


def projected_items(cache):
    """The items of a reading's meshes whose materials are projected onto them from where they stand (not by UV), whose
    coordinates a move changes. None where the reading cannot tell."""
    try:
        from .coordinates import descriptors
        materials=cache.get('materials') or {}
        tags={tag for tag,material in materials.items() if any(d.get('projection','uv')!='uv' for d in descriptors({tag:material}).values())}
        if not tags:return set()
        return {mesh.get('source_item') or mesh['identity'].split('|')[0] for mesh in cache.get('meshes') or []
                if tags&set(mesh.get('face_materials') or [mesh.get('material','')])}
    except Exception:return None


def environment_locator(item):
    """Whether a texture locator places only environment layers (an HDRI's rotation): moving it changes what lights
    the scene from around it, which is read at every update, and no mesh."""
    try:
        if item.type!='txtrLocator':return False
        layers=list(item.itemGraph('shadeLoc').reverse())
        if not layers:return False
        for layer in layers:
            parent=layer.parent
            while parent is not None and parent.type!='environment':
                if parent.type=='polyRender':return False
                parent=parent.parent
            if parent is None:return False
        return True
    except (RuntimeError,LookupError,AttributeError):return False


def classify(scene, identities, cache):
    # A native material added from Add Layer has a type of its own; it is a material like the rest.
    types={'advancedMaterial' if kind.startswith('material.dw.') or kind=='material.mtlx' else kind for kind in (scene.item(identity).type for identity in identities)}
    if 'mesh' in types and types<=LIGHTS|{'mesh'}:
        # Modo's evaluated geometry too, where each mesh's geometry is its own (own_geometry): the surfaces of the meshes
        # edited are read again from its render cache, the others kept (evaluated.capture); every surface's placement,
        # an instance's or a replica's among them, is read anew all the same. An interior's edit: 2.5 s to read; a car
        # with channel modifiers and instances read whole at each edit, 28 s.
        evaluated=cache.get('_evaluated_data') is not None
        if not cache.get('extra_geometry') and (own_geometry(scene) if evaluated else True):
            try:
                if evaluated or (not deformers(scene) and not scene.items('meshInst',superType=False) and not scene.items('replicator',superType=False)):
                    # Meshes and lights alone: the Shader Tree is as it was, and its stacks' materials are kept.
                    return {'dirty_meshes':{identity for identity in identities if scene.item(identity).type=='mesh'},'shading_kept':True}
            except (RuntimeError,LookupError,AttributeError):pass
        return False
    if types<=LIGHTS:return True
    # An environment image turned or moved: what is around the scene is read again, the meshes are kept (each step
    # of turning an HDRI read the whole scene again, seconds in a large one).
    try:
        if types<=LIGHTS|{'txtrLocator','translation','rotation','scale'} and 'txtrLocator' in types or types&{'translation','rotation','scale'}:
            located=[scene.item(identity) for identity in identities]
            owners=[o for item in located if item.type in ('translation','rotation','scale') for o in item.itemGraph('xfrmCore').forward()]
            places=[item for item in located if item.type=='txtrLocator']+[o for o in owners if o.type=='txtrLocator']
            others=[item for item in located if item.type not in LIGHTS|{'txtrLocator','translation','rotation','scale'}]+[o for o in owners if o.type!='txtrLocator' and o.type not in LIGHTS]
            if places and not others and all(environment_locator(item) for item in places):return True
    except (RuntimeError,LookupError,AttributeError):pass
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
            # Any item moved (a mesh, a group, a locator, the root a whole car hangs from): what hangs from it moves
            # with it, and channel modifiers may move others, so every mesh that stands with its item is asked where
            # it now is (refresh_transforms). Read again from Modo, and only they: copies that stand with no item of
            # their own (a replicator's, _loose_items), meshes a deformer bends, and meshes textured from where they
            # stand (a projection). Moving a part of a car with instances read the whole car again, 28 s.
            if (plain or cache.get('_item_transforms')) and owners:
                again=set() if plain else set(cache.get('_loose_items') or ())
                projected=projected_items(cache)
                if projected is None:return False
                again|=projected
                if deformers(scene):
                    bent=None if plain else deformed_meshes(scene)
                    if bent is None:return False
                    again|=bent
                if again:
                    # A scene read as written (not evaluated) reads its meshes again by item, the moved ones' places
                    # asked as well; an evaluated one has every surface's place from Modo with them.
                    return {'dirty_meshes':again,'placements':True}
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


def transform_targets(scene,identities):
    """Known transform owners and descendants; unknown/instanced dependencies retain the full refresh."""
    if not identities:return None
    try:
        if scene.items('meshInst',superType=False) or scene.items('replicator',superType=False):return None
        if scene.items('chanModify',superType=True):return None
        result=set()
        for identity in identities:
            item=scene.item(identity)
            if item.type in LIGHTS:continue
            if item.type not in ('translation','rotation','scale'):return None
            owners=list(item.itemGraph('xfrmCore').forward())
            if not owners:return None
            for owner in owners:
                result.add(owner.id)
                result.update(child.id for child in owner.children(recursive=True))
        return result
    except (RuntimeError,LookupError,AttributeError):return None


# Items that neither bend a mesh nor make one come and go as time passes: meshes, lights, the camera, locators and
# their transforms, groups, the Shader Tree and MoonRay's own items and materials (read again at each moment in any case).
STEADY={'mesh','locator','groupLocator','translation','rotation','scale','transform','txtrLocator','mask','shaderFolder',
        'defaultShader','renderOutput','polyRender','render','actionclip','group','scene','videoStill','imageFolder'}|LIGHTS|MATERIALS


def standing(scene,snapshot):
    """How the meshes of a snapshot read as Modo evaluates it stand: (whether they can be followed by their items at
    all, the items whose copies stand where no item of theirs does). A mesh, or an instance (of its own item, a
    meshInst), that stands where its item does is drawn where its item now stands; copies Modo generates, which are no
    item's (a replicator's), are read again from Modo when anything moves. A fur's strands, grown from their mesh,
    stand with it as well, and are moved with it (refresh_transforms); other extra geometry is not taken to."""
    from .host import world_matrix
    try:
        extra=snapshot.get('extra_geometry') or []
        if any(item.get('kind') not in ('curves','points') or not item.get('source_item') for item in extra):return False,set()
        where,loose={},set()

        def stands(held,identity):
            if identity not in where:where[identity]=world_matrix(scene.item(identity))
            return bool(held) and len(held)==16 and all(abs(a-b)<=1e-5*max(1.0,abs(b)) for a,b in zip(held,where[identity]))
        for mesh in list(snapshot['meshes'])+list(extra):
            if mesh.get('volumetric'):continue
            if 'instances' in mesh:
                named=mesh.get('instance_ids') or []
                if len(named)!=len(mesh['instances']):return False,set()
                for held,identity in zip(mesh['instances'],named):
                    if not stands(held,identity.split('|')[0]):loose.add(identity.split('|')[0])
                continue
            identity=mesh.get('source_item') or mesh['identity'].split('|')[0]
            if not stands(mesh.get('matrix'),identity):loose.add(identity)
        return bool(where),loose
    except Exception:return False,set()


def stands_with_items(scene,snapshot):
    """Whether each mesh of a snapshot read as Modo evaluates it stands where its item does (standing): then where its
    item now stands is where it is to be drawn."""
    followed,loose=standing(scene,snapshot)
    return followed and not loose


def steady(scene):
    """Whether nothing in the scene deforms a mesh, simulates, generates or copies one, or drives a channel: every item
    is of a STEADY kind. A mesh's geometry is then its own, and no other's depends on it. Where Modo cannot be asked, it
    is taken not to be so."""
    try:
        import lx
        service=lx.service.Scene()
        kinds=[service.ItemTypeLookup(name) for name in ('light','textureLayer')]
        if deformers(scene):return False
        for item in scene.iterItems():
            kind=item.type
            if kind in STEADY or kind.startswith(('material.','moonray.')) or any(item.TestType(each) for each in kinds):continue
            return False
        return True
    except Exception:return False


# Kinds of item that make no mesh's geometry, beside the steady ones: in a scene read as Modo's evaluated geometry,
# what they do is where things stand, read anew at every reading (own_geometry). Channel modifiers (cm...) drive channels.
NEUTRAL={'assembly','schmNode','shear','CameraMatch','meshInst','replicator','camera','targetLocator'}


def own_geometry(scene):
    """Whether, in a scene read as Modo's evaluated geometry, each mesh's geometry is its own: nothing deforms one, and
    every item is of a kind that makes none (steady kinds, channel modifiers, instances, replicators). A kind not known
    to make none is taken to make some, and the scene is read whole. Where Modo cannot be asked, it is taken not to be so."""
    try:
        import lx
        service=lx.service.Scene()
        kinds=[service.ItemTypeLookup(name) for name in ('light','textureLayer')]
        if deformers(scene):return False
        for item in scene.iterItems():
            kind=item.type
            if kind in STEADY or kind in NEUTRAL or kind.startswith(('material.','moonray.','cm')) or any(item.TestType(each) for each in kinds):continue
            return False
        return True
    except Exception:return False


def rigid(scene,snapshot):
    """Whether the meshes of a snapshot hold at any other moment, only moved with their items: nothing in the scene
    deforms a mesh, simulates, generates or copies one, or drives a channel (every item is of a STEADY kind), no
    texture is projected from where a mesh stands, and each mesh stands where its item does. A reading at another
    moment, for the ends of the shutter, is then a matter of asking where the items stand (refresh_transforms), as when
    an item is moved: not of reading every mesh again. Where Modo cannot be asked, it is taken not to be so."""
    try:
        if not steady(scene):return False
        from .coordinates import descriptors
        if any(d.get('projection','uv')!='uv' for d in descriptors(snapshot.get('materials') or {}).values()):return False
        return stands_with_items(scene,snapshot)
    except Exception:return False


def animated(scene,identities):
    """Whether any channel of these items is animated (keyed, or driven by an envelope): a move of items none of whose
    channels is cannot make anything move during the shutter. Where Modo cannot be asked, they are taken to be."""
    try:
        for identity in identities or ():
            item=scene.item(identity)
            if any(channel.isAnimated for channel in item.channels()):return True
        return False
    except Exception:return True


def item_matrices(scene,snapshot):
    """Where the items of a snapshot's meshes now stand, by item."""
    from .host import world_matrix
    where={}
    for mesh in snapshot['meshes']:
        # Volumetric fog is placed anew at every reading (volumetrics.capture), where its light and the camera stand.
        if mesh.get('volumetric'):continue
        identity=mesh.get('source_item') or mesh['identity'].split('|')[0]
        if identity not in where:where[identity]=world_matrix(scene.item(identity))
    return where


def follow_items(scene,snapshot,before):
    """A rigid snapshot (rigid) at another moment: each mesh where its item then stands. One whose item stands where
    it did (before: item_matrices then) keeps the matrix it was read with, as reading it again would give it."""
    now=item_matrices(scene,snapshot)
    for mesh in snapshot['meshes']:
        if mesh.get('volumetric'):continue
        identity=mesh.get('source_item') or mesh['identity'].split('|')[0]
        if now[identity]!=before.get(identity):mesh['matrix']=now[identity]


def refresh_transforms(scene,snapshot,identities=None,loose=()):
    """Each mesh of a snapshot where its item now stands (those of identities, the moved transforms, or every one where
    what follows a move cannot be told), an instance where its own item does. Copies that stand with no item of their
    own (loose: standing) keep the places they were read with: they are read again from Modo."""
    from .host import world_matrix
    targets=transform_targets(scene,identities)
    asked={}

    def where(held,identity):
        # Where the item stands, or the place it was read with where that is the same: Modo's render cache and the
        # item's world matrix differ in their last digits, and every mesh given a new matrix so had the renderer
        # prepare the whole scene again (a car's 335 objects for one part moved).
        if identity not in asked:asked[identity]=world_matrix(scene.item(identity))
        now=asked[identity]
        if held and len(held)==16 and all(abs(a-b)<=1e-6*max(1.0,abs(b)) for a,b in zip(held,now)):return held
        return now
    for mesh in snapshot['meshes']:
        if mesh.get('volumetric'):continue
        if 'instances' in mesh:
            # An evaluated instance is named by its item and its place among that item's copies ("item|0").
            mesh['instances']=[held if identity.split('|')[0] in loose else where(held,identity.split('|')[0])
                               for held,identity in zip(mesh['instances'],mesh['instance_ids'])]
        else:
            identity=mesh.get('source_item') or mesh['identity'].split('|')[0]
            if identity in loose:continue
            if targets is None or identity in targets:mesh['matrix']=where(mesh.get('matrix'),identity)
    snapshot['extra_geometry']=[dict(item,matrix=where(item.get('matrix'),item.get('source_item') or item['identity'].split('|')[0])) if targets is None or (item.get('source_item') or item['identity'].split('|')[0]) in targets else item for item in snapshot.get('extra_geometry',[])]
