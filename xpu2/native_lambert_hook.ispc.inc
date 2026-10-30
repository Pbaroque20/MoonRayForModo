    // Diagnostic only: preserve the native answer while measuring a live CUDA replacement.
    varying Color answer = LambertBsdfLobe_eval(lobe, slice, wi, &pdf);
    uniform float input[8*24];
    uniform float output[8*8];
    uniform int count = 0;
    uniform int lanes[8];
    const varying Vec3f N = getN(lambert->mFrame);
    const varying bool reflection = BsdfLobe_matchesFlag(lobe, BSDF_LOBE_TYPE_REFLECTION);
    const varying bool excluded = isActive(BsdfLobe_getFresnel(lobe)) || BsdfLobe_getIsSpherical(lobe);
    const varying bool invalid = BsdfSlice_isSampleGeometricallyInvalid(&slice, *lobe, wi);
    foreach_active (lane) {
        uniform int b = count*24, o = count*8;
        lanes[count] = lane;
        input[b]=floatbits((uniform int)0x32535058); input[b+1]=floatbits((uniform int)1);
        input[b+2]=extract(N.x,lane); input[b+3]=extract(N.y,lane); input[b+4]=extract(N.z,lane);
        input[b+5]=extract(slice.mNg.x,lane); input[b+6]=extract(slice.mNg.y,lane); input[b+7]=extract(slice.mNg.z,lane);
        input[b+8]=extract(slice.mWo.x,lane); input[b+9]=extract(slice.mWo.y,lane); input[b+10]=extract(slice.mWo.z,lane);
        input[b+11]=extract(r1,lane); input[b+12]=extract(r2,lane); input[b+13]=0.f;
        input[b+14]=extract(lambert->mAlbedo.r,lane); input[b+15]=extract(lambert->mAlbedo.g,lane); input[b+16]=extract(lambert->mAlbedo.b,lane);
        input[b+17]=extract(lambert->mScale.r,lane); input[b+18]=extract(lambert->mScale.g,lane); input[b+19]=extract(lambert->mScale.b,lane);
        input[b+20]=floatbits((uniform int)extract(reflection,lane));
        input[b+21]=floatbits((uniform int)extract(slice.mIncludeCosineTerm,lane));
        input[b+22]=floatbits((uniform int)extract(slice.mShadowTerminatorFix,lane));
        input[b+23]=floatbits((uniform int)extract(excluded,lane));
        output[o]=extract(wi.x,lane); output[o+1]=extract(wi.y,lane); output[o+2]=extract(wi.z,lane);
        output[o+3]=extract(answer.r,lane); output[o+4]=extract(answer.g,lane); output[o+5]=extract(answer.b,lane);
        output[o+6]=extract(pdf,lane); output[o+7]=(uniform float)extract(invalid,lane);
        count++;
    }
    xpu2NativeLambert(input, output, count);
    for (uniform int i=0; i<count; ++i) {
        wi.x=insert(wi.x,lanes[i],output[i*8]); wi.y=insert(wi.y,lanes[i],output[i*8+1]); wi.z=insert(wi.z,lanes[i],output[i*8+2]);
        answer.r=insert(answer.r,lanes[i],output[i*8+3]); answer.g=insert(answer.g,lanes[i],output[i*8+4]); answer.b=insert(answer.b,lanes[i],output[i*8+5]);
        pdf=insert(pdf,lanes[i],output[i*8+6]);
    }
    return answer;
