"""Linear beauty-only denoising; raw EXR/AOVs never enter a destructive operation."""
from pathlib import Path
ENGINES=('off','optix','oidn_cpu')
SMART=('off','draft','medium','fine')
# How much of the fine detail a denoiser smooths away is put back: fur, hair and curves, a pixel or so wide. Where the
# render's matte of them says they are, the picture as it was rendered is let through, by this much for a pixel they
# cover whole.
DETAIL={'off':0.0,'some':1.0,'more':2.0}
def settings(value):
    # safe: MoonRay saves its picture every few seconds as it renders, so that a render stopped by hand is kept and
    # denoised as a finished one is.
    # smart: a MoonRay render is stopped once its picture is clean enough for the denoiser (smart_render.py); 'off',
    # or how clean is clean enough.
    result={'engine':value.get('engine','off'),'preview':value.get('preview',True),'final':value.get('final',True),'safe':value.get('safe',False),
            'smart':value.get('smart','off'),'detail':value.get('detail','some')}
    if result['detail'] not in DETAIL:raise ValueError('Invalid denoising settings')
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
    # MoonRay's realtime under XPU2 has no denoised beauty (panel): its guides only for Lower Resolution While Moving,
    # whose pictures from a quarter of their pixels XPU2 denoises and upscales while the view or the scene moves.
    if snapshot.get('_realtime') and not final:
        try:
            from . import native
            if native.xpu2():return bool(native.xpu2_upscale())
        except Exception:pass
    return enabled(snapshot,final,linear) or (not final and not linear)

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

def sidecar(path):
    path=Path(path);return path.with_name(path.stem+'.denoised.exr')

def jobs(runtime,source,base,engine,guides,detail='some'):
    runtime=Path(runtime);base=Path(base)
    if engine not in ENGINES[1:]: raise ValueError('Choose a denoising engine')
    denoiser=runtime/'denoise.exe';oiio=runtime/'oiiotool.exe'
    if not denoiser.is_file() or not oiio.is_file(): raise ValueError('This runtime does not include the denoising tools')
    rgba=base.with_suffix('.denoise-input.exr');filtered=base.with_suffix('.denoise-filtered.exr');output=base.with_suffix('.denoised.exr')
    # Isolate four known channels: native denoiser must never receive a multi-AOV EXR.
    steps=[(oiio,['--no-autopremult',str(source),'--ch','R,G,B,A=1','-d','float','-o',str(rgba)],rgba),
        (denoiser,['-in',str(rgba),'-albedo',guides['albedo'],'-normals',guides['normal'],'-mode',engine,'-out',str(filtered)],filtered)]
    gain=DETAIL.get(detail,0.0)
    # Only where the render made the matte of fur, hair and curves. The guides' own fine detail (each guide against
    # itself blurred) is not used: on a textured or bumpy surface they change at every pixel, and letting the render
    # through there brought its noise back (a scaled dragon at 16 samples: 3.50 to 4.52 in 8-bit steps from the clean
    # picture, against the denoiser alone).
    if gain<=0 or not guides.get('fine'):
        return steps+[(oiio,['--no-autopremult',str(filtered),'--ch','R,G,B','-d','float','-o',str(output)],output)]
    # How much of each pixel is fibres: the surface under them is the denoised one and the fibres are the rendered
    # ones, laid over it.
    mask=base.with_suffix('.denoise-detail.exr')
    steps.append((oiio,[str(guides['fine']),'--ch','0,0,0','--chnames','R,G,B','--mulc',str(1.5*gain),
                       '--clamp:min=0:max=1','-d','float','-o',str(mask)],mask))
    # The denoised picture, and over it the rendered one by as much as the mask says.
    steps.append((oiio,['--no-autopremult',str(rgba),'--ch','R,G,B',str(filtered),'--ch','R,G,B','--sub',str(mask),'--mul',
                       str(filtered),'--ch','R,G,B','--add','-d','float','-o',str(output)],output))
    return steps
