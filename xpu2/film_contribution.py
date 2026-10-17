"""Connect supported live contribution inputs/results to native film processing."""
from xpu2.profile_patch import replace

def sampler(text):
    call="""            integrateBsdfSample(bSampler, lobeIndex,
                    lSampler, pv.pathThroughput, lCo, bsmp[s]);"""
    block=r"""
            const uniform int filmMode=xpu2FilmMode();
            if(!filmMode) {
                integrateBsdfSample(bSampler,lobeIndex,lSampler,pv.pathThroughput,lCo,bsmp[s]);
            } else {
                uniform float filmIn[8*24],filmRef[8*8],filmOut[8*8];
                uniform int filmMask=0;
                foreach_active(lane) {
                    uniform int b=lane*24;
                    for(uniform int j=0;j<24;++j)filmIn[b+j]=0.f;
                    filmIn[b]=extract((float)BsdfSampler_getLobeSampleCount(&bSampler,lobeIndex),lane);
                    filmIn[b+1]=extract((float)LightSetSampler_getLightSampleCount(&lSampler),lane);
                    filmIn[b+2]=extract(BsdfSampler_getDoIndirect(&bSampler),lane)?1.f:0.f;
                    filmIn[b+3]=extract(BsdfLobe_matchesFlags(BsdfSampler_getLobe(&bSampler,lobeIndex),BSDF_LOBE_TYPE_ALL_MIRROR),lane)?1.f:0.f;
                    filmIn[b+4]=extract(lCo.isInvalid,lane)?1.f:0.f;
                    if(!extract(lCo.isInvalid,lane)) {
                        filmIn[b+5]=extract(lCo.distance,lane);filmIn[b+6]=extract(lCo.pdf,lane);
                        filmIn[b+14]=extract(lCo.Li.r,lane);filmIn[b+15]=extract(lCo.Li.g,lane);filmIn[b+16]=extract(lCo.Li.b,lane);
                    }
                    filmIn[b+7]=extract(bsmp[s].pdf,lane);
                    filmIn[b+8]=extract(pv.pathThroughput.r,lane);filmIn[b+9]=extract(pv.pathThroughput.g,lane);filmIn[b+10]=extract(pv.pathThroughput.b,lane);
                    filmIn[b+11]=extract(bsmp[s].f.r,lane);filmIn[b+12]=extract(bsmp[s].f.g,lane);filmIn[b+13]=extract(bsmp[s].f.b,lane);
                    filmMask |= 1<<lane;
                }
                if(filmMode<=2) {
                    integrateBsdfSample(bSampler,lobeIndex,lSampler,pv.pathThroughput,lCo,bsmp[s]);
                    foreach_active(lane) {
                        uniform int b=lane*8;
                        for(uniform int j=0;j<8;++j)filmRef[b+j]=0.f;
                        if(!extract(BsdfSample_isInvalid(&bsmp[s]),lane)) {
                        filmRef[b]=extract(bsmp[s].distance,lane);
                        filmRef[b+1]=extract(bsmp[s].tDirect.r,lane);filmRef[b+2]=extract(bsmp[s].tDirect.g,lane);filmRef[b+3]=extract(bsmp[s].tDirect.b,lane);
                        filmRef[b+4]=extract(bsmp[s].tIndirect.r,lane);filmRef[b+5]=extract(bsmp[s].tIndirect.g,lane);filmRef[b+6]=extract(bsmp[s].tIndirect.b,lane);
                        }
                    }
                }
                const uniform int accepted=xpu2FilmContribution(filmIn,filmRef,filmOut,filmMask);
                if(filmMode>2 && !(accepted&(1<<programIndex))) {
                    integrateBsdfSample(bSampler,lobeIndex,lSampler,pv.pathThroughput,lCo,bsmp[s]);
                }
                if(accepted&(1<<programIndex)) {
                    int b=programIndex*8;
                    bsmp[s].distance=filmOut[b];
                    bsmp[s].tDirect=Color_ctor(filmOut[b+1],filmOut[b+2],filmOut[b+3]);
                    bsmp[s].tIndirect=Color_ctor(filmOut[b+4],filmOut[b+5],filmOut[b+6]);
                }
            }
"""
    decl='extern "C" uniform int xpu2FilmMode();\nextern "C" uniform int xpu2FilmContribution(uniform float input[],uniform float reference[],uniform float output[],uniform int mask);\n'
    return decl+replace(text,call,block,2)
