"""Preview-only quality limits; never mutate scene-owned/final settings."""
from . import options

# The material widget's Samples choice: the most samples a pixel, and the noise it stops at (lower is cleaner, and slower),
# for a picture from Refresh and, held lighter to keep up with values being dragged, under Live. A pixel stops at its
# noise whatever it may still take, so each step asks for less noise as well as more samples.
WIDGET_SAMPLES=(('standard','64 samples',(64,5.0),(4,50.0)),
                ('high','256 samples',(256,2.0),(16,20.0)))


def widget_samples(choice,live=False):
    """(most samples a pixel, noise) for the widget's choice; Standard for one no longer known."""
    row=next((r for r in WIDGET_SAMPLES if r[0]==choice),WIDGET_SAMPLES[0])
    return row[3] if live else row[2]


def prepare(scene, width, height, sample_grid, width_cap=160, sample_cap=1, error=100.0, sampling='adaptive'):
    """MoonRay LS's scene: adaptive, from 2 samples a pixel up to its cap, stopping where a pixel is clean enough; or,
    with sampling 'uniform', the same samples in every pixel, MoonRay's square grid of no more than the cap
    (kept as '_uniform_grid', for the render to be given)."""
    if width_cap not in (80,160,240,320,640,960,1280) or sample_cap not in (1,4,16,32,64,128,256):
        raise ValueError('Invalid IPR quality preset')
    if sampling not in ('adaptive','uniform'):
        raise ValueError('MoonRay LS sampling is adaptive or uniform')
    if not 0.1<=float(error)<=1000:
        raise ValueError('IPR adaptive error must be between 0.1 and 1000')
    settings=options.render_values(scene.get('render_settings',{}))
    original_cap=settings['max_adaptive_samples'] if settings['sampling_mode']==2 else int(sample_grid)**2
    cap=max(1,min(sample_cap,original_cap))
    # MoonRay clamps adaptive sampling to >=2 internally. Uniform grid 1 is
    # required for a genuine single-sample preview.
    settings.update(sampling_mode=0 if cap==1 else 2,min_adaptive_samples=1 if cap==1 else 2,
                    max_adaptive_samples=cap,
                    target_adaptive_error=max(float(error),settings['target_adaptive_error']),
                    light_samples=1,bsdf_samples=1,bssrdf_samples=1)
    result=dict(scene,render_settings=settings,_ipr=True)
    if sampling=='uniform' and cap>1:
        settings.update(sampling_mode=0,min_adaptive_samples=1)
        result['_uniform_grid']=max(1,int(cap**.5))
    result.pop('_denoise_guides',None)
    # A quick look is the beauty and nothing else: no other buffer is rendered or kept for it.
    result['preview_buffer']='beauty';result['aovs']=['alpha'];result['custom_aovs']=[]
    # Cap both scene and normal preview width, so IPR never enlarges either.
    scale=min(1.0,float(width_cap)/max(1,width),float(scene['width'])/max(1,width))
    return result,max(16,round(width*scale)),max(16,round(height*scale))


def refine(scene):
    """Optional idle quality pass; keep scene-owned settings and dimensions intact."""
    if not scene.get('_ipr'):raise ValueError('Idle refinement requires an IPR snapshot')
    settings=dict(scene['render_settings'],sampling_mode=0,min_adaptive_samples=1,max_adaptive_samples=16)
    return dict(scene,render_settings=settings,_ipr_refined=True)
