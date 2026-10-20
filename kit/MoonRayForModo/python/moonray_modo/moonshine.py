"""MoonShine material and ordered BSDF-layer serialization."""
import math

# MoonRay's gamma map that takes a colour to its square root.
TINT_GAMMA = 2.0

# Modo's refraction roughness, and the transmission roughness of MoonRay's that blurs a glass ball as much, fitted
# against Modo's renders of a clear ball at 0.1, 0.3, 0.6 and 0.9 (check_glass): Modo's blur rises quickly at first and
# then levels off. Between them, straight; past 0.9, on as from 0.6.
REFRACTION_CURVE = ((0.0, 0.0), (0.1, 0.4), (0.3, 0.55), (0.6, 0.6), (0.9, 0.7), (1.0, 0.7333))


def refraction_through(material, value=None):
    """A Modo material's refraction roughness as MoonRay's (REFRACTION_CURVE); MoonRay's own materials keep theirs."""
    value = float(material.get('refraction_roughness', 0) if value is None else value)
    value = min(1.0, max(0.0, value))
    if not material.get('standard_material'):
        return value
    for (a, b), (c, d) in zip(REFRACTION_CURVE, REFRACTION_CURVE[1:]):
        if value <= c:
            return b + (d - b) * (value - a) / (c - a)
    return REFRACTION_CURVE[-1][1]


def passed_once(material, colour=None):
    """A Modo material's Transmission Color as MoonRay's: Modo tints the light that goes through a glass solid once,
    MoonRay as it goes in and again as it comes out, so a solid is given the square root of Modo's colour (measured on
    Modo's renders of a tinted ball: 0.3, 0.8, 0.5 came out at 0.32, 0.81, 0.52 of the clear ball in Modo and at their
    squares in MoonRay). A thin surface, crossed once, and MoonRay's own materials keep their colour as it is."""
    colour = material.get('transmission_color', [1, 1, 1]) if colour is None else colour
    if not material.get('standard_material') or material.get('thin_geometry'):
        return colour
    return [math.sqrt(max(0.0, float(c))) for c in colour]

def dielectric(cosine,straight):
    """How much a smooth surface reflects at an angle, given how much it reflects seen straight on."""
    root=math.sqrt(max(0.0,min(.9999,straight)))
    index=(1+root)/(1-root)
    sine=math.sqrt(max(0.0,1-cosine*cosine))/index
    inner=math.sqrt(max(0.0,1-sine*sine))
    across=(cosine-index*inner)/(cosine+index*inner)
    along=(index*cosine-inner)/(index*cosine+inner)
    return .5*(across*across+along*along)


# How far Modo's Fresnel setting, at full, takes a surface toward a mirror at 65 and 75 degrees from straight on,
# as its own renders show.
MODO_RISE=((math.cos(math.radians(65)),.083),(math.cos(math.radians(75)),.289))


def fresnel_match(straight,rise):
    """The reflectance to give MoonRay's specular layer so that its rise toward the edge is nearest Modo's.

    Modo reflects its specular amount seen straight on and, by its Fresnel setting, more toward the edge:
    with the setting at none, the same at every angle. MoonRay's layer always rises as glass of its index
    does. So the layer is given a higher reflectance, whose rise is flatter, and a weight that brings it
    back down to the amount; this returns that reflectance, between the amount (the steepest rise there
    is) and nearly a mirror (none).
    """
    if straight<=0:return 0.0
    best,found=None,straight
    for step in range(101):
        lobe=straight+(.99-straight)*(step/100.0)**2
        if lobe<=0:continue
        weight=straight/lobe
        error=sum((weight*dielectric(cosine,lobe)-(straight+(1-straight)*rise*share))**2 for cosine,share in MODO_RISE)
        if best is None or error<best:best,found=error,lobe
    return min(.99,found)


# Modo's Principled model, specular at none, over black in an even white sky (its own renders, tools/probe_fresnel.py,
# sheen_black_000): what it reflects from straight on to 75 degrees. Its specular rises as Schlick's does, toward a
# mirror at the edge, whatever the amount.
PRINCIPLED_RISE=((1.0,0.0),(math.cos(math.radians(40)),.001),(math.cos(math.radians(55)),.019))+MODO_RISE


# The most a Principled highlight reflects straight on (8% of a specular amount of 0.125) for which it is fitted over
# its whole curve: past it, the weight held to that amount was as near Modo's renders or nearer (principled_paint and
# principled_gloss cases).
PRINCIPLED_FITTED=.01


def principled_match(straight,rise):
    """(reflectance, weight) of MoonRay's specular layer nearest a Principled highlight that reflects straight on
    what it does there and rises toward the edge as Modo's does (rise of 1 for the whole rise). MoonRay's layer rises
    as glass does, which cannot start from nothing as Schlick's rise does: the reflectance and the weight are fitted
    together over the whole curve, straight on included, rather than the weight held to the amount straight on."""
    targets=[(cosine,straight+(1-straight)*rise*share) for cosine,share in PRINCIPLED_RISE]
    best=None
    for step in range(1,400):
        lobe=(step/400.0)**2
        reflected=[dielectric(cosine,lobe) for cosine,_ in targets]
        weight=min(1.0,max(0.0,sum(r*target for r,(_,target) in zip(reflected,targets))/max(1e-12,sum(r*r for r in reflected))))
        error=sum((weight*r-target)**2 for r,(_,target) in zip(reflected,targets))
        if best is None or error<best[0]:best=(error,lobe,weight)
    return min(.99,best[1]),best[2]


def sources(material):
    """The Modo materials a surface is made of: the rows of its stack, or itself."""
    rows=[layer['material'] for layer in material.get('layers') or [] if layer.get('kind')=='materialBase' and layer.get('material')]
    return rows or material.get('material_stack') or [material]


def specular_ceiling(material):
    """The most a standard Modo material reflects seen straight on, anywhere on it: its specular amount and
    colour, or the colour alone where an image varies either."""
    from . import textures
    stack=sources(material)
    most=max([max(m.get('specular',[0])) for m in stack]+[0])
    layers=material.get('layers')
    effects=[layer.get('effect') for layer in layers if layer.get('kind')!='materialBase'] if layers is not None else list(material.get('textures',{}))
    if any(textures.EFFECT_ALIASES.get(e,e) in ('specCol','specAmt') for e in effects):
        most=max([most]+[max(m.get('raw_specular',[1])) for m in stack])
    return max(0.0,min(.99,most))


def metal_mapped(material):
    """Whether an image varies how metallic a material is."""
    return mapped(material,'metallic')


def mapped(material,effect):
    """Whether an image varies one of a material's settings."""
    from . import textures
    layers=material.get('layers')
    effects=[layer.get('effect') for layer in layers if layer.get('kind')!='materialBase'] if layers is not None else list(material.get('textures',{}))
    return any(textures.EFFECT_ALIASES.get(e,e)==effect for e in effects)


# Modo's Principled sheen as DwaBaseMaterial's fuzz: how much fuzz a sheen of 1 is, and how rough it is, as measured
# against Modo's renders (tools/probe_fresnel.py, sheen cases).
# Fitted to Modo's sheen of 1 over black, its Principled edge without sheen taken away: within 0.01 of Modo's up to 75
# degrees from straight on, darker past that.
SHEEN_FUZZ = 0.1
SHEEN_ROUGHNESS = 0.05


def sheen(material, number, vector):
    """The fuzz attributes for a material's sheen: none where it has none. Its tint goes from white to the hue of the
    base colour (the colour at a brightness of 1), as Principled tints its sheen."""
    amount = material.get('sheen', 0)
    if not amount:
        return {}
    color = material.get('sheen_color', material.get('raw_color', material.get('color', [.5, .5, .5])))
    bright = 0.3 * color[0] + 0.6 * color[1] + 0.1 * color[2]
    hue = [c / bright for c in color] if bright > 0 else [1, 1, 1]
    tint = material.get('sheen_tint', 0)
    return {'show_fuzz': 'true', 'fuzz': number(min(1.0, amount * SHEEN_FUZZ)), 'fuzz_roughness': number(SHEEN_ROUGHNESS),
            'fuzz_albedo': vector([min(1.0, 1 - tint + tint * h) for h in hue], 'Rgb')}


# Modo's anisotropy as MoonRay's, fitted against Modo's renders of a ball (tools/probe_aniso_direction.py, grid cases):
# MoonRay's stretches far more for the same number, so it is given a share of Modo's, and its highlight is drawn rougher
# to spread as broadly as Modo's stretched one does.
ANISO_SHARE = 0.6
ANISO_ROUGHNESS = 1.35


def emit(material, tag, index, bindings, lines):
    from .rdla import string, number, vector
    from .shading_models import curve,principled_rise,strengths
    driven=None
    from .material_settings import values
    controls = values(material)
    sss_weight = bindings.get('subsurfaceAmount')
    reflection_ior = material.get('ior',1.5)
    if material.get('standard_material') and not material.get('metallic',0):
        f0 = max(0,min(.99,sum(material.get('specular',[.04]*3))/3))
        reflection_ior = (1+math.sqrt(f0))/(1-math.sqrt(f0))
    # A highlight that stretches, as Modo's anisotropy makes it: given MoonRay's measure of it below.
    stretched = bool(material.get('standard_material')) and (any(m.get('anisotropy',0) for m in sources(material)) or mapped(material,'aniso'))
    rougher = ANISO_ROUGHNESS if stretched else 1.0
    attributes = {
        'albedo':vector(material['color'],'Rgb'),
        'metallic':number(material.get('metallic',0)),
        'metallic_color':vector(material['color'],'Rgb'),
        'roughness':number(min(1.0,material.get('roughness',.4)*rougher)),
        'diffuse_roughness':number(material.get('diffuse_roughness',0)),
        'scattering_radius':number(max(0,material.get('subsurface_distance',0)) if material.get('subsurface_amount',0)>0 or sss_weight else 0),
        'scattering_color':vector(material.get('subsurface_color',[1,1,1]),'Rgb'),
        'bssrdf':str(controls['subsurface_model']),
        'enable_sss_input_normal':'true' if controls['sss_input_normal'] else 'false',
        'resolve_self_intersections':'true' if controls['sss_resolve_self_intersections'] else 'false',
        # Beckmann for a highlight that stretches, and for Modo's Blinn and Ashikhmin models, whose shape it is.
        'specular_model':'0' if material.get('anisotropy',0) or material.get('_beckmann') else '1',
        'shading_tangent':vector([math.cos(controls['anisotropy_angle']), math.sin(controls['anisotropy_angle'])],'Vec2'),
        'anisotropy':number(max(-1,min(1,material.get('anisotropy',0)*(ANISO_SHARE if stretched else 1.0)))),
        'refractive_index':number(reflection_ior),
        'use_independent_transmission_refractive_index':'true',
        'independent_transmission_refractive_index':number(material.get('ior',1.5)),
        # DwaBaseMaterial ignores the Abbe number unless dispersion is switched on.
        'use_dispersion':'true' if material.get('dispersion_abbe',0)>0 else 'false',
        'dispersion_abbe_number':number(material.get('dispersion_abbe',0)),
        'transmission':number(material.get('transmission',0)),
        'transmission_color':vector(passed_once(material),'Rgb'),
        'use_independent_transmission_roughness':'true',
        'independent_transmission_roughness':number(refraction_through(material)),
        'presence':number(material.get('presence',1)),
        'show_emission':'true',
        'emission':vector(material.get('emission',[0,0,0]),'Rgb'),
        'show_clearcoat':'true',
        'clearcoat':number(material.get('clearcoat',0)),
        'clearcoat_roughness':number(material.get('clearcoat_roughness',.01)),
        'show_specular':'true' if material.get('specular_amount',.04)>0 else 'false',
        **sheen(material,number,vector),
        'thin_geometry':'true' if material.get('thin_geometry',False) else 'false',
    }
    names={'diffuseColor':'albedo','emissiveColor':'emission','ior':'refractive_index',
        'transmissionColor':'transmission_color','refractionRoughness':'independent_transmission_roughness',
        'diffuseRoughness':'diffuse_roughness','clearcoatRoughness':'clearcoat_roughness','specularAmount':'specular', 'subsurfaceColor':'scattering_color'}
    for key,value in bindings.items():
        if key in ('layerMask','subsurfaceAmount'):
            continue
        if key=='anisotropy' and (not material.get('standard_material') or any(m.get('anisotropy',0) for m in sources(material)) or mapped(material,'aniso')):
            # Only the Beckmann highlight stretches; a standard material that does not stretch keeps GGX, the shape of Modo's own.
            attributes['specular_model']='0'
        if key=='anisotropy' and stretched:
            # Modo's anisotropy, plain or from an image, as MoonRay's measure of it (a ramp from Modo's to MoonRay's).
            path='/modo/anisotropy/%s'%index
            lines += ['RampMap(%s) {'%string(path),'  ["ramp_type"] = 8,','  ["input"] = %s,'%value,
                      '  ["positions"] = {0, 1},','  ["colors"] = {Rgb(0, 0, 0), Rgb(%s, %s, %s)},'%((number(ANISO_SHARE),)*3),
                      '  ["interpolations"] = {1, 1},','}']
            attributes['anisotropy']='bind(RampMap(%s), 1)'%string(path)
            continue
        if key in ('normal','coatNormal'):
            name='/modo/normal/%s/%s' % (index,key)
            lines += ['ModoNormalMap(%s) { ["input"] = %s }' % (string(name),value)]
            attributes['input_normal' if key=='normal' else 'independent_clearcoat_normal']='ModoNormalMap(%s)' % string(name)
            if key=='coatNormal':attributes['use_independent_clearcoat_normal']='true'
        elif key=='ior':
            # MoonRay takes an index of refraction as a number only: a map wired to it is refused with a warning for
            # each material, and the number set above is what renders either way.
            continue
        elif key=='specularAmount' and material.get('standard_material'):
            attributes['specular']='1'
            attributes['show_specular']='true'
        elif key=='transmissionColor' and passed_once(material,[.25,.25,.25])!=[.25,.25,.25]:
            # Through a solid, MoonRay tints twice where Modo tints once (passed_once): the colour the Shader Tree
            # gives is taken to its square root on its way in.
            path='/modo/transmission/%s'%index
            lines += ['ColorCorrectGammaMap(%s) {'%string(path),'  ["input"] = %s,'%value,'  ["gamma"] = %s,'%number(TINT_GAMMA),'}']
            attributes['transmission_color']='bind(ColorCorrectGammaMap(%s), Rgb(1, 1, 1))'%string(path)
        elif key=='refractionRoughness' and material.get('standard_material'):
            # A refraction roughness from the Shader Tree goes through the curve a plain one does (REFRACTION_CURVE).
            path='/modo/refraction/%s'%index
            lines += ['RampMap(%s) {'%string(path),'  ["ramp_type"] = 8,','  ["input"] = %s,'%value,
                      '  ["positions"] = {%s},'%', '.join(number(a) for a,_ in REFRACTION_CURVE),
                      '  ["colors"] = {%s},'%', '.join('Rgb(%s, %s, %s)'%((number(b),)*3) for _,b in REFRACTION_CURVE),
                      '  ["interpolations"] = {%s},'%', '.join('1' for _ in REFRACTION_CURVE),'}']
            attributes['independent_transmission_roughness']='bind(RampMap(%s), 1)'%string(path)
        elif key=='roughness' and curve(material.get('shading_model')):
            # A roughness an image drives goes through the same curve a plain one does: Modo's roughness in, the
            # roughness of MoonRay's lobe that draws the same highlight out.
            points=curve(material['shading_model']);path='/modo/roughness/%s'%index
            lines += ['RampMap(%s) {'%string(path),'  ["ramp_type"] = 8,','  ["input"] = %s,'%value,
                      '  ["positions"] = {%s},'%', '.join(number(a) for a,_ in points),
                      '  ["colors"] = {%s},'%', '.join('Rgb(%s, %s, %s)'%((number(min(1.0,b*rougher)),)*3) for _,b in points),
                      '  ["interpolations"] = {%s},'%', '.join('1' for _ in points),'}']
            attributes['roughness']='bind(RampMap(%s), 1)'%string(path)
            # What drives the roughness, for the highlight's strength to follow it too.
            driven=value
        elif key!='specularColor':
            attributes[names.get(key,key)]=value
            if key=='diffuseColor':
                attributes['metallic_color']=value
            if key=='specularAmount':
                attributes['show_specular']='true'
    if material.get('standard_material') and 'specularColor' in bindings:
        # Modo's specular amount is how much is reflected seen straight on. MoonRay's index of refraction says
        # the same thing but cannot take a map, so it is set for the most this material reflects and the
        # weight of the specular layer, which can, carries the amount as a share of that.
        most=specular_ceiling(material)
        stack=sources(material)
        principled=any(m.get('principled') for m in stack)
        if any(m.get('metallic',0)>0 for m in stack) or metal_mapped(material):
            # A metal reflects by its colour, whatever the specular amount.
            pass
        elif most<=0 and not principled:
            attributes.update(specular='0',show_specular='false')
        else:
            # Under Modo's Principled model the specular amount is a share of 8% seen straight on, as measured
            # against Modo, and it always rises toward the edge, even at none.
            straight=most*(.08 if principled else 1.0)
            rise=max(principled_rise(m) for m in stack if m.get('principled')) if principled else max(0.0,min(1.0,max(m.get('specular_fresnel',1.0) for m in stack)))
            if principled and straight<=PRINCIPLED_FITTED:
                # A weak highlight: the weight held to its amount straight on would leave it no edge.
                lobe,weight=principled_match(straight,rise)
            else:
                lobe=fresnel_match(straight,rise);weight=straight/lobe
            root=math.sqrt(lobe)
            path='/modo/fresnel/'+str(index)
            # Modo's Blinn and Ashikhmin highlights reflect less than a lobe that keeps all the light. The amount is divided
            # by the number below, so a weaker highlight is a larger one.
            strength=max(1e-6,float(material.get('_specular_strength',1.0)))
            if driven is not None:
                # The roughness is driven by an image: the strength is read for each point from what drives it, as the
                # roughness is, in place of the one worked out for the material's plain roughness.
                points=strengths(material['shading_model']);ramp='/modo/strength/%s'%index
                lines += ['RampMap(%s) {'%string(ramp),'  ["ramp_type"] = 8,','  ["input"] = %s,'%driven,
                          '  ["positions"] = {%s},'%', '.join(number(a) for a,_ in points),
                          '  ["colors"] = {%s},'%', '.join('Rgb(%s, %s, %s)'%((number(most/max(1e-6,weight)/max(1e-6,k)),)*3) for _,k in points),
                          '  ["interpolations"] = {%s},'%', '.join('1' for _ in points),'}']
                lines.append('ModoTextureMap(%s) { ["background"] = %s, ["foreground"] = bind(RampMap(%s), Rgb(1, 1, 1)), ["blend"] = 5 }'%(string(path),bindings['specularColor'],string(ramp)))
            elif principled and straight<=PRINCIPLED_FITTED and (most<=0 or not (mapped(material,'specCol') or mapped(material,'specAmt'))):
                # A Principled highlight no image drives: the fitted weight, whatever the amount (its edge is there at none).
                path=None
            else:
                lines.append('ModoTextureMap(%s) { ["background"] = %s, ["foreground"] = Rgb(%s, %s, %s), ["blend"] = 5 }'%((string(path),bindings['specularColor'])+(number(most/max(1e-6,weight)/strength),)*3))
            attributes.update(refractive_index=number((1+root)/(1-root)),show_specular='true',
                              specular=number(min(1.0,weight/strength)) if path is None else 'bind(ModoTextureMap(%s), 1)'%string(path))
    from .working_space import surface as working_surface
    attributes=working_surface(attributes,'/modo/material/'+str(index),lines,{'albedo','metallic_color','scattering_color','transmission_color','emission','clearcoat_attenuation_color'})
    lines.append('materials[%s] = DwaBaseMaterial("/modo/material/%s") {' % (string(tag),index))
    lines.extend('  [%s] = %s,' % (string(k),v) for k,v in attributes.items())
    lines.append('}')

    amount = max(0,min(1,material.get('subsurface_amount',0)))
    if (sss_weight or 0 < amount < 1) and material.get('subsurface_distance',0)>0:
        surface_name = '/modo/material/%s/surface' % index
        surface = dict(attributes, scattering_radius='0')
        lines.append('DwaBaseMaterial(%s) {' % string(surface_name))
        lines.extend('  [%s] = %s,' % (string(k),v) for k,v in surface.items())
        lines.append('}')
        lines.append('materials[%s] = DwaLayerMaterial(%s) { ["material_A"] = materials[%s], ["material_B"] = DwaBaseMaterial(%s), ["mask"] = %s }' %
                     (string(tag),string('/modo/material/%s/sss_mix'%index),string(tag),string(surface_name),sss_weight or number(amount)))


def emit_stack(stack, tag, index, lines, library=None, native_index=None):
    from .rdla import string, number
    from .graph import bindings
    from .material_groups import supported, merged
    # A material that cannot be blended with others (hair, a volume's surface) covers what lies under it when it is
    # there in full, as an upper material does in the Shader Tree: what is under it is left out.
    from .shader_library import compatible as blendable, catalog as shader_catalog
    for position in range(len(stack)-1,0,-1):
        upper=stack[position]
        if (upper.get('native_shader') in shader_catalog() and not blendable(upper['native_shader'],'INTERFACE_DWABASELAYERABLE')
                and upper.get('layer_opacity',1)==1 and not upper.get('layers') and all(g.get('opacity',1)==1 for g in upper.get('material_groups',[]))):
            stack=stack[position:];break
    if supported(stack):
        material=merged(stack)
        maps=bindings(material,index,lines)
        emit(material,tag,index,maps,lines)
        return
    from .compositing import Groups
    scopes_list=[g for material in stack for g in material.get('material_groups',[])]
    if any(g.get('blend','normal')!='normal' or g.get('invert') for g in scopes_list):
        raise ValueError('Native BSDF groups support Normal blending without inversion; arithmetic material groups require explicit graph nodes')
    if any(m.get('layer_blend','normal')!='normal' or m.get('layer_invert') for m in stack):
        raise ValueError('Native BSDF material layers require Normal blending without inversion')
    serial=[0]
    def mix(background,foreground,opacity,mask):
        opacity=float(opacity)
        if not math.isfinite(opacity) or not 0<=opacity<=1:raise ValueError('Material opacity must be between zero and one')
        if opacity==0:return background
        if opacity==1 and mask is None:return foreground
        name='/modo/layers/%s/%s'%(index,serial[0]);serial[0]+=1
        weight=mask.rsplit(', ',1)[0]+', '+number(opacity)+')' if mask else number(opacity)
        ref='DwaLayerMaterial(%s)'%string(name)
        lines.append('%s { ["material_A"] = %s, ["material_B"] = %s, ["mask"] = %s }'%(ref,foreground,background,weight))
        return ref
    default='/modo/stackDefault/'+str(index)
    emit({'color':[.5]*3},default,'stack-default-'+str(index),{},lines)
    pending_masks={}
    def bare(value):
        return value.rsplit(', ',1)[0]+')' if value else None
    def scalar(value):
        return value[:-1]+', 1)' if value else None
    def scoped_mix(background,foreground,group,mask,effect):
        external=pending_masks.get(group['id'])
        if external:
            if mask:
                name='/modo/layers/%s/mask/%s'%(index,serial[0]);serial[0]+=1
                lines.append('ModoTextureMap(%s) { ["background"] = %s, ["foreground"] = %s, ["blend"] = 1 }'%(
                    string(name),bare(mask)[:-1]+', Rgb(1, 1, 1))',external[:-1]+', Rgb(1, 1, 1))'))
                mask='bind(ModoTextureMap(%s), 1)'%string(name)
            else:mask=scalar(external)
        return mix(background,foreground,group.get('opacity',1),mask)
    scopes=Groups({'surface':'materials[%s]'%string(default),'groupMask':None},mix,scoped_mix)
    for i,material in enumerate(stack):
        if i>=1000:raise ValueError('Material stack exceeds 1000 layers')
        scopes.select(material.get('material_groups',[]))
        key='/modo/internal/%s/%s'%(index,i)
        identity=1000000+index*1000+i
        maps=bindings(dict(material,shader='DwaBaseMaterial'),identity,lines,separate_masks=True,
                      mask_state=pending_masks,group_mask=bare(scopes.current['groupMask']))
        row_mask=maps.pop('_rowMask',None)
        group_mask=maps.pop('layerMask',None)
        if group_mask:
            scopes.current['groupMask']=group_mask;scopes.used.add('groupMask')
        if material.get('native_shader'):
            from .shader_library import emit as native_emit,compatible
            layered=len(stack)>1 or row_mask or group_mask or pending_masks or material.get('layer_opacity',1)!=1 or any(g.get('opacity',1)!=1 for g in material.get('material_groups',[]))
            if layered and not compatible(material['native_shader'],'INTERFACE_DWABASELAYERABLE'):
                raise ValueError(material['native_shader']+' cannot be mixed in a Dwa Shader Tree stack; assign it separately')
            if material.get('node_graph'):
                from .nodes import emit as native_emit
            ref=native_emit(material,'/modo/native/stack/%s'%identity,native_index or [1000000000+identity],lines,library or {})
            lines.append('materials[%s] = %s'%(string(key),ref))
        else:
            emit(material,key,identity,maps,lines)
        scopes.current['surface']=mix(scopes.current['surface'],'materials[%s]'%string(key),material.get('layer_opacity',1),row_mask)
        scopes.used.add('surface')
    value,used=scopes.finish()
    # Ungrouped masks control the complete root stack.
    if 'groupMask' in used:
        value['surface']=mix('materials[%s]'%string(default),value['surface'],1,value['groupMask'])
    lines.append('materials[%s] = %s'%(string(tag),value['surface']))
