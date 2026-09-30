// Vectorized counterpart of ModoGlassMaterial.cc, compiled for AVX1.
#include "attributes.isph"
#include "labels.isph"
#include <moonray/rendering/shading/ispc/MaterialApi.isph>
struct ModoGlassMaterial { uniform int mReserved; };
ISPC_UTIL_EXPORT_UNIFORM_STRUCT_TO_HEADER(ModoGlassMaterial);

static void shade(const uniform Material * uniform me, uniform ShadingTLState * uniform tls,
                  const varying State& state, varying BsdfBuilder& builder) {
    Vec3f N = getN(state);
    if (!isZero(length(state.mdPds))) {
        const ReferenceFrame frame = ReferenceFrame_ctor(N, normalize(state.mdPds));
        N = normalize(localToGlobal(frame, evalAttrNormal(me, tls, state)));
    }
    const float ior = max(1.0f, evalAttrIor(me, tls, state));
    const float transmission = saturate(evalAttrTransmission(me, tls, state));
    const float roughness = saturate(evalAttrRoughness(me, tls, state));
    const float refractionRoughness = saturate(evalAttrRefractionRoughness(me, tls, state));
    const Color tint = evalAttrTransmissionColor(me, tls, state);
    if (isZero(roughness) && isZero(refractionRoughness)) {
        MirrorBSDF glass;
        MirrorBSDF_init(glass, N, ior, tint, 0.0f, ior, 1.0f, transmission);
        BsdfBuilder_addMirrorBSDF(builder, glass, 1.0f, BSDFBUILDER_PHYSICAL, aovReflection, aovTransmission);
    } else {
        MicrofacetIsotropicBSDF glass;
        MicrofacetIsotropicBSDF_init(glass, N, ior, roughness, refractionRoughness,
            MICROFACET_DISTRIBUTION_GGX, MICROFACET_GEOMETRIC_SMITH, tint, 0.0f, ior, 1.0f, transmission);
        BsdfBuilder_addMicrofacetIsotropicBSDF(builder, glass, 1.0f, BSDFBUILDER_PHYSICAL,
                                             aovReflection, aovTransmission);
    }
    const Color diffuse = evalAttrDiffuseColor(me, tls, state) * (1.0f - transmission);
    if (!isBlack(diffuse)) {
        LambertianBRDF lobe;
        LambertianBRDF_init(lobe, N, diffuse);
        BsdfBuilder_addLambertianBRDF(builder, lobe, 1.0f, BSDFBUILDER_PHYSICAL, aovDiffuse);
    }
    BsdfBuilder_addEmission(builder, evalAttrEmissiveColor(me, tls, state));
}
DEFINE_MATERIAL_SHADER(ModoGlassMaterial, shade)
