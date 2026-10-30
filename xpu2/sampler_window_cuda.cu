// Experimental version-2 boundary kernel. Concatenated after sampler_cuda.cu.
// RSequence/hash arithmetic adapted from MoonRay, Copyright 2023-2024
// DreamWorks Animation LLC, Apache-2.0. See CUDA_SAMPLER_LICENSES.md.
__device__ U windowChecksum(const unsigned char* p) {
    U h=2166136261u;for(U i=0;i<60;++i)h=(h^p[i])*16777619u;return h;
}
__device__ U triple(U x) {
    ++x;x^=x>>17;x*=0xed5ad4bbu;x^=x>>11;x*=0xac4c1b51u;
    x^=x>>15;x*=0x31848babu;x^=x>>14;return x;
}
__device__ U hash16(U x) {
    x=(x+(x<<7))&65535u;x^=x>>8;
    x=(x+(x<<3))&65535u;x^=x>>2;
    x=(x+(x<<4))&65535u;x^=x>>8;return x;
}
__device__ float fraction(float x) {return __fsub_rn(x,floorf(x));}
__device__ float r1(U i,U scramble,const float* moebius) {
    U index=hash16(scramble>>16)%16384u;
    float s0=unitFloat((hash16(scramble&65535u)<<16)>>9);
    float p=__fadd_rn(s0,__fmul_rn(__uint2float_rn(i),moebius[index]));
    constexpr float numerator=0.4f*0.26f;
    float k=__fdiv_rn(numerator,__fadd_rn(__uint2float_rn(i),1.010f));
    float u=unitFloat(triple(scramble)>>9);
    return fraction(__fadd_rn(p,__fmul_rn(k,u)));
}
__device__ void r2(U n,U scramble,float* value) {
    constexpr float g=1.324717957244746f;
    constexpr float a=1.0f/g,b=1.0f/(g*g);
    constexpr float numerator=0.4f*0.76f*1.7724538509055160272981674833411451827975494561223871282138077898f;
    constexpr float n0=1.0f-0.700f;
    // n+1 and n+scramble intentionally wrap as unsigned native operations.
    float step=__uint2float_rn(n+1);
    float p0=fraction(__fmul_rn(a,step)),p1=fraction(__fmul_rn(b,step));
    U random=n+scramble,rotated=(random<<16)|(random>>16);
    float u0=unitFloat(triple(random)>>9),u1=unitFloat(triple(rotated)>>9);
    float k=__fdiv_rn(numerator,__fmul_rn(4.0f,__fsqrt_rn(__fadd_rn(__uint2float_rn(n),n0))));
    value[0]=fraction(__fadd_rn(p0,__fmul_rn(k,u0)));
    value[1]=fraction(__fadd_rn(p1,__fmul_rn(k,u1)));
}
extern "C" __global__ void sampler_window(const unsigned char* input,const U* lengths,
    unsigned char* output,U* results,const float* one,const float* two,const float* moebius,U count) {
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const unsigned char* src=input+id*64;unsigned char* dst=output+id*64;U* result=results+id*5;
    for(U i=0;i<64;++i)dst[i]=src[i];for(U i=0;i<5;++i)result[i]=0;
    result[0]=2;
    U dims=get(src,2),depth=get(src,3),total=get(src,4),next=get(src,5),pseudo=get(src,6),anchor=get(src,14);
    if(lengths[id]!=64 || get(src,0)!=0x32555058u || get(src,1)!=2 || get(src,7)!=6 ||
       get(src,15)!=windowChecksum(src) || dims<1 || dims>3 || pseudo>1 || total==0 ||
       (total!=0xffffffffu && next>=total) || next>=0xffffffffu-8u || anchor>next || next-anchor>8)return;
    result[1]=sequence(src);result[0]=1;
    // Only the measured unknown-count boundary corpus is enabled here.
    if(!one || !two || !moebius || total!=0xffffffffu || pseudo ||
       (depth!=0 && depth!=2) || next<1000 || next>=1048)return;
    if(next-anchor==8)anchor=next;
    if(anchor+8<1024) {
        tableSamples(result[1],dims,next,one,two,result+2);
    } else {
        U index=next-1024u; // Native unsigned wrap before index 1024 is intentional.
        if(dims>=2) {
            float v[2];r2(index,hashSeed(result[1],0xa81972b7u),v);
            result[2]=__float_as_uint(rotateSample(v[0],hashSeed(result[1],0xd0944adbu)));
            result[3]=__float_as_uint(rotateSample(v[1],hashSeed(result[1],0x0662aa53u)));
        }
        if(dims!=2) {
            float v=r1(index,hashSeed(result[1],0xdf4f4915u),moebius);
            result[dims==1?2:4]=__float_as_uint(rotateSample(v,hashSeed(result[1],0x5b748587u)));
        }
    }
    put(dst,5,next+1);put(dst,14,anchor);put(dst,15,windowChecksum(dst));result[0]=0;
}
