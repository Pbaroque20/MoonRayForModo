// Experimental sampling of the original Lambert lobe and reference frame.
// Adapted from MoonRay Util.h/BsdfLambert.h and scene_rdl2 ReferenceFrame.h,
// Copyright 2023-2024 DreamWorks Animation LLC, Apache-2.0.
// Numerical agreement is measured; this is not enabled in the renderer.
template<bool Vector> __device__ float sampleDot(const float* a,const float* b) {
    if(Vector)return __fadd_rn(__fadd_rn(__fmul_rn(a[0],b[0]),__fmul_rn(a[1],b[1])),__fmul_rn(a[2],b[2]));
    return lambertDot(a,b);
}
template<bool Vector> __device__ void sampleLambert(const unsigned char* input,const U* lengths,
    unsigned char* output,U* results,const float*,const float*,U count) {
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const unsigned char* src=input+id*96;unsigned char* dst=output+id*96;U* result=results+id*9;
    for(U i=0;i<96;++i)dst[i]=src[i];for(U i=0;i<9;++i)result[i]=0;
    result[0]=2;
    if(lengths[id]!=96 || get(src,0)!=0x32535058u || get(src,1)!=1 || get(src,13)!=0 || get(src,20)>1 || get(src,21)>1)return;
    float v[18];for(U i=0;i<18;++i){v[i]=__uint_as_float(get(src,i+2));if(!isfinite(v[i]))return;}
    for(U i=12;i<18;++i)if(v[i]<0)return;
    for(U i=0;i<9;i+=3)if(fabsf(sampleDot<Vector>(v+i,v+i)-1.0f)>0.0001f)return;
    float r1=v[9],r2=v[10];if(r1<0 || r1>1 || r2<0 || r2>1)return;
    result[0]=1;if(get(src,22)!=0 || get(src,23)!=0)return;
    for(U i=12;i<15;++i)if(v[i]>8.0f)return;
    for(U i=15;i<18;++i)if(v[i]>2.0f)return;
    float sign=copysignf(1.0f,v[2]),a=-1.0f/(sign+v[2]),b=v[0]*v[1]*a;
    float X[3]={1.0f+sign*v[0]*v[0]*a,sign*b,-sign*v[0]};
    float Y[3]={b,sign+v[1]*v[1]*a,-v[1]};
    float sinPhi,cosPhi;
    if(Vector)ispcSincos(r2*__uint_as_float(0x40c90fdbu),&sinPhi,&cosPhi);
    else sincosf(r2*__uint_as_float(0x40c90fdbu),&sinPhi,&cosPhi);
    float cosTheta=sqrtf(r1),sinTheta=sqrtf(1.0f-r1);
    float local[3]={sinTheta*cosPhi,sinTheta*sinPhi,cosTheta},wi[3];
    for(U i=0;i<3;++i){wi[i]=(X[i]*local[0]+Y[i]*local[1])+v[i]*local[2];result[1+i]=__float_as_uint(wi[i]);}
    float cosine=fmaxf(sampleDot<Vector>(v,wi),0.0f),pi=__uint_as_float(0x3ea2f983u);
    for(U i=0;i<3;++i){float value=(v[12+i]*v[15+i])*pi;if(get(src,21))value*=cosine;result[4+i]=__float_as_uint(value);}
    result[7]=__float_as_uint(cosine*pi);
    bool same=sampleDot<Vector>(v+3,v+6)*sampleDot<Vector>(v+3,wi)>0;
    result[8]=get(src,20)?!same:same;result[0]=0;
}

extern "C" __global__ void lambert_sample(const unsigned char* input,const U* lengths,
    unsigned char* output,U* results,const float* a,const float* b,U count) {
    sampleLambert<false>(input,lengths,output,results,a,b,count);
}
extern "C" __global__ void lambert_sample_vector(const unsigned char* input,const U* lengths,
    unsigned char* output,U* results,const float* a,const float* b,U count) {
    sampleLambert<true>(input,lengths,output,results,a,b,count);
}
