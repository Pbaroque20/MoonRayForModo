            const uniform int filmMode=xpu2FilmMode();
            uniform float filmIn[16*8*24],filmRef[16*8*8],filmOut[16*8*8];
            uniform int filmMasks[16],filmAccepted[16];
            if(filmMode) {
                // Inactive lanes are never read by either processor.
                for(uniform int j=0;j<count*8*24;++j)filmIn[j]=0.f;
                for(uniform int j=0;j<count*8*8;++j)filmRef[j]=0.f;
                for(uniform int j=0;j<16;++j){filmMasks[j]=0;filmAccepted[j]=0;}
                for(uniform int slot=0;slot<count;++slot) {
                    const varying int i=first+slot;
                    const uniform int s=base+first+slot;
                    if(i>=lobeSampleCount){continue;}
@@COLLECT@@
                    lCo=contributions[slot];
                foreach_active(lane) {
                    uniform int b=(slot*8+lane)*24;
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
                    filmMasks[slot] |= 1<<lane;
                }
                if(filmMode<=2) {
                    integrateBsdfSample(bSampler,lobeIndex,lSampler,pv.pathThroughput,lCo,bsmp[s]);
                    foreach_active(lane) {
                        uniform int b=(slot*8+lane)*8;
                        for(uniform int j=0;j<8;++j)filmRef[b+j]=0.f;
                        if(!extract(BsdfSample_isInvalid(&bsmp[s]),lane)) {
                        filmRef[b]=extract(bsmp[s].distance,lane);
                        filmRef[b+1]=extract(bsmp[s].tDirect.r,lane);filmRef[b+2]=extract(bsmp[s].tDirect.g,lane);filmRef[b+3]=extract(bsmp[s].tDirect.b,lane);
                        filmRef[b+4]=extract(bsmp[s].tIndirect.r,lane);filmRef[b+5]=extract(bsmp[s].tIndirect.g,lane);filmRef[b+6]=extract(bsmp[s].tIndirect.b,lane);
                        }
                    }
                }
                }
                // No native pointer crosses this synchronous numeric boundary.
                xpu2FilmWindow(filmIn,filmRef,filmOut,filmMasks,filmAccepted,count);
            }
