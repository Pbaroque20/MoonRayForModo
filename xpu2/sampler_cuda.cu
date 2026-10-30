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
__device__ U hashSeed(U h,U s) {
    s^=0xb994ef91u+(s<<6)+(s>>2);
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
// MoonRay Sampling.ispc / Permute.isph, Apache-2.0; Kensler CMJ.
__device__ U permute(U i,U length,U p) {
    U w=length-1;w|=w>>1;w|=w>>2;w|=w>>4;w|=w>>8;w|=w>>16;
    do {
        i^=p;i*=0xe170893du;i^=p>>16;i^=(i&w)>>4;
        i^=p>>8;i*=0x0929eb3fu;i^=p>>23;i^=(i&w)>>1;
        i*=1|(p>>27);i*=0x6935fa69u;i^=(i&w)>>11;i*=0x74dcb303u;
        i^=(i&w)>>2;i*=0x9e501cc3u;i^=(i&w)>>2;i*=0xc860a3dfu;
        i&=w;i^=i>>5;
    } while(i>=length);
    return (i+p)%length;
}
__device__ U randomHash(U i,U p) {
    i^=p;i^=i>>17;i^=i>>10;i*=0xb36534e5u;
    i^=i>>12;i^=i>>21;i*=0x93fc4795u;i^=0xdf6e307fu;
    i^=i>>17;i*=1|(p>>18);return i;
}
__device__ float unitFloat(U mantissa) {
    return __fsub_rn(__uint_as_float(0x3f800000u|mantissa),1.0f);
}
__device__ bool knownCount(U total) {
    return total==1 || total==2 || total==3 || total==4 || total==7 ||
           total==8 || total==15 || total==16 || total==17 || total==63 ||
           total==64 || total==65 || total==257;
}
__device__ void cmj(U hash,U total,U index,U* result) {
    if(total==1) {
        result[0]=__float_as_uint(unitFloat(randomHash(0,hashSeed(hash,0xf2b143c3u))>>9));
        result[1]=__float_as_uint(unitFloat(randomHash(1,hashSeed(hash,0x1d3cb933u))>>9));
        return;
    }
    U m=1;while((m+1)*(m+1)<=total)++m;
    U n=(total+m-1)/m, scramble=hashSeed(hash,0x2904c44eu);
    U sample=permute(index,total,scramble*0x51633e2du);
    U sx=permute(sample%m,m,scramble*0x68bc21ebu);
    U sy=permute(sample/m,n,scramble*0x02e5be93u);
    float jx=unitFloat(randomHash(sample,scramble*0x967a889bu)&0x7fffffu);
    float jy=unitFloat(randomHash(sample,scramble*0x368cc8b7u)&0x7fffffu);
    result[0]=__float_as_uint(__fdiv_rn(__fadd_rn(float(sx),__fdiv_rn(__fadd_rn(float(sy),jx),float(n))),float(m)));
    result[1]=__float_as_uint(__fdiv_rn(__fadd_rn(float(sample),jy),float(total)));
}
__device__ float rotateSample(float value,U seed) {
    float x=__fadd_rn(value,unitFloat(seed&0x7fffffu));
    return x>=1.0f ? __fsub_rn(x,1.0f) : x;
}
__device__ void tableSamples(U hash,U dims,U index,const float* one,const float* two,U* result) {
    if(dims>=2) {
        U seq=hashSeed(hash,0x4a770fdfu)%4096u, offset=(seq*1024u+index)*2;
        result[0]=__float_as_uint(rotateSample(two[offset],hashSeed(hash,0xd0944adbu)));
        result[1]=__float_as_uint(rotateSample(two[offset+1],hashSeed(hash,0x0662aa53u)));
    }
    if(dims!=2) {
        U seq=hashSeed(hash,0x0740eb57u)%4096u, offset=seq*1024u+index;
        result[dims==1?0:2]=__float_as_uint(rotateSample(one[offset],hashSeed(hash,0x5b748587u)));
    }
}
extern "C" __global__ void sampler(const unsigned char* input,const U* lengths,
                                  unsigned char* output,U* results,const float* one,const float* two,U count) {
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
    if(!pseudo && depth<3) {
        if(dims==2 && knownCount(total)) {
            cmj(result[1],total,next,result+2);
        } else if(one && two && next<65 && (dims!=2 || total==0xffffffffu)) {
            // Bounded validated table prefix. No late-cache/R-sequence approximation.
            tableSamples(result[1],dims,next,one,two,result+2);
        } else return;
    } else {
        U words[4];random4(hashSeed(result[1],0xa511e9b3u),next,words);
        for(U i=0;i<dims;++i)
            result[2+i]=__float_as_uint(__fsub_rn(__uint_as_float(0x3f800000u|(words[i]>>9)),1.0f));
    }
    put(dst,5,next+1);put(dst,14,checksum(dst));result[0]=0;
}
