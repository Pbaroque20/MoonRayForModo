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
    # MoonRay's realtime under XPU2 has no denoised beauty (panel), and no longer a picture from a quarter of its pixels
    # to denoise and upscale while things move (Lower Resolution While Moving, removed 2026-10-30): no guides.
    if snapshot.get('_realtime') and not final:
        try:
            from . import native
            if native.xpu2():return False
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
    # How much of each pixel is fibres (the matte, full from two thirds of a pixel), by the share of the render put back
    # there: the fibres are denoised as the surface under them is, with a little of their rendered grain over them.
    mask=base.with_suffix('.denoise-detail.exr')
    steps.append((oiio,[str(guides['fine']),'--ch','0,0,0','--chnames','R,G,B','--mulc',str(1.5*gain),
                       '--clamp:min=0:max=%s'%gain,'-d','float','-o',str(mask)],mask))
    # The denoised picture, and over it the rendered one by as much as the mask says.
    steps.append((oiio,['--no-autopremult',str(rgba),'--ch','R,G,B',str(filtered),'--ch','R,G,B','--sub',str(mask),'--mul',
                       str(filtered),'--ch','R,G,B','--add','-d','float','-o',str(output)],output))
    return steps
