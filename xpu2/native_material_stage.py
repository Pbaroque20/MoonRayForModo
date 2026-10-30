"""Split native material sample submission/resumption; isolated sources only."""
from pathlib import Path
from . import native_work as work
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=work.adapter
cpp=work.cpp
queue=work.queue
profile=work.profile
cuda=work.cuda

DECL = r"""
extern "C" uniform int CPP_gpuMaterialStageMode(uniform PbrTLState *uniform tls);
extern "C" void CPP_gpuMaterialStageBegin(const uniform uint64 *uniform tokens,uniform unsigned int count);
extern "C" void CPP_gpuMaterialStageResume(const uniform uint64 *uniform tokens,uniform unsigned int count);
uniform bool xpu2SubmitMaterial(uniform PbrTLState *uniform pbrTls,
    const varying BsdfSampler &bSampler, const varying Subpixel &sp,
    const varying PathVertex &pv,varying uint32_t sequenceID,
    uniform uint64 *uniform tokens,uniform bool *uniform prepared);
void xpu2ResumeMaterial(uniform PbrTLState *uniform pbrTls, uniform ShadingTLState *uniform shadingTls,
    const varying BsdfSampler &bSampler, const varying LightSetSampler &lSampler,
    const varying Subpixel &sp,const varying PathVertex &pv,
    const varying Vec3f &P,const varying Vec3f &cullingNormal,varying float time,
    varying uint32_t sequenceID,varying BsdfSample *uniform bsmp,uniform int clampingDepth,
    varying float clampingValue,varying Flags indirectFlags,varying float rayDirFootprint,
    const varying Rdl2LightSetList *uniform parentLobeLightSets,
    uniform uint64 *uniform tokens,uniform bool *uniform prepared);
"""

def header(text):
    text=work.header(text)
    text=once(text,'inline void earlyReset(){','inline void stageReset();inline void stageFinish();\ninline void earlyReset(){stageReset();')
    text=once(text,'inline void earlyFinish(){','inline void earlyFinish(){stageFinish();')
    return text+'\n'+(HERE/'native_material_stage.inc').read_text()

def ispc(text,bsdf_header):
    text=work.ispc(text,bsdf_header)
    start=text.index('void\ndrawBsdfSamples(')
    end=text.index('\nvoid\ndrawLightSamples(',start)
    # There are helper functions between these two. Clone only drawBsdfSamples.
    brace=text.index('{',start);depth=1;stop=brace+1
    while depth:
        depth+=(text[stop]=='{')-(text[stop]=='}');stop+=1
    draw=text[start:stop]
    a=draw.index('    uniform uint64 xpu2AheadTokens[BSDF_MAX_LOBE*16];')
    b=draw.index('    for (uniform int lobeIndex',a)
    resume=draw[:a]+draw[b:]
    resume=once(resume,'drawBsdfSamples(', 'xpu2ResumeMaterial(')
    resume=once(resume,'const varying Rdl2LightSetList * uniform parentLobeLightSets)',
        'const varying Rdl2LightSetList * uniform parentLobeLightSets, uniform uint64 *uniform xpu2AheadTokens, uniform bool *uniform xpu2AheadPrepared)')
    # Prepared tickets belong to this invocation and are consumed exactly once.
    resume=once(resume,'CPP_gpuEarlyCollect(pbrTls,xpu2Tokens[s-bSampler.mLobeToSampleIndex[lobeIndex]],xpu2Result);',
        'CPP_gpuEarlyCollect(pbrTls,xpu2Tokens[s-bSampler.mLobeToSampleIndex[lobeIndex]],xpu2Result);\n                xpu2Tokens[s-bSampler.mLobeToSampleIndex[lobeIndex]]=0;')
    submit=r"""
uniform bool xpu2SubmitMaterial(uniform PbrTLState *uniform pbrTls,
    const varying BsdfSampler &bSampler,const varying Subpixel &sp,
    const varying PathVertex &pv,varying uint32_t sequenceID,
    uniform uint64 *uniform tokens,uniform bool *uniform prepared) {
    for(uniform int k=0;k<BSDF_MAX_LOBE*16;++k)tokens[k]=0;
    for(uniform int k=0;k<BSDF_MAX_LOBE;++k)prepared[k]=false;
    if(!CPP_gpuMaterialStageMode(pbrTls) || !all(pv.nonMirrorDepth==0))return false;
    const int spIndex=0;
    varying int seed=0;
    for(uniform int k=0;k<BsdfSampler_getLobeCount(&bSampler);++k){
        const varying BsdfLobe *uniform lobe=BsdfSampler_getLobe(&bSampler,k);
        if(!isActive(lobe))continue;
        seed+=1;
        int count=BsdfSampler_getLobeSampleCount(&bSampler,k);
        SequenceID sid;SequenceID_init(sid,(uint32_t)pv.nonMirrorDepth,sp.mPixel,seed,
            (uniform uint32_t)SequenceTypeBsdf,spIndex,sequenceID);
        IntegratorSample2D sampler;IntegratorSample2D_init(sampler,sid);
        sampler.mSampleNumber=sp.mSubpixelIndex*count;
        prepared[k]=xpu2PrepareLobe(pbrTls,bSampler,sp,pv,lobe,count,sampler,&tokens[k*16]);
    }
    uniform bool anyPrepared=false;
    for(uniform int k=0;k<BSDF_MAX_LOBE;++k)anyPrepared=anyPrepared || prepared[k];
    if(anyPrepared)CPP_gpuMaterialStageBegin(tokens,BSDF_MAX_LOBE*16);
    return anyPrepared;
}
"""
    return text[:start]+DECL+submit+'\n'+resume+'\n'+text[start:]

def multisampler(text):
    # No late post-shading adapter: the early path owns the shader calculation.
    text=once(text,'#include "LightSetSampler.isph"','#include "LightSetSampler.isph"\n'+DECL)
    anchor='    const uniform int bsdfSampleCount = BsdfSampler_getSampleCount(&bSampler);'
    text=once(text,anchor,r"""
    uniform uint64 xpu2Tokens[BSDF_MAX_LOBE*16];
    uniform bool xpu2Prepared[BSDF_MAX_LOBE];
    uniform bool xpu2Staged=xpu2SubmitMaterial(pbrTls,bSampler,rs->mSubpixel,pv,sequenceID,xpu2Tokens,xpu2Prepared);
    uniform bool xpu2LightFirst=xpu2Staged && CPP_gpuMaterialStageMode(pbrTls)==2;
"""+anchor)
    start=text.index('    drawBsdfSamples(pbrTls, shadingTls, bSampler, lSampler, sp, pv,')
    end=text.index('    if (doIndirect) {',start)
    # Only move the BSDF draw; AOV/RR are irrelevant under the first-bounce,
    # empty-AOV admission gate. Native publication order remains unchanged.
    finish=text.index('parentLobeLightSets);',start)+len('parentLobeLightSets);')
    call=text[start:finish]
    staged=call.replace('drawBsdfSamples(', 'xpu2ResumeMaterial(').replace('parentLobeLightSets);','parentLobeLightSets,xpu2Tokens,xpu2Prepared);')
    resume="""
        CPP_gpuMaterialStageResume(xpu2Tokens,BSDF_MAX_LOBE*16);
"""+staged
    text=text[:start]+ '    if(!xpu2LightFirst){\n        if(xpu2Staged){'+resume+'\n        }else{\n'+call+'\n        }\n    }'+text[finish:end]+'    if(xpu2LightFirst){'+resume+'\n    }\n'+text[end:]
    return text
