// XPU2 diagnostic CUDA subset, not a rendering backend.
// Hashing/conversion derived from MoonRay / scene_rdl2:
// Copyright 2023-2024 DreamWorks Animation LLC, Apache-2.0.
// Threefry4x32 adapted from Random123, Copyright 2010-2011 D. E. Shaw Research.
// See CUDA_SAMPLER_LICENSES.md for notices. No fast-math approximation.
typedef unsigned int U;
__device__ U get(const unsigned char* p,U i) {
    U v=0;for(U b=0;b<4;++b)v|=U(p[4*i+b])<<(8*b);return v;
}
__device__ void put(unsigned char* p,U i,U v) {
    for(U b=0;b<4;++b)p[4*i+b]=(unsigned char)(v>>(8*b));
}
__device__ U checksum(const unsigned char* p) {
    U h=2166136261u;for(U i=0;i<56;++i)h=(h^p[i])*16777619u;return h;
}
__device__ U combine(U a,U b) {return a^(b+0x9e3779b9u+(a<<6)+(a>>2));}
__device__ U single(U v) {
    U h=combine(0x31e149a2u,v);h=(h<<19)-h;return (h<<31)-h;
}
__device__ U sequence(const unsigned char* p) {
    U h=single(get(p,13));
    for(int i=12;i>=8;--i) {U a=single(get(p,i));h=combine(combine(a,h),a);}
    return h;
}
__device__ U key(U h) {
    U s=0xa511e9b3u;s^=0xb994ef91u+(s<<6)+(s>>2);
    U a=0x6cf575c5u*(s+h);a=(a>>18)|(a<<14);return 0x6cf575c5u*a;
}
__device__ U rotl(U x,U n) {return (x<<n)|(x>>(32-n));}
__device__ void random4(U seed,U index,U* x) {
    const U rotations[8][2]={{10,26},{11,21},{13,27},{23,5},{6,20},{17,11},{25,10},{18,20}};
    U k[5]={seed,seed+1,seed+2,seed+3,0x1bd11bdau};
    for(U i=0;i<4;++i) {k[4]^=k[i];x[i]=index+k[i];}
    for(U r=0;r<20;++r) {
        U a=(r&1)?3:1,b=(r&1)?1:3;
        x[0]+=x[a];x[a]=rotl(x[a],rotations[r%8][0])^x[0];
        x[2]+=x[b];x[b]=rotl(x[b],rotations[r%8][1])^x[2];
        if(r%4==3) {U s=(r+1)/4;for(U i=0;i<4;++i)x[i]+=k[(s+i)%5];x[3]+=s;}
    }
}
extern "C" __global__ void sampler(const unsigned char* input,const U* lengths,
                                  unsigned char* output,U* results,U count) {
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const unsigned char* src=input+id*60;unsigned char* dst=output+id*60;U* result=results+id*5;
    for(U i=0;i<60;++i)dst[i]=src[i];
    for(U i=0;i<5;++i)result[i]=0;
    result[0]=2; // Invalid: no sample/no cursor advance.
    U dims=get(src,2),depth=get(src,3),total=get(src,4),next=get(src,5),pseudo=get(src,6);
    if(lengths[id]!=60 || get(src,0)!=0x32555058u || get(src,1)!=1 || get(src,7)!=6 ||
       get(src,14)!=checksum(src) || dims<1 || dims>3 || pseudo>1 || total==0 ||
       (total!=0xffffffffu && next>=total) || next>=0xffffffffu-8u)return;
    result[1]=sequence(src);
    result[0]=1; // Unsupported distribution: retain exact state for CPU handling.
    if(!pseudo && depth<3)return;
    U words[4];random4(key(result[1]),next,words);
    for(U i=0;i<dims;++i)
        result[2+i]=__float_as_uint(__fsub_rn(__uint_as_float(0x3f800000u|(words[i]>>9)),1.0f));
    put(dst,5,next+1);put(dst,14,checksum(dst));result[0]=0;
}
