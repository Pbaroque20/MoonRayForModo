// Restricted untextured EnvLight intersection/evaluation and contribution.
// Adapted from MoonRay EnvLight.ispc, Light.isph, PathIntegratorUtil.ispc;
// DreamWorks Animation LLC, Apache-2.0. No filters, portals, motion or shadows.
__device__ void liveEnvContribution(const float* inputs,const U* sampled,float* output,U count){
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const float* a=inputs+id*40;const float* e=a+24;const U* s=sampled+id*9;float* dst=output+id*16;
    for(U k=0;k<16;++k)dst[k]=0;
    if(s[0]!=0 || s[8]!=0 || a[3]!=0 || a[0]<=0)return;
    float wi[3]={__uint_as_float(s[1]),__uint_as_float(s[2]),__uint_as_float(s[3])};
    const float maximum=__uint_as_float(0x7f7fffffu);
    const float distance=(maximum-1e32f)*.9f;
    bool hit=!(e[6]!=0 && sampleDot<true>(wi,e+7)<0) && !(distance>e[10]);
    float pdf=hit?(e[6]!=0?__uint_as_float(0x3e22f983u):__uint_as_float(0x3da2f983u)):0;
    float li[3]={0,0,0};if(hit)for(U c=0;c<3;++c)li[c]=e[c]*e[c+3];
    dst[8]=hit?1.f:0.f;dst[9]=hit?distance:0.f;dst[10]=pdf;
    for(U c=0;c<3;++c)dst[11+c]=li[c];
    dst[0]=hit?distance:(a[2]!=0?maximum:0.f);if(dst[0]<=0)return;
    float f=a[0]*__uint_as_float(s[7]),g=a[1]*pdf,inv=1.f/f;
    float weight=hit?(f*f)/(f*f+g*g):0.f;
    for(U c=0;c<3;++c){float pt=(a[8+c]*__uint_as_float(s[4+c]))*inv;
        dst[1+c]=hit?(li[c]*pt)*weight:0.f;dst[4+c]=a[2]!=0?pt:0.f;}
}
extern "C" __global__ void contribution_only(const float* a,const U* sampled,float* output,U count){liveEnvContribution(a,sampled,output,count);}
extern "C" __global__ void fused_lambert_contribution(const unsigned char* a,const U* lengths,unsigned char* echo,U* sampled,const float* env,float* output,U count){
    sampleLambert<true>(a,lengths,echo,sampled,0,0,count);liveEnvContribution(env,sampled,output,count);
}
