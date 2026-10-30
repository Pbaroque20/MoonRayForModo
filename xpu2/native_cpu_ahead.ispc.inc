// Precompute only CPU-owned lobes in this same native shading invocation.
// No other ray queues, arenas, film operations or native contexts are entered.
void xpu2PrepareCpuLobes(uniform PbrTLState *uniform pbrTls,
    const varying BsdfSampler &bSampler,const varying Subpixel &sp,const varying PathVertex &pv,
    varying uint32_t sequenceID,varying BsdfSample *uniform bsmp,
    const uniform bool *uniform gpuPrepared,uniform bool *uniform cpuPrepared,varying bool *uniform cpuValid) {
    varying int seed=0;
    uniform unsigned int packets=0;
    for(uniform int k=0;k<BsdfSampler_getLobeCount(&bSampler);++k){
        const varying BsdfLobe *uniform lobe=BsdfSampler_getLobe(&bSampler,k);
        if(!isActive(lobe))continue;
        seed+=1;
        if(gpuPrepared[k])continue;
        int count=BsdfSampler_getLobeSampleCount(&bSampler,k);
        SequenceID sid;SequenceID_init(sid,(uint32_t)pv.nonMirrorDepth,sp.mPixel,seed,
            (uniform uint32_t)SequenceTypeBsdf,0,sequenceID);
        IntegratorSample2D sampler;IntegratorSample2D_init(sampler,sid);
        sampler.mSampleNumber=sp.mSubpixelIndex*count;
        uniform int s=bSampler.mLobeToSampleIndex[k];
        for(int i=0;i<count;++i,++s){
            float values[2];getSample(sampler,values,pv.nonMirrorDepth,*pbrTls->mFs);
            cpuValid[s]=BsdfSampler_sample(pbrTls,&bSampler,k,values[0],values[1],bsmp[s]);
            ++packets;
        }
        cpuPrepared[k]=true;
    }
    CPP_gpuCpuAheadCount(packets,false);
}
