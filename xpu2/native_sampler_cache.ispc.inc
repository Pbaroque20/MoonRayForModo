// Numeric-only cache of the pinned native sampler initializer.
// No native arena, slice, BSDF or lobe pointer is retained.
struct Xpu2SamplerCache {
    uniform int sourceCount;
    uniform int types[BSDF_MAX_LOBE];
    uniform int masks[BSDF_MAX_LOBE];
    int maxSamples;
    BsdfLobeType flags;
    uniform int lobeCount;
    uniform int sampleCount;
    int sampleCountVarying;
    uniform uint8 indexes[BSDF_MAX_LOBE];
    uniform uint16 offsets[BSDF_MAX_LOBE];
    int counts[BSDF_MAX_LOBE];
    float inverses[BSDF_MAX_LOBE];
};
extern "C" uniform uint8 *uniform CPP_gpuSamplerRead(uniform unsigned bytes);
extern "C" uniform uint8 *uniform CPP_gpuSamplerWrite(uniform unsigned bytes);
extern "C" void CPP_gpuSamplerCommit();
extern "C" uniform bool CPP_gpuSamplerVerify();
extern "C" uniform bool CPP_gpuSamplerForceMiss();
extern "C" void CPP_gpuSamplerResult(uniform bool reused,uniform bool verified,uniform bool equal);
inline void xpu2SamplerInit(varying BsdfSampler *uniform sampler,uniform Arena *uniform arena,
    const varying Bsdf &bsdf,const varying BsdfSlice &slice,varying int maxSamples,varying bool indirect){
    // Partial native blocks must follow the original initializer.
    if(lanemask()!=((1<<VLEN)-1) || Bsdf_getLobeCount(&bsdf)>BSDF_MAX_LOBE){
        BsdfSampler_init(sampler,arena,bsdf,slice,maxSamples,indirect);return;
    }
    const uniform unsigned bytes=sizeof(varying Xpu2SamplerCache);
    varying Xpu2SamplerCache *uniform cache=(varying Xpu2SamplerCache *uniform)CPP_gpuSamplerRead(bytes);
    if(cache!=NULL){
        uniform bool same=!CPP_gpuSamplerForceMiss() && cache->sourceCount==Bsdf_getLobeCount(&bsdf) &&
            all(cache->maxSamples==maxSamples) && all(cache->flags==slice.mFlags);
        for(uniform int i=0;same && i<cache->sourceCount;++i){
            const varying BsdfLobe *uniform lobe=Bsdf_getLobe(&bsdf,i);
            uniform int type=lobe!=NULL?lobe->mType:0;
            uniform int mask=lobe!=NULL?lobe->mMask:0;
            same=cache->types[i]==type && cache->masks[i]==mask;
        }
        if(same){
            uniform bool verify=CPP_gpuSamplerVerify();
            uniform bool equal=true;
            if(verify){
                BsdfSampler_init(sampler,arena,bsdf,slice,maxSamples,indirect);
                equal=cache->lobeCount==sampler->mLobeCount && cache->sampleCount==sampler->mSampleCount && all(cache->sampleCountVarying==sampler->mSampleCountVarying);
                for(uniform int i=0;equal && i<cache->lobeCount;++i){
                    equal=cache->indexes[i]==sampler->mLobeIndex[i] && cache->offsets[i]==sampler->mLobeToSampleIndex[i] &&
                        all(cache->counts[i]==sampler->mLobeSampleCount[i]) && all(intbits(cache->inverses[i])==intbits(sampler->mInvLobeSampleCount[i]));
                }
            }else{
                sampler->mBsdf=&bsdf;sampler->mSlice=&slice;sampler->mMaxSamplesPerLobe=maxSamples;sampler->mDoIndirect=indirect;
                sampler->mLobeCount=cache->lobeCount;sampler->mSampleCount=cache->sampleCount;sampler->mSampleCountVarying=cache->sampleCountVarying;
                sampler->mLobeIndex=(uniform uint8 *uniform)Arena_allocArray(arena,cache->lobeCount,sizeof(uniform uint8));
                sampler->mLobeSampleCount=(varying int *uniform)Arena_allocArray(arena,cache->lobeCount,sizeof(varying int));
                sampler->mInvLobeSampleCount=(varying float *uniform)Arena_allocArray(arena,cache->lobeCount,sizeof(varying float));
                for(uniform int i=0;i<cache->lobeCount;++i){
                    sampler->mLobeIndex[i]=cache->indexes[i];sampler->mLobeToSampleIndex[i]=cache->offsets[i];
                    sampler->mLobeSampleCount[i]=cache->counts[i];sampler->mInvLobeSampleCount[i]=cache->inverses[i];
                }
            }
            CPP_gpuSamplerResult(true,verify,equal);return;
        }
        CPP_gpuSamplerResult(false,false,true);
    }
    BsdfSampler_init(sampler,arena,bsdf,slice,maxSamples,indirect);
    cache=(varying Xpu2SamplerCache *uniform)CPP_gpuSamplerWrite(bytes);
    if(cache==NULL)return;
    cache->sourceCount=Bsdf_getLobeCount(&bsdf);cache->maxSamples=maxSamples;cache->flags=slice.mFlags;
    for(uniform int i=0;i<cache->sourceCount;++i){
        const varying BsdfLobe *uniform lobe=Bsdf_getLobe(&bsdf,i);
        cache->types[i]=lobe!=NULL?lobe->mType:0;cache->masks[i]=lobe!=NULL?lobe->mMask:0;
    }
    cache->lobeCount=sampler->mLobeCount;cache->sampleCount=sampler->mSampleCount;cache->sampleCountVarying=sampler->mSampleCountVarying;
    for(uniform int i=0;i<cache->lobeCount;++i){
        cache->indexes[i]=sampler->mLobeIndex[i];cache->offsets[i]=sampler->mLobeToSampleIndex[i];
        cache->counts[i]=sampler->mLobeSampleCount[i];cache->inverses[i]=sampler->mInvLobeSampleCount[i];
    }
    CPP_gpuSamplerCommit();
}
