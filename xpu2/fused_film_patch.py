"""Opt-in single-dispatch Lambert/contribution capture; retains the old queue."""
from pathlib import Path
from xpu2.profile_patch import replace
ROOT=Path(__file__).parent


def bridge(text):
    text=(ROOT/'fused_capture.h').read_text(encoding='utf-8')+'\n'+text
    branches={
        'void xpu2BatchedBegin(int slot){':'if(fusedcapture::enabled()){fusedcapture::begin(slot);return;}',
        'void xpu2BatchedSelect(int slot){':'if(fusedcapture::enabled()){fusedcapture::select(slot);return;}',
        'void xpu2BatchedSampleEnd(){':'if(fusedcapture::enabled()){fusedcapture::slots[fusedcapture::selected].sampling=false;return;}',
        'void xpu2BatchedPublish(){':'if(fusedcapture::enabled())return;',
        'void xpu2BatchedLambert(const float* input,const float* output,const int* lanes,int count){':'if(fusedcapture::enabled()){fusedcapture::sample(input,output,lanes,count);return;}',
        'void xpu2BatchedLightBegin(){':'if(fusedcapture::enabled())return;',
        'void xpu2BatchedLightEnd(){':'if(fusedcapture::enabled())return;',
        'void xpu2BatchedCollect(float* post,int mask,int slot){':'if(fusedcapture::enabled()){fusedcapture::collect(post,mask,slot);return;}',
    }
    for anchor,branch in branches.items():text=replace(text,anchor,anchor+'\n    '+branch,1)
    return text


def sampler(text):
    decl='extern "C" uniform int xpu2FusedEnabled();\nextern "C" void xpu2FusedTake(uniform float input[],uniform float reference[],uniform int mask[],uniform int slot);\nextern "C" void xpu2FilmFusedWindow(uniform float input[],uniform float reference[],uniform float output[],uniform int masks[],uniform int accepted[],uniform int count,uniform float lambert[],uniform float native[],uniform int shaderMasks[]);\n'
    text=replace(text,'            const uniform int filmMode=xpu2FilmMode();','            const uniform int filmMode=xpu2FilmMode();\n            const uniform int filmFused=xpu2FusedEnabled();\n            uniform float filmLambert[16*8*24],filmNative[16*8*8];\n            uniform int filmShaderMasks[16];',2)
    # Only the first collect in each draw variant is in the window prepass.
    marker='            xpu2BatchedCollect(xpu2Post,xpu2Mask,slot);'
    parts=text.split(marker)
    if len(parts)!=5:raise ValueError('Collect hook drift')
    for i in (1,3):parts[i]='\n            if(filmFused)xpu2FusedTake(&filmLambert[slot*8*24],&filmNative[slot*8*8],&filmShaderMasks[slot],slot);'+parts[i]
    text=marker.join(parts)
    call='                xpu2FilmWindow(filmIn,filmRef,filmOut,filmMasks,filmAccepted,count);'
    text=replace(text,call,'                if(filmFused)xpu2FilmFusedWindow(filmIn,filmRef,filmOut,filmMasks,filmAccepted,count,filmLambert,filmNative,filmShaderMasks);\n                else '+call.strip(),2)
    return decl+text


def cuda():
    # Reuse the validated AVX-compatible sampling arithmetic, making the helper
    # address a single owned packet rather than a global output/echo array.
    text=(ROOT/'lambert_sample_cuda.cu').read_text(encoding='utf-8')
    start=text.index('    result[0]=2;');end=text.index('\n}\n',start)
    body=text[start:end].replace('lengths[id]!=96 || ','')
    helper='__device__ void filmSample(const unsigned char* src,U* result){\n'+body.replace('Vector','true')+'\n}\n'
    return '\n'.join((ROOT/name).read_text(encoding='utf-8') for name in ('sampler_cuda.cu','lambert_cuda.cu','ispc_math_cuda.cuh','lambert_sample_cuda.cu'))+'\n'+helper+'\n'+(ROOT/'fused_film_cuda.cu').read_text(encoding='utf-8')
