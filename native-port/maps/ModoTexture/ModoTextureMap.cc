// Original MoonRayForModo texture graph adapter, using MoonRay's Map API.
#include "attributes.cc"
#include "ModoTextureMap_ispc_stubs.h"
#include <moonray/rendering/shading/MapApi.h>
#include <moonray/rendering/shading/Intersection.h>
#include <cmath>
using namespace scene_rdl2::math;
using namespace moonray::shading;
// Repeat=0, Edge=1, Mirror=2, Reset=3. Apply after interpolation.
static float tileCoordinate(float value,int mode) {
    if(mode==0) return value-floor(value);
    if(mode==2) {
        float period=value-2*floor(value/2);
        return period<=1?period:2-period;
    }
    return clamp(value,0.0f,1.0f);
}
static float hash2(int x,int y) {
    uint32_t h=uint32_t(x)*73856093u ^ uint32_t(y)*19349663u;
    h^=h>>16; h*=0x7feb352du; h^=h>>15; h*=0x846ca68bu; h^=h>>16;
    return float(h & 0xffffffu)/16777215.0f;
}
static float noise2(float x,float y) {
    int ix=int(floor(x)), iy=int(floor(y));
    float u=x-ix,v=y-iy; u=u*u*(3-2*u); v=v*v*(3-2*v);
    return (1-v)*((1-u)*hash2(ix,iy)+u*hash2(ix+1,iy))+
           v*((1-u)*hash2(ix,iy+1)+u*hash2(ix+1,iy+1));
}
RDL2_DSO_CLASS_BEGIN(ModoTextureMap, scene_rdl2::rdl2::Map)
public:
    ModoTextureMap(const scene_rdl2::rdl2::SceneClass& sc,const std::string& name):Parent(sc,name) {
        mSampleFunc=sample;
        mSampleFuncv=(scene_rdl2::rdl2::SampleFuncv)ispc::ModoTextureMap_getSampleFunc();
    }
    void update() override {}
    static void sample(const scene_rdl2::rdl2::Map* self,TLState* tls,const State& state,Color* out) {
        const auto* me=static_cast<const ModoTextureMap*>(self);
        const int mode=me->get(attrMode);
        if(mode==1) {
            const Color encoded=evalColor(me,attrNormal,tls,state);
            Vec3f n((encoded.r*2-1)*me->get(attrNormalStrength),
                    (encoded.g*2-1)*me->get(attrNormalStrength),max(.001f,encoded.b*2-1));
            if(me->get(attrFlipGreen)) n.y=-n.y;
            float sx=n.x/n.z,sy=n.y/n.z;
            if(me->get(attrBumpStrength)!=0) {
                const float e=.001f;
                Intersection shifted=*state.getIntersection();
                State other(&shifted);
                Vec2f uv=state.getSt();
                shifted.setSt(uv+Vec2f(e,0)); float right=evalFloat(me,attrHeight,tls,other);
                shifted.setSt(uv-Vec2f(e,0)); float left=evalFloat(me,attrHeight,tls,other);
                shifted.setSt(uv+Vec2f(0,e)); float up=evalFloat(me,attrHeight,tls,other);
                shifted.setSt(uv-Vec2f(0,e)); float down=evalFloat(me,attrHeight,tls,other);
                sx-=me->get(attrBumpStrength)*(right-left)/(2*e*max(1.e-6f,length(state.getdPds())));
                sy-=me->get(attrBumpStrength)*(up-down)/(2*e*max(1.e-6f,length(state.getdPdt())));
            }
            n=normalize(Vec3f(sx,sy,1)); *out=Color(n.x,n.y,n.z); return;
        }
        if(mode==5 || mode==6) {
            const Color st=evalColor(me,attrCoordinates,tls,state);
            Vec2f uv=(me->get(attrUseCoordinates)?Vec2f(st.r,st.g):state.getSt())*me->get(attrScale);
            int u=me->get(attrTileU),v=me->get(attrTileV);
            if(mode==6) {
                float covered=((u!=3 || (uv.x>=0 && uv.x<=1)) && (v!=3 || (uv.y>=0 && uv.y<=1)))?1.0f:0.0f;
                *out=Color(covered);return;
            }
            *out=Color(tileCoordinate(uv.x,u),tileCoordinate(uv.y,v),0);return;
        }
        Color a=evalColor(me,attrBackground,tls,state),b=evalColor(me,attrForeground,tls,state);
        if(mode==7) {
            int component=me->get(attrComponent);
            *out=Color(component==0?b.r:(component==1?b.g:b.b));return;
        }
        if(mode==4) {
            const float distance=max(1.e-9f,me->get(attrDistance));
            *out=Color(-std::log(clamp(b.r,1.e-6f,1.0f)),-std::log(clamp(b.g,1.e-6f,1.0f)),-std::log(clamp(b.b,1.e-6f,1.0f)))/distance;
            return;
        }
        if(mode>=2) {
            const Color st=evalColor(me,attrCoordinates,tls,state);
            Vec2f uv=(me->get(attrUseCoordinates)?Vec2f(st.r,st.g):state.getSt())*me->get(attrScale);
            float value=0;
            if(mode==2) value=float((int(floor(uv.x*2))+int(floor(uv.y*2)))&1);
            else {
                float amplitude=1,total=0;
                for(int i=0;i<min(12,max(1,me->get(attrOctaves)));++i) {
                    value+=amplitude*noise2(uv.x,uv.y);total+=amplitude;
                    uv*=max(.01f,me->get(attrLacunarity));amplitude*=clamp(me->get(attrPersistence),0.0f,1.0f);
                }
                value/=total;
            }
            *out=a*(1-value)+b*value;return;
        }
        Color mixed=b;
        switch(me->get(attrBlend)) {
            case 1:mixed=a*b;break;
            case 2:mixed=a+b;break;
            case 3:mixed=a-b;break;
            case 4:mixed=Color(1)-(Color(1)-a)*(Color(1)-b);break;
            case 5:mixed=Color(a.r/max(1.e-6f,b.r),a.g/max(1.e-6f,b.g),a.b/max(1.e-6f,b.b));break;
            case 6:mixed=Color(std::abs(a.r-b.r),std::abs(a.g-b.g),std::abs(a.b-b.b));break;
            case 7:mixed=Color(min(a.r,b.r),min(a.g,b.g),min(a.b,b.b));break;
            case 8:mixed=Color(max(a.r,b.r),max(a.g,b.g),max(a.b,b.b));break;
            case 9:mixed=Color((a.r<.5f?2*a.r*b.r:1-2*(1-a.r)*(1-b.r)),(a.g<.5f?2*a.g*b.g:1-2*(1-a.g)*(1-b.g)),(a.b<.5f?2*a.b*b.b:1-2*(1-a.b)*(1-b.b)));break;
            case 10:mixed=Color((b.r<.5f?2*a.r*b.r:1-2*(1-a.r)*(1-b.r)),(b.g<.5f?2*a.g*b.g:1-2*(1-a.g)*(1-b.g)),(b.b<.5f?2*a.b*b.b:1-2*(1-a.b)*(1-b.b)));break;
            case 11:mixed=Color(a.r+b.r-2*a.r*b.r,a.g+b.g-2*a.g*b.g,a.b+b.b-2*a.b*b.b);break;
        }
        float alpha=saturate(evalFloat(me,attrOpacity,tls,state)*evalFloat(me,attrMask,tls,state));
        *out=a*(1-alpha)+mixed*alpha;
    }
RDL2_DSO_CLASS_END(ModoTextureMap)
