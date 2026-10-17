// Experimental Lambert evaluation only. Adapted from MoonRay BsdfLambert.h /
// BsdfSlice.h, Copyright 2023-2024 DreamWorks Animation LLC, Apache-2.0.
// See CUDA_SAMPLER_LICENSES.md. Fresnel and terminator fixes are declined.
__device__ float lambertDot(const float* a,const float* b) {
    // Native C++ Vec3 dot uses x + (y + z), with contraction disabled.
    return __fadd_rn(__fmul_rn(a[0],b[0]),__fadd_rn(__fmul_rn(a[1],b[1]),__fmul_rn(a[2],b[2])));
}
extern "C" __global__ void lambert(const unsigned char* input,const U* lengths,
    unsigned char* output,U* results,const float*,const float*,U count) {
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const unsigned char* src=input+id*96;unsigned char* dst=output+id*96;U* result=results+id*9;
    for(U i=0;i<96;++i)dst[i]=src[i];for(U i=0;i<9;++i)result[i]=0;
    result[0]=2;
    if(lengths[id]!=96 || get(src,0)!=0x324c5058u || get(src,1)!=1 || get(src,20)>1 || get(src,21)>1)return;
    float v[18];for(U i=0;i<18;++i){v[i]=__uint_as_float(get(src,i+2));if(!isfinite(v[i]))return;}
    for(U i=12;i<18;++i)if(v[i]<0)return;
    for(U i=0;i<12;i+=3)if(fabsf(__fsub_rn(lambertDot(v+i,v+i),1.0f))>0.0001f)return;
    result[0]=1;if(get(src,22)!=0 || get(src,23)!=0)return;
    // Finite measured color/scale range; larger values require native fallback.
    for(U i=12;i<15;++i)if(v[i]>8.0f)return;
    for(U i=15;i<18;++i)if(v[i]>2.0f)return;
    float cosine=fmaxf(lambertDot(v,v+9),0.0f),pi=__uint_as_float(0x3ea2f983u);
    for(U i=0;i<3;++i){
        float value=__fmul_rn(__fmul_rn(v[12+i],v[15+i]),pi);
        if(get(src,21))value=__fmul_rn(value,cosine);
        result[1+i]=__float_as_uint(value);
        result[5+i]=__float_as_uint(__fmul_rn(v[15+i],v[12+i]));
    }
    result[4]=__float_as_uint(__fmul_rn(cosine,pi));
    bool same=__fmul_rn(lambertDot(v+3,v+6),lambertDot(v+3,v+9))>0;
    result[8]=get(src,20)?!same:same;result[0]=0;
}
