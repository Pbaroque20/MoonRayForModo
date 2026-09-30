#include "attributes.isph"
#include <moonray/rendering/shading/ispc/MapApi.isph>
static float hash2(int x,int y) {
    unsigned int h=(unsigned int)x*73856093u ^ (unsigned int)y*19349663u;
    h^=h>>16;h*=0x7feb352du;h^=h>>15;h*=0x846ca68bu;h^=h>>16;
    return (float)(h & 0xffffffu)/16777215.0f;
}
static float noise2(float x,float y) {
    int ix=(int)floor(x),iy=(int)floor(y);
    float u=x-ix,v=y-iy;u=u*u*(3-2*u);v=v*v*(3-2*v);
    return (1-v)*((1-u)*hash2(ix,iy)+u*hash2(ix+1,iy))+
           v*((1-u)*hash2(ix,iy+1)+u*hash2(ix+1,iy+1));
}
static Color sample(const uniform Map* uniform me,uniform ShadingTLState* uniform tls,const varying State& state) {
    uniform int mode=getAttrMode(me);
    if(mode==1) {
        Color encoded=evalAttrNormal(me,tls,state);
        Vec3f n=Vec3f_ctor((encoded.r*2-1)*getAttrNormalStrength(me),
            (encoded.g*2-1)*getAttrNormalStrength(me),max(.001f,encoded.b*2-1));
        if(getAttrFlipGreen(me)) n.y=-n.y;
        float sx=n.x/n.z,sy=n.y/n.z;
        if(getAttrBumpStrength(me)!=0) {
            uniform float e=.001f;
            State other=state;
            other.mSt.x=state.mSt.x+e;float right=evalAttrHeight(me,tls,other);
            other.mSt.x=state.mSt.x-e;float left=evalAttrHeight(me,tls,other);
            other.mSt.x=state.mSt.x;other.mSt.y=state.mSt.y+e;float up=evalAttrHeight(me,tls,other);
            other.mSt.y=state.mSt.y-e;float down=evalAttrHeight(me,tls,other);
            sx-=getAttrBumpStrength(me)*(right-left)/(2*e*max(1.e-6f,length(state.mdPds)));
            sy-=getAttrBumpStrength(me)*(up-down)/(2*e*max(1.e-6f,length(state.mdPdt)));
        }
        n=normalize(Vec3f_ctor(sx,sy,1));return Color_ctor(n.x,n.y,n.z);
    }
    Color a=evalAttrBackground(me,tls,state),b=evalAttrForeground(me,tls,state);
    if(mode>=2) {
        Vec2f scale=getAttrScale(me);
        float x=state.mSt.x*scale.x,y=state.mSt.y*scale.y,value=0;
        if(mode==2) value=(float)(((int)floor(x*2)+(int)floor(y*2))&1);
        else {
            float amplitude=1,total=0;
            for(uniform int i=0;i<min(12,max(1,getAttrOctaves(me)));++i) {
                value+=amplitude*noise2(x,y);total+=amplitude;
                x*=max(.01f,getAttrLacunarity(me));y*=max(.01f,getAttrLacunarity(me));
                amplitude*=clamp(getAttrPersistence(me),0.0f,1.0f);
            }
            value/=total;
        }
        return a*(1-value)+b*value;
    }
    Color mixed=b;
    switch(getAttrBlend(me)) {
        case 1:mixed=a*b;break;
        case 2:mixed=a+b;break;
        case 3:mixed=a-b;break;
        case 4:mixed=sWhite-(sWhite-a)*(sWhite-b);break;
        case 5:mixed=Color_ctor(a.r/max(1.e-6f,b.r),a.g/max(1.e-6f,b.g),a.b/max(1.e-6f,b.b));break;
    }
    float alpha=saturate(evalAttrOpacity(me,tls,state)*evalAttrMask(me,tls,state));
    return a*(1-alpha)+mixed*alpha;
}
DEFINE_MAP_SHADER(ModoTextureMap,sample)
