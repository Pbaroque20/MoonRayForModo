// Appended to the original EnvLight.ispc for an isolated native oracle.
export void xpu2NativeEnv(uniform float params[],uniform float rays[],uniform float output[]) {
    uniform EnvLight light;
    light.mOn=true;light.mMb=0;light.mDistribution=nullptr;light.mHasPortal=false;
    light.mHemispherical=params[6]!=0.f;
    light.mDirection=Vec3f_ctor(params[7],params[8],params[9]);
    light.mRadiance=Color_ctor(params[0],params[1],params[2]);
    light.mTextureFallbackColor=Color_ctor(params[3],params[4],params[5]);
    light.mLog2TexelAngle=0.f;light.mInvArea=light.mHemispherical?sOneOverTwoPi:sOneOverFourPi;
    foreach(lane=0 ... 8){
        int b=lane*4;Vec3f wi=Vec3f_ctor(rays[b],rays[b+1],rays[b+2]);
        Vec3f p=Vec3f_ctor(0.f);LightIntersection isect;
        bool hit=EnvLight_intersect((uniform Light * uniform)&light,p,p,wi,0.f,rays[b+3],isect);
        int o=lane*8;for(uniform int c=0;c<8;++c)output[o+c]=0.f;
        output[o]=hit?1.f:0.f;
        if(hit){
            LightFilterRandomValues random;float pdf=0.f,visibility=1.f;
            Color radiance=EnvLight_eval((uniform Light * uniform)&light,nullptr,wi,p,random,0.f,isect,false,nullptr,nullptr,0.f,&visibility,&pdf);
            output[o+1]=isect.distance;output[o+2]=pdf;
            output[o+3]=radiance.r;output[o+4]=radiance.g;output[o+5]=radiance.b;
        }
    }
}
