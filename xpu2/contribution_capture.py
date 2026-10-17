"""Capture a restricted native numeric contribution stage, never native pointers."""
from xpu2.profile_patch import replace


def sampler(text):
    call = """            integrateBsdfSample(bSampler, lobeIndex,
                    lSampler, pv.pathThroughput, lCo, bsmp[s]);"""
    before = r"""
            uniform float ownedIn[8*24];
            uniform uint32_t ownedIds[8*8];
            uniform int ownedMask=0;
            if(xpu2ContributionCaptureEnabled()) {
                foreach_active(lane) {
                    uniform uint32_t pixel=extract(sp.mPixel,lane);
                    if((pixel==((77<<16)|96) || pixel==((96<<16)|132)) && extract(sp.mSubpixelIndex,lane)==0) {
                        uniform int b=lane*24;
                        for(uniform int j=0;j<24;++j)ownedIn[b+j]=0.f;
                        ownedIn[b]=extract((float)BsdfSampler_getLobeSampleCount(&bSampler,lobeIndex),lane);
                        ownedIn[b+1]=extract((float)LightSetSampler_getLightSampleCount(&lSampler),lane);
                        ownedIn[b+2]=extract(BsdfSampler_getDoIndirect(&bSampler),lane)?1.f:0.f;
                        ownedIn[b+3]=extract(BsdfLobe_matchesFlags(BsdfSampler_getLobe(&bSampler,lobeIndex),BSDF_LOBE_TYPE_ALL_MIRROR),lane)?1.f:0.f;
                        ownedIn[b+4]=extract(lCo.isInvalid,lane)?1.f:0.f;
                        if(!extract(lCo.isInvalid,lane)) {
                            ownedIn[b+5]=extract(lCo.distance,lane);ownedIn[b+6]=extract(lCo.pdf,lane);
                            ownedIn[b+14]=extract(lCo.Li.r,lane);ownedIn[b+15]=extract(lCo.Li.g,lane);ownedIn[b+16]=extract(lCo.Li.b,lane);
                        }
                        ownedIn[b+7]=extract(bsmp[s].pdf,lane);
                        ownedIn[b+8]=extract(pv.pathThroughput.r,lane);ownedIn[b+9]=extract(pv.pathThroughput.g,lane);ownedIn[b+10]=extract(pv.pathThroughput.b,lane);
                        ownedIn[b+11]=extract(bsmp[s].f.r,lane);ownedIn[b+12]=extract(bsmp[s].f.g,lane);ownedIn[b+13]=extract(bsmp[s].f.b,lane);
                        uniform int m=lane*8;
                        ownedIds[m]=pixel;ownedIds[m+1]=extract(sp.mSubpixelIndex,lane);ownedIds[m+2]=extract(sequenceID,lane);
                        ownedIds[m+3]=extract(pv.nonMirrorDepth,lane);ownedIds[m+4]=lobeIndex;ownedIds[m+5]=extract(i,lane);
                        ownedIds[m+6]=lane;ownedIds[m+7]=s;ownedMask |= 1<<lane;
                    }
                }
            }
"""
    after = r"""
            if(ownedMask) {
                uniform float ownedOut[8*8];
                foreach_active(lane) {
                    if(ownedMask & (1<<lane)) {
                        if(extract(BsdfSample_isInvalid(&bsmp[s]),lane)) {ownedMask &= ~(1<<lane);}
                        else {
                            uniform int b=lane*8;
                            ownedOut[b]=extract(bsmp[s].distance,lane);
                            ownedOut[b+1]=extract(bsmp[s].tDirect.r,lane);ownedOut[b+2]=extract(bsmp[s].tDirect.g,lane);ownedOut[b+3]=extract(bsmp[s].tDirect.b,lane);
                            ownedOut[b+4]=extract(bsmp[s].tIndirect.r,lane);ownedOut[b+5]=extract(bsmp[s].tIndirect.g,lane);ownedOut[b+6]=extract(bsmp[s].tIndirect.b,lane);ownedOut[b+7]=0.f;
                        }
                    }
                }
                if(ownedMask)xpu2CaptureContribution(ownedIds,ownedIn,ownedOut,ownedMask);
            }
"""
    decl='extern "C" uniform int xpu2ContributionCaptureEnabled();\nextern "C" void xpu2CaptureContribution(uniform unsigned int ids[],uniform float input[],uniform float output[],uniform int mask);\n'
    return decl+replace(text,call,before+call+after,2)


def kernel(original):
    start=original.index('inline void\nintegrateBsdfSample(')
    end=original.index('\nstruct Scene;',start)
    body=original[start:end]
    sig=body[:body.index('\n{')]
    new='inline void integrateOwned(varying float ni, varying float nl, varying bool doIndirect, varying bool mirror, const varying Color &pathThroughput, const varying LightContribution &lCo, varying BsdfSample &bsmp)'
    body=replace(body,sig,new)
    body=replace(body,'BsdfSampler_getDoIndirect(&bSampler)','doIndirect',2)
    body=replace(body,'    const float ni = (const float)BsdfSampler_getLobeSampleCount(&bSampler, lobeIndex);','')
    body=replace(body,'            const float nl = (const float)LightSetSampler_getLightSampleCount(&lSampler);','')
    body=replace(body,'        const bool lobeIsMirror = BsdfLobe_matchesFlags(\n                BsdfSampler_getLobe(&bSampler, lobeIndex), BSDF_LOBE_TYPE_ALL_MIRROR);','        const bool lobeIsMirror = mirror;')
    wrapper=r"""
export void xpu2ResumeContribution(uniform float input[],uniform float output[],uniform int mask) {
    foreach(lane=0 ... 8) {
        if(mask & (1<<lane)) {
            int b=lane*24;
            Color throughput=Color_ctor(input[b+8],input[b+9],input[b+10]);
            LightContribution light;
            light.isInvalid=input[b+4]!=0.f;light.distance=input[b+5];light.pdf=input[b+6];
            light.Li=Color_ctor(input[b+14],input[b+15],input[b+16]);
            BsdfSample sample;
            sample.pdf=input[b+7];sample.f=Color_ctor(input[b+11],input[b+12],input[b+13]);
            sample.tDirect=sBlack;sample.tIndirect=sBlack;
            integrateOwned(input[b],input[b+1],input[b+2]!=0.f,input[b+3]!=0.f,throughput,light,sample);
            int o=lane*8;output[o]=sample.distance;
            output[o+1]=sample.tDirect.r;output[o+2]=sample.tDirect.g;output[o+3]=sample.tDirect.b;
            output[o+4]=sample.tIndirect.r;output[o+5]=sample.tIndirect.g;output[o+6]=sample.tIndirect.b;output[o+7]=0.f;
        }
    }
}
"""
    return original[:start]+body+wrapper
