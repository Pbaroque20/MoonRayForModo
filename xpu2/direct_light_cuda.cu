// Experimental direct-light numerical unit. Native shadows and film remain on host.
// Adapted from MoonRay PathIntegratorUtil.ispc / BsdfLambert / BsdfFlatDiffuse,
// Copyright DreamWorks Animation LLC, Apache-2.0. See CUDA_SAMPLER_LICENSES.md.
extern "C" __global__ void direct_light_unit(const float* inputs,float* outputs,unsigned count){
    unsigned id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const float* a=inputs+id*32;float* r=outputs+id*9;
    for(unsigned k=0;k<9;++k)r[k]=0.f;
    unsigned kind=__float_as_uint(a[0]);if(kind!=1 && kind!=2)return;
    for(unsigned k=1;k<32;++k)if(!isfinite(a[k]))return;
    if(a[29]!=0.f || a[30]!=0.f || a[31]!=0.f || (a[28]!=0.f && a[28]!=1.f))return;
    if(a[22]<1.f || a[23]<0.f || a[24]<=0.f || a[25]<0.f)return;
    if(a[22]!=floorf(a[22]) || a[23]!=floorf(a[23]))return;
    for(unsigned k=10;k<22;++k)if(a[k]<0.f)return;
    for(unsigned k=1;k<10;k+=3)if(fabsf(sampleDot<true>(a+k,a+k)-1.f)>0.0001f)return;
    if(kind==1 && (a[26]!=0.f || a[27]!=0.f))return;
    if(kind==2 && (a[26]<0.f || a[26]>1.f || a[27]<0.f || a[27]>1.f))return;
    float cosine=fmaxf(sampleDot<true>(a+1,a+4),0.f);
    if(kind==2){
        float inv=1.f/sqrtf(sampleDot<true>(a+1,a+1));float n[3]={a[1]*inv,a[2]*inv,a[3]*inv};
        float angle=fminf(__uint_as_float(0x3fc90fdbu),nativeAcos(fminf(1.f,fmaxf(-1.f,sampleDot<true>(n,a+4)))));
        float unused,nl;ispcSincos(angle,&unused,&nl);nl=fmaxf(nl,0.f);
        float nv=fmaxf(sampleDot<true>(n,a+7),0.f),s=sampleDot<true>(a+4,a+7)-nl*nv;
        float t=s>0.f?fmaxf(nl,nv)+1.e-6f:1.f;
        cosine=nl*(a[26]+a[27]*s/t);
    }
    const float pi=__uint_as_float(0x3ea2f983u),pdf=cosine*pi;
    if(pdf<=0.f || !isfinite(pdf))return;
    float x=a[22]*a[25],y=a[23]*pdf,den=x*x+y*y;
    if(den<=0.f || !isfinite(den))return;
    const float weight=(x*x)/den,inv=1.f/(a[22]*a[24]);
    for(unsigned c=0;c<3;++c){
        float f=kind==1?(a[10+c]*a[13+c])*pi:(a[10+c]*pi)*a[13+c];
        if(a[28])f*=cosine;
        float factor=(a[16+c]*a[19+c])*inv;
        r[c]=f;r[4+c]=(factor*f)*weight;
        if(!isfinite(r[c]) || !isfinite(r[4+c]))return;
    }
    r[3]=pdf;r[7]=weight;r[8]=1.f;
}
