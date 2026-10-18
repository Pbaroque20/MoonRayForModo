extern "C" uniform uint64 CPP_gpuWindowBegin(uniform PbrTLState *uniform tls);
extern "C" uniform unsigned CPP_gpuWindowSize();
extern "C" void CPP_gpuWindowEnd(uniform uint64 handle);
extern "C" void CPP_gpuWindowRecord(uniform uint64 handle,uniform unsigned block);
extern "C" void CPP_gpuWindowPublish(uniform uint64 handle);
extern "C" void CPP_gpuWindowReplay(uniform uint64 handle,uniform unsigned block);
extern "C" void CPP_gpuWindowReplayEnd();
extern "C" uniform int CPP_gpuMaterialStageMode(uniform PbrTLState *uniform tls);
uniform bool xpu2SubmitMaterial(uniform PbrTLState *uniform pbrTls,
    const varying BsdfSampler &bSampler,const varying Subpixel &sp,
    const varying PathVertex &pv,varying uint32_t sequenceID,
    uniform uint64 *uniform tokens,uniform bool *uniform prepared);
// Restrict speculation to full primary SIMD blocks without mutable volume/SSS paths.
void xpu2WindowPrepare(const uniform PathIntegrator *uniform integrator,
    uniform PbrTLState *uniform tls,const varying RayState &rs,
    const varying Intersection &isect,const varying Bsdf &bsdf,varying float presence){
    if(!CPP_gpuMaterialStageMode(tls) || !all(rs.mPathVertex.nonMirrorDepth==0) ||
       !all(rs.mRay.ext.depth==0) || any(rs.mVolHit) || !all(presence==1.f) ||
       bsdf.mEarlyTerminationMask || Bsdf_hasSubsurface(&bsdf) || Bsdf_getLobeCount(&bsdf)==0)return;
    varying BsdfSlice slice;
    BsdfSlice_init(&slice,getNg(isect),rs.mRay.dir*-1.f,BSDF_LOBE_TYPE_ALL,
        true,isEntering(isect),tls->mFs->mShadowTerminatorFix);
    const varying PathVertex &pv=rs.mPathVertex;
    varying bool indirect=integrator->mBsdfSamples>0 && rs.mRay.ext.depth<integrator->mMaxDepth &&
        (pv.diffuseDepth<integrator->mMaxDiffuseDepth || pv.glossyDepth<integrator->mMaxGlossyDepth ||
         pv.mirrorDepth<integrator->mMaxMirrorDepth || pv.hairDepth<integrator->mMaxHairDepth);
    uniform uint8_t *uniform bookmark=Arena_getPtr(tls->mArena);
    varying BsdfSampler sampler;
    BsdfSampler_init(&sampler,tls->mArena,bsdf,slice,integrator->mBsdfSamples,indirect);
    uniform uint64 tokens[BSDF_MAX_LOBE*16];uniform bool prepared[BSDF_MAX_LOBE];
    xpu2SubmitMaterial(tls,sampler,rs.mSubpixel,pv,rs.mSequenceID,tokens,prepared);
    Arena_setPtr(tls->mArena,bookmark);
}
