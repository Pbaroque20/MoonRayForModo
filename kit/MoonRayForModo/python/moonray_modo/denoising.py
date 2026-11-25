"""Linear beauty-only denoising; raw EXR/AOVs never enter a destructive operation."""
import re
from pathlib import Path
ENGINES=('off','optix','oidn_cpu')
SMART=('off','draft','medium','fine')
# How much of the fine detail a denoiser smooths away is put back: fur, hair and curves, a pixel or so wide. They are
# denoised with the rest, and where the render's matte of them says they are, this share of the picture as it was
# rendered goes back over the denoised one, for a pixel they cover whole. All of it (as until 0.5.4.1) left the fur as
# grainy as the render: a furry ball at 4 samples, 20.8 8-bit steps from a 256-sample render in the fur, as the render
# itself. A quarter: 13.6, its strands as sharp as the reference's (the denoiser alone: 12.9, a little softer). Half:
# 15.2, sharper than the reference, some grain.
DETAIL={'off':0.0,'some':.25,'more':.5}
# Keep Metallic Flakes: the light glitter's flakes reflect (their own buffer, the render's light path expression
# FLAKES_LPE) is taken out of the picture before it is denoised, and put back after it, half of it as rendered and half
# denoised on its own. Flakes a pixel or smaller (metallic paint seen from a car's length or more) sparkle at random from
# sample to sample, and a denoiser smooths them to a milky sheen, the paint plastic. A painted ball whose flakes are
# about a third of a pixel, at 4 samples against 144 (8-bit steps; spread: how far each 4x4 block's sparkle is from
# the reference's): Open Image Denoise 15.6 -> 13.9, spread 8.5 -> 3.7, sparkle kept 0.58 -> 0.93 of the reference's;
# OptiX 14.6 -> 13.5, spread 6.2 -> 3.6. All of it as rendered brought the noise back (19.5, as the render itself);
# none of it, the plastic look (16.0). Off by default: flakes several pixels wide the denoiser keeps by itself, and the
# split costs Open Image Denoise there (5.1 -> 6.1).
FLAKES_KEPT=.5
FLAKES_LPE="C<R.'glitter'>.*[<L.>O]"
def settings(value):
    # safe: MoonRay saves its picture every few seconds as it renders, so that a render stopped by hand is kept and
    # denoised as a finished one is.
    # smart: a MoonRay render is stopped once its picture is clean enough for the denoiser (smart_render.py); 'off',
    # or how clean is clean enough.
    result={'engine':value.get('engine','off'),'preview':value.get('preview',True),'final':value.get('final',True),'safe':value.get('safe',False),
            'smart':value.get('smart','off'),'detail':value.get('detail','some'),'flakes':value.get('flakes',False)}
    if result['detail'] not in DETAIL or type(result['flakes']) is not bool:raise ValueError('Invalid denoising settings')
    if result['smart'] not in SMART:raise ValueError('Invalid denoising settings')
    # Smart Render stops a render for the denoiser to finish: with the Denoiser Off it is off too, its control greyed,
    # rather than stop a render early and leave it noisy.
    if result['engine']=='off':result['smart']='off'
    # One or the other: a scene saved with both has Smart Render.
    if result['smart']!='off' and result['safe'] is True:result['safe']=False
    if result['engine'] not in ENGINES or type(result['preview']) is not bool or type(result['final']) is not bool or type(result['safe']) is not bool:
        raise ValueError('Invalid denoising settings')
    return result

def enabled(snapshot,final=False,linear=False):
    if snapshot.get('_ipr') and not final:return False
    # MoonRay's realtime under XPU2 is not denoised (its denoised pictures looked bad), and has no guides for it.
    if snapshot.get('_realtime') and not final:
        try:
            from . import native
            if native.xpu2():return False
        except Exception:pass
    value=settings(snapshot.get('denoising',{}))
    return value['engine']!='off' and value['final' if final else 'preview'] and not linear and (final or snapshot.get('preview_buffer','beauty')=='beauty')

def guides_required(snapshot,final=False,linear=False):
    if snapshot.get('_ipr') and not final:return False
    # MoonRay's realtime under XPU2 has no denoised beauty (panel), and no longer a picture from a quarter of its pixels
    # to denoise and upscale while things move (Lower Resolution While Moving, removed 2026-10-30): no guides.
    if snapshot.get('_realtime') and not final:
        try:
            from . import native
            if native.xpu2():return False
        except Exception:pass
    return enabled(snapshot,final,linear) or (not final and not linear)

def glittering(materials):
    """Whether any of these materials (a scene's, or its MoonRay material library) shows glitter: a material, a node of
    its graph or a layer of its stack."""
    from .reference_points import GLITTERING
    def shows(material,depth=0):
        if not isinstance(material,dict) or depth>16:return False
        if material.get('native_shader') in GLITTERING and (material.get('native_parameters') or {}).get('show_glitter'):return True
        graph=material.get('node_graph') or {}
        if any(isinstance(node,dict) and node.get('type') in GLITTERING and (node.get('parameters') or {}).get('show_glitter')
               for node in (graph.get('nodes') or {}).values()):return True
        return any(shows(layer,depth+1) for layer in (material.get('material_stack') or [])+(material.get('native_dependencies') or []) if layer is not material)
    return any(shows(material) for material in (materials or {}).values())

def keeps_flakes(snapshot):
    """Keep Metallic Flakes is on and the scene has glitter for it to keep."""
    try:on=settings(snapshot.get('denoising',{}))['flakes']
    except ValueError:return False
    return on and (glittering(snapshot.get('materials')) or glittering(snapshot.get('native_materials')))

# How often a safe render saves its picture, in minutes, and what a saved picture is called beside the file it is of.
SAFE_MINUTES=.05
def safe_minutes(files,width,height):
    """How often MoonRay is to save a safe render, in minutes. MoonRay stops rendering while it saves, and a save
    takes about a quarter of a second for each file and million pixels: every three seconds where that is little,
    and otherwise seldom enough that saving takes about a sixth of the time, up to every two minutes."""
    return max(SAFE_MINUTES,min(2.0,.25*files*width*height/1e6*5/60))
def one_or_other(stored,changed):
    """Safe Denoising and Smart Render are one or the other: a render that stops by itself once it is clean has no
    use for being saved as it goes. stored is a scene's denoising settings, changed whichever of 'safe' and 'smart'
    has just been set: switched on, it switches the other off."""
    if changed=='smart' and stored.get('smart','off')!='off':stored['safe']=False
    elif changed=='safe' and stored.get('safe'):stored['smart']='off'
    return stored
def safe_name(path):return str(path)+'.safe.exr'

def beside(path,word):
    """A file made of the render saved at path, named for what it is. A frame's number stays last, for a sequence to read
    as one in other programs: frame.0001.exr has frame.denoised.0001.exr, and a still shot.exr has shot.denoised.exr."""
    path=Path(path);frame=re.fullmatch(r'(.+)\.(-?\d+)',path.stem)
    return path.with_name('%s.%s.%s.exr'%(frame.group(1),word,frame.group(2)) if frame else '%s.%s.exr'%(path.stem,word))

def sidecar(path):
    return beside(path,'denoised')

def held_sidecar(path):
    """The denoised copy a render already has: under its name, or the one frames had until 0.5.2, frame.0001.denoised.exr,
    so that a sequence begun then can be resumed. Its name where it has none yet."""
    path=Path(path);named=sidecar(path);older=path.with_name(path.stem+'.denoised.exr')
    return older if not named.exists() and older.exists() else named

def jobs(runtime,source,base,engine,guides,detail='some',alpha=False):
    """The steps of denoising a picture. alpha: the source has its alpha, which the result is given (the denoiser takes
    colour alone, and a denoised frame came out with no alpha where the render had one)."""
    steps=denoised_steps(runtime,source,base,engine,guides,detail)
    if not alpha:return steps
    done=steps[-1][2];whole=Path(base).with_suffix('.denoised-alpha.exr')
    return steps+[(Path(runtime)/'oiiotool.exe',['--no-autopremult',str(done),'--ch','R,G,B',str(source),'--ch','A','--chappend','-d','float','-o',str(whole)],whole)]

def denoised_steps(runtime,source,base,engine,guides,detail='some'):
    runtime=Path(runtime);base=Path(base)
    if engine not in ENGINES[1:]: raise ValueError('Choose a denoising engine')
    denoiser=runtime/'denoise.exe';oiio=runtime/'oiiotool.exe'
    if not denoiser.is_file() or not oiio.is_file(): raise ValueError('This runtime does not include the denoising tools')
    rgba=base.with_suffix('.denoise-input.exr');filtered=base.with_suffix('.denoise-filtered.exr');output=base.with_suffix('.denoised.exr')
    # Isolate four known channels: native denoiser must never receive a multi-AOV EXR. The Cryptomatte's header entries
    # go with its channels: a denoised picture that kept them (and its manifest) had Photoshop offer 1,530 mattes it
    # does not hold.
    steps=[(oiio,['--no-autopremult',str(source),'--ch','R,G,B,A=1','--eraseattrib','cryptomatte/.*',
                  '--eraseattrib','MoonRayForModo/cryptomatteCategory','-d','float','-o',str(rgba)],rgba)]
    def denoise(picture,result):
        return (denoiser,['-in',str(picture),'-albedo',guides['albedo'],'-normals',guides['normal'],'-mode',engine,'-out',str(result)],result)
    steps+=flake_steps(oiio,rgba,base,guides['flakes'],denoise,filtered) if guides.get('flakes') else [denoise(rgba,filtered)]
    gain=DETAIL.get(detail,0.0)
    # Only where the render made the matte of fur, hair and curves. The guides' own fine detail (each guide against
    # itself blurred) is not used: on a textured or bumpy surface they change at every pixel, and letting the render
    # through there brought its noise back (a scaled dragon at 16 samples: 3.50 to 4.52 in 8-bit steps from the clean
    # picture, against the denoiser alone).
    if gain<=0 or not guides.get('fine'):
        return steps+[(oiio,['--no-autopremult',str(filtered),'--ch','R,G,B','-d','float','-o',str(output)],output)]
    # How much of each pixel is fibres (the matte, full from two thirds of a pixel), by the share of the render put back
    # there: the fibres are denoised as the surface under them is, with a little of their rendered grain over them.
    mask=base.with_suffix('.denoise-detail.exr')
    steps.append((oiio,[str(guides['fine']),'--ch','0,0,0','--chnames','R,G,B','--mulc',str(1.5*gain),
                       '--clamp:min=0:max=%s'%gain,'-d','float','-o',str(mask)],mask))
    # The denoised picture, and over it the rendered one by as much as the mask says.
    steps.append((oiio,['--no-autopremult',str(rgba),'--ch','R,G,B',str(filtered),'--ch','R,G,B','--sub',str(mask),'--mul',
                       str(filtered),'--ch','R,G,B','--add','-d','float','-o',str(output)],output))
    return steps

def flake_steps(oiio,rgba,base,flakes,denoise,filtered):
    """Keep Metallic Flakes: the picture without its flakes' light (the flakes guide) denoised, that light denoised on
    its own, and the two added up into filtered, FLAKES_KEPT of the light as rendered in place of as much of its
    denoised copy. denoise(picture, result) is the denoiser's step."""
    light=base.with_suffix('.denoise-flakes-light.exr');rest=base.with_suffix('.denoise-without-flakes.exr')
    rest_done=base.with_suffix('.denoise-without-flakes-done.exr');light_done=base.with_suffix('.denoise-flakes-light-done.exr')
    kept=FLAKES_KEPT
    return [(oiio,['--no-autopremult',str(flakes),'--ch','0,1,2,A=1','--chnames','R,G,B,A','-d','float','-o',str(light)],light),
            (oiio,['--no-autopremult',str(rgba),'--ch','R,G,B',str(light),'--ch','R,G,B','--sub','--ch','R,G,B,A=1','-d','float','-o',str(rest)],rest),
            denoise(rest,rest_done),denoise(light,light_done),
            (oiio,['--no-autopremult',str(rest_done),'--ch','R,G,B',str(light),'--ch','R,G,B','--mulc',str(kept),'--add',
                   str(light_done),'--ch','R,G,B','--mulc',str(1-kept),'--add','--ch','R,G,B,A=1','-d','float','-o',str(filtered)],filtered)]
