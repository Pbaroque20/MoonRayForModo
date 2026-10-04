#include "attributes.isph"
#include <moonray/rendering/shading/ispc/MapApi.isph>
// Repeat=0, Edge=1, Mirror=2, Reset=3. Apply after interpolation.
static float tileCoordinate(float value,int mode) {
    if(mode==0) return value-floor(value);
    if(mode==2) {
        float period=value-2*floor(value/2);
        return period<=1?period:2-period;
    }
    return clamp(value,0.0f,1.0f);
}
static float layerGain(float value,float amount) {
    float x=clamp(value,0.0f,1.0f), g=clamp(amount,.00001f,.99999f);
    float y=x<.5f?2*x:2-2*x;
    float b=y/((1/(1-g)-2)*(1-y)+1);
    return x<.5f?.5f*b:1-.5f*b;
}
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
    if(mode==12) {
        Vec4f a=getAttrUvAffine(me);Vec2f offset=getAttrUvOffset(me);
        return Color_ctor(a.x*state.mSt.x+a.y*state.mSt.y+offset.x,a.z*state.mSt.x+a.w*state.mSt.y+offset.y,0);
    }
    if(mode==13) {
        Vec4f a=getAttrUvAffine(me);float det=a.x*a.w-a.y*a.z;
        Vec3f N=getN(state);Vec3f T=state.mdPds-N*dot(N,state.mdPds);
        if(abs(det)<1e-12f || length(T)<1e-9f)return Color_ctor(.5f,.5f,1);
        Vec3f U=(state.mdPds*a.w-state.mdPdt*a.z)/det;U=U-N*dot(N,U);
        if(length(U)<1e-9f)return Color_ctor(.5f,.5f,1);
        T=normalize(T);U=normalize(U);Vec3f B=cross(N,T),V=cross(N,U);
        Vec3f derivativeV=(state.mdPds*(-a.y)+state.mdPdt*a.x)/det;
        if(dot(V,derivativeV)<0)V=V*(-1.f);
        Color encoded=evalAttrForeground(me,tls,state);
        Vec3f normal=U*(encoded.r*2-1)+V*(encoded.g*2-1)+N*(encoded.b*2-1);
        return Color_ctor(dot(normal,T)*.5f+.5f,dot(normal,B)*.5f+.5f,dot(normal,N)*.5f+.5f);
    }
    if(mode==5 || mode==6) {
        Color st=evalAttrCoordinates(me,tls,state);
        Vec2f scale=getAttrScale(me);
        float x=(getAttrUseCoordinates(me)?st.r:state.mSt.x)*scale.x;
        float y=(getAttrUseCoordinates(me)?st.g:state.mSt.y)*scale.y;
        uniform int u=getAttrTileU(me),v=getAttrTileV(me);
        if(mode==6) {
            float covered=((u!=3 || (x>=0 && x<=1)) && (v!=3 || (y>=0 && y<=1)))?1.0f:0.0f;
            return Color_ctor(covered,covered,covered);
        }
        return Color_ctor(tileCoordinate(x,u),tileCoordinate(y,v),0);
    }
    Color a=evalAttrBackground(me,tls,state),b=evalAttrForeground(me,tls,state);
    if(mode==10) {
        Color r1=evalAttrNormal(me,tls,state),r2=evalAttrCoordinates(me,tls,state);
        return Color_ctor(a.r*b.r+a.g*b.g+a.b*b.b,r1.r*b.r+r1.g*b.g+r1.b*b.b,r2.r*b.r+r2.g*b.g+r2.b*b.b);
    }
    if(mode==9) {
        float f=sqrt(clamp((b.r+b.g+b.b)/3,0.0f,.99f));return Color_ctor((1+f)/(1-f));
    }
    if(mode==8) {
        float g=getAttrDistance(me);
        return Color_ctor(layerGain(b.r,g),layerGain(b.g,g),layerGain(b.b,g));
    }
    if(mode==7) {
        uniform int component=getAttrComponent(me);
        float value=component==0?b.r:(component==1?b.g:b.b);
        return Color_ctor(value,value,value);
    }
    if(mode==11) {
        return Color_ctor(-log(clamp(b.r,1.e-6f,1.0f)),-log(clamp(b.g,1.e-6f,1.0f)),-log(clamp(b.b,1.e-6f,1.0f)))*max(0.f,a.r);
    }
    if(mode==4) {
        float distance=max(1.e-9f,getAttrDistance(me));
        return Color_ctor(-log(clamp(b.r,1.e-6f,1.0f)),-log(clamp(b.g,1.e-6f,1.0f)),-log(clamp(b.b,1.e-6f,1.0f)))/distance;
    }
    if(mode>=2) {
        Vec2f scale=getAttrScale(me);
        Color st=evalAttrCoordinates(me,tls,state);
        float x=(getAttrUseCoordinates(me)?st.r:state.mSt.x)*scale.x;
        float y=(getAttrUseCoordinates(me)?st.g:state.mSt.y)*scale.y,value=0;
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
        case 6:mixed=Color_ctor(abs(a.r-b.r),abs(a.g-b.g),abs(a.b-b.b));break;
        case 7:mixed=Color_ctor(min(a.r,b.r),min(a.g,b.g),min(a.b,b.b));break;
        case 8:mixed=Color_ctor(max(a.r,b.r),max(a.g,b.g),max(a.b,b.b));break;
        case 9:mixed=Color_ctor((a.r<.5f?2*a.r*b.r:1-2*(1-a.r)*(1-b.r)),(a.g<.5f?2*a.g*b.g:1-2*(1-a.g)*(1-b.g)),(a.b<.5f?2*a.b*b.b:1-2*(1-a.b)*(1-b.b)));break;
        case 10:mixed=Color_ctor((b.r<.5f?2*a.r*b.r:1-2*(1-a.r)*(1-b.r)),(b.g<.5f?2*a.g*b.g:1-2*(1-a.g)*(1-b.g)),(b.b<.5f?2*a.b*b.b:1-2*(1-a.b)*(1-b.b)));break;
        case 11:mixed=Color_ctor(a.r+b.r-2*a.r*b.r,a.g+b.g-2*a.g*b.g,a.b+b.b-2*a.b*b.b);break;
        case 12:mixed=Color_ctor((b.r<=.5f?a.r-(1-2*b.r)*a.r*(1-a.r):a.r+(2*b.r-1)*((a.r<=.25f?((16*a.r-12)*a.r+4)*a.r:sqrt(max(0.f,a.r)))-a.r)),(b.g<=.5f?a.g-(1-2*b.g)*a.g*(1-a.g):a.g+(2*b.g-1)*((a.g<=.25f?((16*a.g-12)*a.g+4)*a.g:sqrt(max(0.f,a.g)))-a.g)),(b.b<=.5f?a.b-(1-2*b.b)*a.b*(1-a.b):a.b+(2*b.b-1)*((a.b<=.25f?((16*a.b-12)*a.b+4)*a.b:sqrt(max(0.f,a.b)))-a.b)));break;
        case 13:mixed=Color_ctor((b.r>=1?1:min(1.f,a.r/max(1.e-6f,1-b.r))),(b.g>=1?1:min(1.f,a.g/max(1.e-6f,1-b.g))),(b.b>=1?1:min(1.f,a.b/max(1.e-6f,1-b.b))));break;
        case 14:mixed=Color_ctor((b.r<=0?0:1-min(1.f,(1-a.r)/max(1.e-6f,b.r))),(b.g<=0?0:1-min(1.f,(1-a.g)/max(1.e-6f,b.g))),(b.b<=0?0:1-min(1.f,(1-a.b)/max(1.e-6f,b.b))));break;
    }
    float alpha=saturate(evalAttrOpacity(me,tls,state)*evalAttrMask(me,tls,state));
    return a*(1-alpha)+mixed*alpha;
}
DEFINE_MAP_SHADER(ModoTextureMap,sample)
