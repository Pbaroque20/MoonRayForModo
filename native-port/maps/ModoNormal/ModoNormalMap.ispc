#include "attributes.isph"
#include <moonray/rendering/shading/ispc/MapApi.isph>
static Vec3f sampleNormal(const uniform NormalMap* uniform me,uniform ShadingTLState* uniform tls,const varying State& state) {
    if(isZero(length(state.mdPds))) return getN(state);
    ReferenceFrame frame=ReferenceFrame_ctor(getN(state),normalize(state.mdPds));
    return normalize(localToGlobal(frame,evalAttrInput(me,tls,state)));
}
DEFINE_NORMALMAP_SHADER(ModoNormalMap,sampleNormal)
