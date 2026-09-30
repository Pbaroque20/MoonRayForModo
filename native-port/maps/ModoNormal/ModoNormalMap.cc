// Bridge a tangent-space map to Moonshine's render-space NormalMap interface.
#include "attributes.cc"
#include "ModoNormalMap_ispc_stubs.h"
#include <moonray/rendering/shading/MapApi.h>
using namespace scene_rdl2::math;
using namespace moonray::shading;
RDL2_DSO_CLASS_BEGIN(ModoNormalMap, scene_rdl2::rdl2::NormalMap)
public:
    ModoNormalMap(const scene_rdl2::rdl2::SceneClass& sc,const std::string& name):Parent(sc,name) {
        mSampleNormalFunc=sampleNormal;
        mSampleNormalFuncv=(scene_rdl2::rdl2::SampleNormalFuncv)ispc::ModoNormalMap_getSampleFunc();
    }
    void update() override {}
    static void sampleNormal(const scene_rdl2::rdl2::NormalMap* self,TLState* tls,const State& state,Vec3f* out) {
        const auto* me=static_cast<const ModoNormalMap*>(self);
        if(isZero(length(state.getdPds()))) { *out=state.getN();return; }
        ReferenceFrame frame(state.getN(),normalize(state.getdPds()));
        *out=normalize(frame.localToGlobal(evalVec3f(me,attrInput,tls,state)));
    }
RDL2_DSO_CLASS_END(ModoNormalMap)
