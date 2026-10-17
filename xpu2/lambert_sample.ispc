// Invoke original ISPC Lambert functions through a flat diagnostic wrapper.
#include <moonray/rendering/shading/ispc/bsdf/BsdfLambert.isph>
#include <moonray/rendering/shading/ispc/bsdf/BsdfSlice.isph>
export void xpu2_lambert_sample(uniform float input[],uniform int count,uniform int reflection,uniform float output[]){
    foreach(i=0 ... count){
        int b=i*24;
        Vec3f N=Vec3f_ctor(input[b+2],input[b+3],input[b+4]);
        Vec3f Ng=Vec3f_ctor(input[b+5],input[b+6],input[b+7]);
        Vec3f wo=Vec3f_ctor(input[b+8],input[b+9],input[b+10]);
        Color color=Color_ctor(input[b+14],input[b+15],input[b+16]);
        Color scale=Color_ctor(input[b+17],input[b+18],input[b+19]);
        varying LambertBsdfLobe lobe;
        LambertBsdfLobe_init(&lobe,N,color,reflection!=0);
        BsdfLobe_setScale((varying BsdfLobe * uniform)&lobe,scale);
        varying BsdfSlice slice;
        BsdfSlice_init(&slice,Ng,wo,BSDF_LOBE_TYPE_ALL,input[b+21]!=0,true,SHADOW_TERMINATOR_FIX_OFF);
        Vec3f wi;float pdf;
        Color value=LambertBsdfLobe_sample((varying BsdfLobe * uniform)&lobe,slice,input[b+11],input[b+12],wi,pdf);
        output[i*8]=wi.x;output[i*8+1]=wi.y;output[i*8+2]=wi.z;
        output[i*8+3]=value.r;output[i*8+4]=value.g;output[i*8+5]=value.b;output[i*8+6]=pdf;
        output[i*8+7]=BsdfSlice_isSampleGeometricallyInvalid(&slice,*((varying BsdfLobe * uniform)&lobe),wi)?1.0f:0.0f;
    }
}
