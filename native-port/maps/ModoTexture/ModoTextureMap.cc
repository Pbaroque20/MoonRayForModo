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
static float layerGain(float value,float amount) {
    float x=clamp(value,0.0f,1.0f), g=clamp(amount,.00001f,.99999f);
    float y=x<.5f?2*x:2-2*x;
    float b=y/((1/(1-g)-2)*(1-y)+1);
    return x<.5f?.5f*b:1-.5f*b;
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
    ispc::ModoTextureMap mData;
    ModoTextureMap(const scene_rdl2::rdl2::SceneClass& sc,const std::string& name):Parent(sc,name) {
        mSampleFunc=sample;
        mSampleFuncv=(scene_rdl2::rdl2::SampleFuncv)ispc::ModoTextureMap_getSampleFunc();
    }
    void update() override {
        mOptionalAttributes.clear();mData.uv=-1;mData.base=-1;
        mData.missing=sLogEventRegistry.createEvent(scene_rdl2::logging::WARN_LEVEL,"Normal/bump UV coordinates or derivatives unavailable; using neutral result");
        if(!get(attrUvName).empty()) {
            TypedAttributeKey<Vec2f> uv(get(attrUvName),true),base("modo_primary_uv");
            mData.uv=uv;mData.base=base;
            mOptionalAttributes.push_back(uv);mOptionalAttributes.push_back(base);
        }
    }
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
                const Vec3f N=state.getN();Vec3f T=state.getdPds()-N*dot(N,state.getdPds());
                const float lengthT=length(T);
                if(lengthT>1.e-9f) {
                    T=T/lengthT;const Vec3f B=cross(N,T);
                    const float dx=(right-left)/(2*e*lengthT),dy=(up-down)/(2*e);
                    const float crossT=dot(state.getdPdt(),T),crossB=dot(state.getdPdt(),B);
                    sx-=me->get(attrBumpStrength)*dx;
                    if(std::abs(crossB)>1.e-9f)sy-=me->get(attrBumpStrength)*(dy-dx*crossT)/crossB;
                }
            }
            n=normalize(Vec3f(sx,sy,1)); *out=Color(n.x,n.y,n.z); return;
        }
        Vec2f namedUv(0.f,0.f);Vec4f jacobian(1.f,0.f,0.f,1.f);
        const bool named=me->mData.uv>=0;
        if((mode==12 || mode==13) && named) {
            TypedAttributeKey<Vec2f> key(me->mData.uv),baseKey(me->mData.base);
            if(!state.isProvided(key) || !state.isProvided(baseKey) || !state.isdsProvided(key) || !state.isdtProvided(key)) {
                moonray::shading::logEvent(me,me->mData.missing);
                *out=mode==13?Color(.5f,.5f,1.f):Color(0.f);return;
            }
            const Vec2f ds=state.getdAttributeds(key),dt=state.getdAttributedt(key);
            const Vec2f delta=state.getSt()-state.getAttribute(baseKey);
            namedUv=state.getAttribute(key)+ds*delta.x+dt*delta.y;
            jacobian=Vec4f(ds.x,dt.x,ds.y,dt.y);
        }
        if(mode==12) {
            if(named){*out=Color(namedUv.x,namedUv.y,0);return;}
            const auto a=me->get(attrUvAffine);const auto offset=me->get(attrUvOffset);const auto st=state.getSt();
            *out=Color(a.x*st.x+a.y*st.y+offset.x,a.z*st.x+a.w*st.y+offset.y,0);return;
        }
        if(mode==13) {
            const auto a=named?jacobian:me->get(attrUvAffine);const float det=a.x*a.w-a.y*a.z;
            const Vec3f N=state.getN();Vec3f T=state.getdPds()-N*dot(N,state.getdPds());
            Vec3f U=(state.getdPds()*a.w-state.getdPdt()*a.z);
            if(std::abs(det)<1e-12f || length(T)<1e-9f){*out=Color(.5f,.5f,1);return;}
            U=U/det;U=U-N*dot(N,U);
            if(length(U)<1e-9f){*out=Color(.5f,.5f,1);return;}
            T=normalize(T);U=normalize(U);Vec3f B=cross(N,T),V=cross(N,U);
            const Vec3f derivativeV=(-state.getdPds()*a.y+state.getdPdt()*a.x)/det;
            if(dot(V,derivativeV)<0)V=-V;
            Color encoded=evalColor(me,attrForeground,tls,state);
            const auto offset=me->get(attrUvOffset);const auto st=state.getSt();
            const float u=named?namedUv.x:a.x*st.x+a.y*st.y+offset.x,v=named?namedUv.y:a.z*st.x+a.w*st.y+offset.y;
            if(me->get(attrTileU)==2 && u-2*std::floor(u/2)>1)encoded.r=1-encoded.r;
            if(me->get(attrTileV)==2 && v-2*std::floor(v/2)>1)encoded.g=1-encoded.g;
            const Vec3f normal=U*(encoded.r*2-1)+V*(encoded.g*2-1)+N*(encoded.b*2-1);
            *out=Color(dot(normal,T)*.5f+.5f,dot(normal,B)*.5f+.5f,dot(normal,N)*.5f+.5f);return;
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
        if(mode==10) {
            Color r1=evalColor(me,attrNormal,tls,state),r2=evalColor(me,attrCoordinates,tls,state);
            *out=Color(a.r*b.r+a.g*b.g+a.b*b.b,r1.r*b.r+r1.g*b.g+r1.b*b.b,r2.r*b.r+r2.g*b.g+r2.b*b.b);return;
        }
        if(mode==9) {
            float f=std::sqrt(clamp((b.r+b.g+b.b)/3,0.0f,.99f));*out=Color((1+f)/(1-f));return;
        }
        if(mode==8) {
            float g=me->get(attrDistance);
            *out=Color(layerGain(b.r,g),layerGain(b.g,g),layerGain(b.b,g));return;
        }
        if(mode==7) {
            int component=me->get(attrComponent);
            *out=Color(component==0?b.r:(component==1?b.g:b.b));return;
        }
        if(mode==11) {
            *out=Color(-std::log(clamp(b.r,1.e-6f,1.0f)),-std::log(clamp(b.g,1.e-6f,1.0f)),-std::log(clamp(b.b,1.e-6f,1.0f)))*max(0.f,a.r);return;
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
        case 12:mixed=Color((b.r<=.5f?a.r-(1-2*b.r)*a.r*(1-a.r):a.r+(2*b.r-1)*((a.r<=.25f?((16*a.r-12)*a.r+4)*a.r:sqrt(max(0.f,a.r)))-a.r)),(b.g<=.5f?a.g-(1-2*b.g)*a.g*(1-a.g):a.g+(2*b.g-1)*((a.g<=.25f?((16*a.g-12)*a.g+4)*a.g:sqrt(max(0.f,a.g)))-a.g)),(b.b<=.5f?a.b-(1-2*b.b)*a.b*(1-a.b):a.b+(2*b.b-1)*((a.b<=.25f?((16*a.b-12)*a.b+4)*a.b:sqrt(max(0.f,a.b)))-a.b)));break;
        case 13:mixed=Color((b.r>=1?1:min(1.f,a.r/max(1.e-6f,1-b.r))),(b.g>=1?1:min(1.f,a.g/max(1.e-6f,1-b.g))),(b.b>=1?1:min(1.f,a.b/max(1.e-6f,1-b.b))));break;
        case 14:mixed=Color((b.r<=0?0:1-min(1.f,(1-a.r)/max(1.e-6f,b.r))),(b.g<=0?0:1-min(1.f,(1-a.g)/max(1.e-6f,b.g))),(b.b<=0?0:1-min(1.f,(1-a.b)/max(1.e-6f,b.b))));break;
        }
        float alpha=saturate(evalFloat(me,attrOpacity,tls,state)*evalFloat(me,attrMask,tls,state));
        *out=a*(1-alpha)+mixed*alpha;
    }
RDL2_DSO_CLASS_END(ModoTextureMap)
