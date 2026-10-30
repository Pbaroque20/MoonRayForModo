            // Pack only the exact native Lambert subset. No lobe/scene pointer escapes.
            if (xpu2Enabled) {
                foreach_active (lane) { xpu2Payload[(s*VLEN+lane)*40+36]=0.f; }
                if (lobe->mName == BSDF_LOBE_LAMBERT && parentPv.nonMirrorDepth == 0) {
                    const varying LambertBsdfLobe *uniform lambert=(const varying LambertBsdfLobe *uniform)lobe;
                    const varying BsdfSlice &slice=*BsdfSampler_getBsdfSlice(&bSampler);
                    const varying Vec3f N=getN(lambert->mFrame);
                    const varying bool reflection=BsdfLobe_matchesFlag(lobe,BSDF_LOBE_TYPE_REFLECTION);
                    const varying bool excluded=isActive(BsdfLobe_getFresnel(lobe)) || BsdfLobe_getIsSpherical(lobe);
                    const varying float factor=1.f/((float)lobeSampleCount*currSamp->pdf);
                    foreach_active (lane) {
                        uniform int b=(s*VLEN+lane)*40;
                        xpu2Payload[b]=floatbits((uniform int)0x32535058);xpu2Payload[b+1]=floatbits((uniform int)1);
                        xpu2Payload[b+2]=extract(N.x,lane);xpu2Payload[b+3]=extract(N.y,lane);xpu2Payload[b+4]=extract(N.z,lane);
                        xpu2Payload[b+5]=extract(slice.mNg.x,lane);xpu2Payload[b+6]=extract(slice.mNg.y,lane);xpu2Payload[b+7]=extract(slice.mNg.z,lane);
                        xpu2Payload[b+8]=extract(slice.mWo.x,lane);xpu2Payload[b+9]=extract(slice.mWo.y,lane);xpu2Payload[b+10]=extract(slice.mWo.z,lane);
                        xpu2Payload[b+11]=extract(currSamp->sample.x,lane);xpu2Payload[b+12]=extract(currSamp->sample.y,lane);xpu2Payload[b+13]=0.f;
                        xpu2Payload[b+14]=extract(lambert->mAlbedo.r,lane);xpu2Payload[b+15]=extract(lambert->mAlbedo.g,lane);xpu2Payload[b+16]=extract(lambert->mAlbedo.b,lane);
                        xpu2Payload[b+17]=extract(lambert->mScale.r,lane);xpu2Payload[b+18]=extract(lambert->mScale.g,lane);xpu2Payload[b+19]=extract(lambert->mScale.b,lane);
                        xpu2Payload[b+20]=floatbits((uniform int)extract(reflection,lane));xpu2Payload[b+21]=floatbits((uniform int)extract(slice.mIncludeCosineTerm,lane));
                        xpu2Payload[b+22]=floatbits((uniform int)extract(slice.mShadowTerminatorFix,lane));xpu2Payload[b+23]=floatbits((uniform int)extract(excluded,lane));
                        xpu2Payload[b+24]=extract(currSamp->wi.x,lane);xpu2Payload[b+25]=extract(currSamp->wi.y,lane);xpu2Payload[b+26]=extract(currSamp->wi.z,lane);
                        xpu2Payload[b+27]=extract(currSamp->f.r,lane);xpu2Payload[b+28]=extract(currSamp->f.g,lane);xpu2Payload[b+29]=extract(currSamp->f.b,lane);
                        xpu2Payload[b+30]=extract(currSamp->pdf,lane);xpu2Payload[b+31]=0.f;
                        xpu2Payload[b+32]=extract(parentPv.pathThroughput.r,lane);xpu2Payload[b+33]=extract(parentPv.pathThroughput.g,lane);xpu2Payload[b+34]=extract(parentPv.pathThroughput.b,lane);
                        xpu2Payload[b+35]=extract(factor,lane);
                        xpu2Payload[b+36]=(!extract(excluded,lane) && extract(reflection,lane) && extract(slice.mShadowTerminatorFix,lane)==0) ? 1.f : 0.f;
                    }
                }
            }
