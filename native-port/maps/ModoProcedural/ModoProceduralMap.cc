// Modo's procedural textures, worked out where each point is at render time (modo_patterns.h, which the ISPC code
// and MoonLightIPR's kernel share): no baking, no UVs, no resolution.
#include "attributes.cc"
#include "ModoProceduralMap_ispc_stubs.h"
#include "modo_patterns.h"
#include <moonray/rendering/shading/MapApi.h>
#include <moonray/rendering/shading/Xform.h>
#include <memory>
using namespace scene_rdl2::math;
using namespace moonray::shading;
RDL2_DSO_CLASS_BEGIN(ModoProceduralMap, scene_rdl2::rdl2::Map)
public:
    ispc::ModoProceduralMap mData;
    std::unique_ptr<Xform> mXform;
    ModoProceduralMap(const scene_rdl2::rdl2::SceneClass& sc,const std::string& name):Parent(sc,name) {
        mSampleFunc=sample;
        mSampleFuncv=(scene_rdl2::rdl2::SampleFuncv)ispc::ModoProceduralMap_getSampleFunc();
    }
    void update() override {
        mXform=std::make_unique<Xform>(this,nullptr,nullptr,nullptr);
        mData.mXform=mXform->getIspcXform();
        // The settings where the ISPC code reads them too; bias and gain 0.5, neutral, unless given.
        const std::vector<float>& given=get(attrSettings);
        for(int i=0;i<24;++i) mData.mSettings[i]=i<int(given.size())?given[i]:(i>=22?0.5f:0.0f);
    }
    static void sample(const scene_rdl2::rdl2::Map* self,TLState* tls,const State& state,Color* out) {
        const auto* me=static_cast<const ModoProceduralMap*>(self);
        const int space=me->get(attrSpace);
        Vec3f p;
        if(space==2) {const Vec2f st=state.getSt();p=Vec3f(st.x,st.y,0.0f);}
        else p=me->mXform->transformPoint(ispc::SHADING_SPACE_RENDER,space==1?ispc::SHADING_SPACE_OBJECT:ispc::SHADING_SPACE_WORLD,state,state.getP());
        const Vec4f r0=me->get(attrRow0),r1=me->get(attrRow1),r2=me->get(attrRow2);
        const float x=r0.x*p.x+r0.y*p.y+r0.z*p.z+r0.w,y=r1.x*p.x+r1.y*p.y+r1.z*p.z+r1.w,z=r2.x*p.x+r2.y*p.y+r2.z*p.z+r2.w;
        MP_Settings settings;
        for(int i=0;i<24;++i) settings.v[i]=me->mData.mSettings[i];
        if(me->get(attrPattern)>=400) {
            // A process: its colour made from the colour beneath it, wholly there.
            const Color beneath=evalColor(me,attrInput,tls,state);
            const MP_Rgb made=mp_process(me->get(attrPattern),beneath.r,beneath.g,beneath.b,settings);
            *out=me->get(attrOutput)==1?Color(1.0f,1.0f,1.0f):Color(made.r,made.g,made.b);return;
        }
        const float t=mp_pattern(me->get(attrPattern),me->get(attrType),x,y,z,settings);
        if(me->get(attrOutput)==1) {
            const float low=std::min(me->get(attrAlpha1),me->get(attrAlpha2)),high=std::max(me->get(attrAlpha1),me->get(attrAlpha2));
            const float alpha=std::min(high,std::max(low,me->get(attrAlpha1)*t+me->get(attrAlpha2)*(1-t)));
            *out=Color(alpha,alpha,alpha);return;
        }
        const Color one=evalColor(me,attrColor1,tls,state),two=evalColor(me,attrColor2,tls,state);
        *out=one*t+two*(1-t);
    }
RDL2_DSO_CLASS_END(ModoProceduralMap)
