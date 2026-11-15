// The ocean's short waves as a shading normal, for the kit's Ocean nodes in MoonRay (moonray_modo/nodes.py split_ocean).
// MoonRay dices only the long waves; the shorter ones come as a tangent-space normal map over them. Read as MoonRay's
// ImageNormalMap reads one, the ripples tipped some mirror reflections below the horizon, where a real sea always has
// another wave in the way and the renderer had only the environment's ground (black patches on the water). Here each
// reflection is kept at or above Horizon over the world's horizon (as MoonLightIPR's water looks), by bending the normal
// as MoonRay's adaptNormal bends one toward the surface ("The Iray Light Transport System", A.3), but against the
// world's up. DwaBase's own adaptNormal still follows. The same in the ISPC code (ModoOceanNormalMap.ispc).
#include "attributes.cc"
#include "ModoOceanNormalMap_ispc_stubs.h"
#include <moonray/rendering/shading/MapApi.h>
#include <moonray/rendering/shading/Xform.h>
#include <memory>
using namespace scene_rdl2::math;
using namespace moonray::shading;

RDL2_DSO_CLASS_BEGIN(ModoOceanNormalMap, scene_rdl2::rdl2::NormalMap)
public:
    ispc::ModoOceanNormalMap mData;  // first, where the ISPC code finds it
    std::unique_ptr<Xform> mXform;
    ModoOceanNormalMap(const scene_rdl2::rdl2::SceneClass& sc, const std::string& name) : Parent(sc, name) {
        mSampleNormalFunc = sampleNormal;
        mSampleNormalFuncv = (scene_rdl2::rdl2::SampleNormalFuncv)ispc::ModoOceanNormalMap_getSampleFunc();
    }
    void update() override {
        mXform = std::make_unique<Xform>(this, nullptr, nullptr, nullptr);
        mData.mXform = mXform->getIspcXform();
    }
    static void sampleNormal(const scene_rdl2::rdl2::NormalMap* self, TLState* tls, const State& state, Vec3f* out) {
        const auto* me = static_cast<const ModoOceanNormalMap*>(self);
        const Vec3f N = state.getN();
        if (isZero(length(state.getdPds()))) { *out = N; return; }
        // The tile's normal, 0 to 1, as -1 to 1; the dial toward the surface's own.
        const Color c = evalColor(me, attrInput, tls, state);
        Vec3f t(2.0f * c.r - 1.0f, 2.0f * c.g - 1.0f, 2.0f * c.b - 1.0f);
        const float dial = clamp(me->get(attrDial), 0.0f, 1.0f);
        t = Vec3f(t.x * dial, t.y * dial, 1.0f + (t.z - 1.0f) * dial);
        if (isZero(length(t))) { *out = N; return; }
        const ReferenceFrame frame(N, normalize(state.getdPds()));
        Vec3f n = normalize(frame.localToGlobal(t));
        // The world's up in render space.
        Vec3f up = me->mXform->transformVector(ispc::SHADING_SPACE_WORLD, ispc::SHADING_SPACE_RENDER, state, Vec3f(0.0f, 1.0f, 0.0f));
        const float upLength = length(up);
        const Vec3f wo = state.getWo();
        if (upLength > 1e-6f) {
            up = up / upLength;
            const float horizon = me->get(attrHorizon);
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
        *out = n;
    }
RDL2_DSO_CLASS_END(ModoOceanNormalMap)
