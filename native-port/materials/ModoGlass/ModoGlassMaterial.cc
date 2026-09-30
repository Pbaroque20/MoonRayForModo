// MoonRayForModo glass adapter. Uses MoonRay's Fresnel-coupled dielectric BSDFs.
#include "attributes.cc"
#include "labels.h"
#include "ModoGlassMaterial_ispc_stubs.h"
#include <moonray/rendering/shading/MaterialApi.h>
using namespace moonray::shading;
using namespace scene_rdl2::math;

RDL2_DSO_CLASS_BEGIN(ModoGlassMaterial, scene_rdl2::rdl2::Material)
public:
    ModoGlassMaterial(const scene_rdl2::rdl2::SceneClass& sc, const std::string& name);
    void update() override {}
    static void shade(const scene_rdl2::rdl2::Material*, TLState*, const State&, BsdfBuilder&);
    static float presence(const scene_rdl2::rdl2::Material*, TLState*, const State&);
private:
    ispc::ModoGlassMaterial mIspc;
RDL2_DSO_CLASS_END(ModoGlassMaterial)

ModoGlassMaterial::ModoGlassMaterial(const scene_rdl2::rdl2::SceneClass& sc, const std::string& name)
    : Parent(sc, name) {
    mShadeFunc = shade;
    mShadeFuncv = (scene_rdl2::rdl2::ShadeFuncv)ispc::ModoGlassMaterial_getShadeFunc();
    mPresenceFunc = presence;
}
float ModoGlassMaterial::presence(const scene_rdl2::rdl2::Material* self, TLState* tls, const State& state) {
    return saturate(evalFloat(static_cast<const ModoGlassMaterial*>(self), attrPresence, tls, state));
}
void ModoGlassMaterial::shade(const scene_rdl2::rdl2::Material* self, TLState* tls,
                              const State& state, BsdfBuilder& builder) {
    const auto* me = static_cast<const ModoGlassMaterial*>(self);
    const Vec3f N = state.getN();
    const float ior = max(1.0f, evalFloat(me, attrIor, tls, state));
    const float transmission = saturate(evalFloat(me, attrTransmission, tls, state));
    const float roughness = saturate(evalFloat(me, attrRoughness, tls, state));
    const float refractionRoughness = saturate(evalFloat(me, attrRefractionRoughness, tls, state));
    const Color tint = evalColor(me, attrTransmissionColor, tls, state);
    if (isZero(roughness) && isZero(refractionRoughness)) {
        const MirrorBSDF glass(N, ior, tint, 0.0f, ior, 1.0f, transmission);
        builder.addMirrorBSDF(glass, 1.0f, ispc::BSDFBUILDER_PHYSICAL, aovReflection, aovTransmission);
    } else {
        const MicrofacetIsotropicBSDF glass(N, ior, roughness, refractionRoughness,
            ispc::MICROFACET_DISTRIBUTION_GGX, ispc::MICROFACET_GEOMETRIC_SMITH,
            tint, 0.0f, ior, 1.0f, transmission);
        builder.addMicrofacetIsotropicBSDF(glass, 1.0f, ispc::BSDFBUILDER_PHYSICAL, aovReflection, aovTransmission);
    }
    const Color diffuse = evalColor(me, attrDiffuseColor, tls, state) * (1.0f - transmission);
    if (!isBlack(diffuse)) {
        const LambertianBRDF lobe(N, diffuse);
        builder.addLambertianBRDF(lobe, 1.0f, ispc::BSDFBUILDER_PHYSICAL, aovDiffuse);
    }
    builder.addEmission(evalColor(me, attrEmissiveColor, tls, state));
}
