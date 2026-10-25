// Modo's procedural textures in MoonRay's vector and XPU modes: the same patterns as the C++ code (modo_patterns.h).
#include "attributes.isph"
#include "modo_patterns.h"
#include <moonray/rendering/shading/ispc/MapApi.isph>
#include <moonray/rendering/shading/ispc/Xform.isph>
struct ModoProceduralMap { const uniform Xform * uniform mXform; uniform float mSettings[24]; };
ISPC_UTIL_EXPORT_UNIFORM_STRUCT_TO_HEADER(ModoProceduralMap);
static Color sample(const uniform Map* uniform map,uniform ShadingTLState* uniform tls,const varying State& state) {
    const uniform ModoProceduralMap* uniform me=MAP_GET_ISPC_PTR(ModoProceduralMap,map);
    uniform int space=getAttrSpace(map);
    Vec3f p;
    if(space==2) {Vec2f st=getSt(state);p=Vec3f_ctor(st.x,st.y,0.0f);}
    else p=transformPoint(me->mXform,SHADING_SPACE_RENDER,space==1?SHADING_SPACE_OBJECT:SHADING_SPACE_WORLD,state,getP(state));
    uniform Vec4f r0=getAttrRow0(map),r1=getAttrRow1(map),r2=getAttrRow2(map);
    float x=r0.x*p.x+r0.y*p.y+r0.z*p.z+r0.w,y=r1.x*p.x+r1.y*p.y+r1.z*p.z+r1.w,z=r2.x*p.x+r2.y*p.y+r2.z*p.z+r2.w;
    MP_Settings settings;
    for(uniform int i=0;i<24;++i) settings.v[i]=me->mSettings[i];
    float t=mp_pattern(getAttrPattern(map),getAttrType(map),x,y,z,settings);
    if(getAttrOutput(map)==1) {
        uniform float a1=getAttrAlpha1(map),a2=getAttrAlpha2(map);
        float alpha=min(max(a1,a2),max(min(a1,a2),a1*t+a2*(1-t)));
        return Color_ctor(alpha,alpha,alpha);
    }
    Color one=evalAttrColor1(map,tls,state),two=evalAttrColor2(map,tls,state);
    return one*t+two*(1-t);
}
DEFINE_MAP_SHADER(ModoProceduralMap,sample)
