        uniform uint64 xpu2Tokens[16];
        uniform bool xpu2Prepared=false;
        if(CPP_gpuEarlyEnabled(pbrTls) && reduce_max(lobeSampleCount)<=16 && lobe->mName==BSDF_LOBE_LAMBERT && all(pv.nonMirrorDepth==0)) {
            const varying LambertBsdfLobe *uniform lambert=(const varying LambertBsdfLobe *uniform)lobe;
            const varying BsdfSlice &slice=*BsdfSampler_getBsdfSlice(&bSampler);
            const varying Vec3f N=getN(lambert->mFrame);
            const varying bool reflection=BsdfLobe_matchesFlag(lobe,BSDF_LOBE_TYPE_REFLECTION);
            const varying bool excluded=isActive(BsdfLobe_getFresnel(lobe)) || BsdfLobe_getIsSpherical(lobe) || !reflection;
            IntegratorSample2D xpu2Sampler=bsdfSamples;
            xpu2Prepared=true;
            for(uniform int j=0;j<reduce_max(lobeSampleCount);++j){
                uniform float xpu2Input[192];
                for(uniform int k=0;k<192;++k)xpu2Input[k]=0.f;
                if(j<lobeSampleCount){
                    float xpu2Sample[2];getSample(xpu2Sampler,xpu2Sample,pv.nonMirrorDepth,*pbrTls->mFs);
                    foreach_active(lane){
                        uniform int b=lane*24;
                        xpu2Input[b]=floatbits((uniform int)0x32535058);xpu2Input[b+1]=floatbits((uniform int)1);
                        xpu2Input[b+2]=extract(N.x,lane);xpu2Input[b+3]=extract(N.y,lane);xpu2Input[b+4]=extract(N.z,lane);
                        xpu2Input[b+5]=extract(slice.mNg.x,lane);xpu2Input[b+6]=extract(slice.mNg.y,lane);xpu2Input[b+7]=extract(slice.mNg.z,lane);
                        xpu2Input[b+8]=extract(slice.mWo.x,lane);xpu2Input[b+9]=extract(slice.mWo.y,lane);xpu2Input[b+10]=extract(slice.mWo.z,lane);
                        xpu2Input[b+11]=extract(xpu2Sample[0],lane);xpu2Input[b+12]=extract(xpu2Sample[1],lane);xpu2Input[b+13]=0.f;
                        xpu2Input[b+14]=extract(lambert->mAlbedo.r,lane);xpu2Input[b+15]=extract(lambert->mAlbedo.g,lane);xpu2Input[b+16]=extract(lambert->mAlbedo.b,lane);
                        xpu2Input[b+17]=extract(lambert->mScale.r,lane);xpu2Input[b+18]=extract(lambert->mScale.g,lane);xpu2Input[b+19]=extract(lambert->mScale.b,lane);
                        xpu2Input[b+20]=floatbits((uniform int)extract(reflection,lane));xpu2Input[b+21]=floatbits((uniform int)extract(slice.mIncludeCosineTerm,lane));
                        xpu2Input[b+22]=floatbits((uniform int)extract(slice.mShadowTerminatorFix,lane));xpu2Input[b+23]=floatbits((uniform int)extract(excluded,lane));
                    }
                }
                xpu2Tokens[j]=CPP_gpuEarlySubmit(xpu2Input);
            }
        }
