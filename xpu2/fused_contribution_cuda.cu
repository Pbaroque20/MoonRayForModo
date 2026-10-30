// Restricted contribution arithmetic adapted from MoonRay PathIntegratorUtil.ispc
// and powerHeuristic, DreamWorks Animation LLC, Apache-2.0. No shadowing/clamp.
__device__ void ownedContribution(const float* inputs,const U* sampled,float* output,U count) {
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const float* a=inputs+id*24;const U* s=sampled+id*9;float* dst=output+id*8;
    for(U k=0;k<8;++k)dst[k]=0;
    if(s[0]!=0 || a[3]!=0 || a[4]!=0 || a[0]<=0 || a[5]<=0)return;
    float pdf=__uint_as_float(s[7]);
    float f=a[0]*pdf,g=a[1]*a[6];
    float inv=1.0f/f;
    float weight=(f*f)/(f*f+g*g);
    dst[0]=a[5];
    for(U c=0;c<3;++c){float pt=(a[8+c]*__uint_as_float(s[4+c]))*inv;
        dst[1+c]=(a[14+c]*pt)*weight;dst[4+c]=a[2]!=0?pt:0;}
}
extern "C" __global__ void contribution_only(const float* inputs,const U* sampled,float* output,U count){
    ownedContribution(inputs,sampled,output,count);
}
extern "C" __global__ void fused_lambert_contribution(const unsigned char* inputs,const U* lengths,
        unsigned char* echo,U* samples,const float* contributions,float* output,U count){
    sampleLambert<true>(inputs,lengths,echo,samples,0,0,count);
    ownedContribution(contributions,samples,output,count);
}
