// The ocean's short waves as a shading normal, in MoonRay's vector and XPU modes: as ModoOceanNormalMap.cc.
#include "attributes.isph"
#include <moonray/rendering/shading/ispc/MapApi.isph>
#include <moonray/rendering/shading/ispc/Xform.isph>
struct ModoOceanNormalMap { const uniform Xform * uniform mXform; };
ISPC_UTIL_EXPORT_UNIFORM_STRUCT_TO_HEADER(ModoOceanNormalMap);
static Vec3f sampleNormal(const uniform NormalMap* uniform map, uniform ShadingTLState* uniform tls, const varying State& state) {
    const uniform ModoOceanNormalMap* uniform me = NORMALMAP_GET_ISPC_PTR(ModoOceanNormalMap, map);
    const Vec3f N = getN(state);
    if (isZero(length(state.mdPds))) return N;
    const Color c = evalAttrInput(map, tls, state);
    Vec3f t = Vec3f_ctor(2.0f * c.r - 1.0f, 2.0f * c.g - 1.0f, 2.0f * c.b - 1.0f);
    const uniform float dial = clamp(getAttrDial(map), 0.0f, 1.0f);
    t = Vec3f_ctor(t.x * dial, t.y * dial, 1.0f + (t.z - 1.0f) * dial);
    if (isZero(length(t))) return N;
    ReferenceFrame frame = ReferenceFrame_ctor(N, normalize(state.mdPds));
    Vec3f n = normalize(localToGlobal(frame, t));
    Vec3f up = transformVector(me->mXform, SHADING_SPACE_WORLD, SHADING_SPACE_RENDER, state, Vec3f_ctor(0.0f, 1.0f, 0.0f));
    const float upLength = length(up);
    const Vec3f wo = state.mWo;
    if (upLength > 1e-6f) {
        up = up / upLength;
        const uniform float horizon = getAttrHorizon(map);
        if (dot(wo, up) > 0.0f) {
            const Vec3f r = 2.0f * dot(n, wo) * n - wo;
            const float h = dot(r, up);
            if (h < horizon) {
                const Vec3f bent = normalize(r + (horizon - h) * up);
                const Vec3f half = wo + bent;
                const float l = length(half);
                if (l > 1e-6f) n = half / l;
            }
        }
    }
    return n;
}
DEFINE_NORMALMAP_SHADER(ModoOceanNormalMap, sampleNormal)
