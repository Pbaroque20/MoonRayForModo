"""Linear beauty-only denoising; raw EXR/AOVs never enter a destructive operation."""
from pathlib import Path
ENGINES=('off','optix','oidn_cpu')
SMART=('off','draft','medium','fine')
# How much of the fine detail a denoiser smooths away is put back: hair, fur and other things a pixel or so wide.
# Where the denoiser's guides (the albedo and the normals, which are clean) change from one pixel to the next, the
# picture as it was rendered is let through, by this much for a guide that changes all the way.
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
    # One or the other: a scene saved with both has Smart Render.
    if result['smart']!='off' and result['safe'] is True:result['safe']=False
    if result['engine'] not in ENGINES or type(result['preview']) is not bool or type(result['final']) is not bool or type(result['safe']) is not bool:
        raise ValueError('Invalid denoising settings')
    return result

def enabled(snapshot,final=False,linear=False):
    if snapshot.get('_ipr') and not final:return False
    value=settings(snapshot.get('denoising',{}))
    return value['engine']!='off' and value['final' if final else 'preview'] and not linear and (final or snapshot.get('preview_buffer','beauty')=='beauty')

def guides_required(snapshot,final=False,linear=False):
    if snapshot.get('_ipr') and not final:return False
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
    if gain<=0:
        return steps+[(oiio,['--no-autopremult',str(filtered),'--ch','R,G,B','-d','float','-o',str(output)],output)]
    # Where the fine detail is: how far each guide stands from itself blurred, the greater of the two, a little
    # soft at its edges. A hair over a surface turns the normal there and, where it is another colour, the albedo.
    mask=base.with_suffix('.denoise-detail.exr')
    def fine(guide,weight):
        return [str(guide),'--chnames','R,G,B','--dup','--blur','7x7','--absdiff','--chsum:weight=%g,%g,%g'%(weight,weight,weight)]
    steps.append((oiio,fine(guides['albedo'],2.0)+fine(guides['normal'],.6667)+['--max','--mulc',str(gain),'--blur','3x3','--mulc','1.5',
                       '--clamp:min=0:max=1','--ch','0,0,0','--chnames','R,G,B','-d','float','-o',str(mask)],mask))
    # The denoised picture, and over it the rendered one by as much as the mask says.
    steps.append((oiio,['--no-autopremult',str(rgba),'--ch','R,G,B',str(filtered),'--ch','R,G,B','--sub',str(mask),'--mul',
                       str(filtered),'--ch','R,G,B','--add','-d','float','-o',str(output)],output))
    return steps
