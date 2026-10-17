// Native-equivalent nonmirror, valid-light contribution arithmetic.
// Adapted from MoonRay PathIntegratorUtil.ispc, DreamWorks, Apache-2.0.
extern "C" __global__ void film_contribution(const float* input,float* output,unsigned mask) {
    unsigned lane=threadIdx.x;if(lane>=8 || !(mask&(1u<<lane)))return;
    const float* a=input+lane*24;float* dst=output+lane*8;
    float f=a[0]*a[7],g=a[1]*a[6],inv=1.f/f;
    float weight=(f*f)/(f*f+g*g);
    dst[0]=a[5];dst[7]=0.f;
    for(unsigned c=0;c<3;++c){float pt=(a[8+c]*a[11+c])*inv;
        dst[1+c]=(a[14+c]*pt)*weight;dst[4+c]=a[2]!=0.f?pt:0.f;}
}
