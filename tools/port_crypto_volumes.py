"""Fog in Cryptomatte: the volumes a camera ray passes through get mattes of their own, and what lies behind them is
covered only as much as shows through.

MoonRay's Cryptomatte records the surface a camera ray (or a presence continuation of it) hits, at the full weight of
that ray, and never the volumes on the way: a cloud has no matte, and the surface behind a thick cloud has as much
matte as one in the clear, so the mattes in a pixel add up to more than its alpha.

Only when MoonRay is started with MOONRAY_MODO_CRYPTO_VOLUMES=1 (the plugin's preference):

1. As the frame starts, each assignment that holds a volume shader is looked up in the layer, and its geometry's
   "primitive_attributes" UserData read for the Cryptomatte IDs the plugin gives surfaces: the first deep ID attribute
   (the object ID), "modo_material_id" and "modo_asset_id". VdbGeometry takes "primitive_attributes" for this; it reads
   nothing else from them.
2. At the end of a camera ray's march through volumes (scalar, vector and XPU all march in C++), each step's share of
   the opacity, by luminance of its extinction as MoonRay's own volume "surface" depth has it, goes to the volume that
   is densest in that step. Each volume is recorded once per ray with that share as its coverage, at the depth where
   its share is centred, facing the camera, with the volume's light as its beauty. A ray stopped by the transmittance
   threshold gives what is left to the last volume.
3. The surface the ray then hits, and a presence surface, are recorded at their weight times what shows through the
   volumes before them: per thread for a scalar camera sample, and in the ray's CryptomatteData for vector and XPU,
   where it takes 16 bits of the presence depth (which is never more than a few hundred).

Without the variable, MoonRay renders exactly as its source does."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOONRAY = ROOT / 'upstream/openmoonray/moonray/moonray'
RENDERING = MOONRAY / 'lib/rendering'

HEADER = 'pbr/integrator/ModoCryptoVolumes.h'
HEADER_TEXT = '''// Modo: fog in Cryptomatte (tools/port_crypto_volumes.py).
#pragma once

#include <scene_rdl2/scene/rdl2/rdl2.h>

#include <cstdlib>
#include <string>
#include <vector>

namespace moonray {
namespace pbr {

/// True when MoonRay was started with MOONRAY_MODO_CRYPTO_VOLUMES=1. Read once.
inline bool modoCryptoVolumes()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_CRYPTO_VOLUMES");
        return value && value[0] == '1';
    }();
    return on;
}

/// A volume's Cryptomatte IDs, as the plugin gives them to its geometry.
struct ModoCryptoIds
{
    bool mValid = false;
    float mId = 0.f;
    float mMaterialId = 0.f;
    float mAssetId = 0.f;
};

/// The IDs of each assignment that holds a volume shader, by assignment ID. Built as the frame starts.
inline std::vector<ModoCryptoIds>& modoCryptoVolumeTable()
{
    static std::vector<ModoCryptoIds> table;
    return table;
}

inline const ModoCryptoIds* modoCryptoVolumeIds(int assignmentId)
{
    const std::vector<ModoCryptoIds> &table = modoCryptoVolumeTable();
    if (assignmentId < 0 || size_t(assignmentId) >= table.size() || !table[assignmentId].mValid) {
        return nullptr;
    }
    return &table[assignmentId];
}

/// For a scalar camera sample: how much of what lies behind the volumes passed so far shows through.
inline float& modoCryptoVolumeFront()
{
    static thread_local float front = 1.f;
    return front;
}

inline bool modoReadCryptoId(const scene_rdl2::rdl2::SceneObjectVector &data, const std::string &key, float &value)
{
    for (const scene_rdl2::rdl2::SceneObject *object : data) {
        const scene_rdl2::rdl2::UserData *userData = object ? object->asA<scene_rdl2::rdl2::UserData>() : nullptr;
        if (userData && userData->hasFloatData() && userData->getFloatKey() == key &&
            !userData->getFloatValues().empty()) {
            value = userData->getFloatValues()[0];
            return true;
        }
    }
    return false;
}

inline void modoCryptoVolumesBuild(const scene_rdl2::rdl2::Layer *layer, const scene_rdl2::rdl2::StringVector &idNames)
{
    std::vector<ModoCryptoIds> &table = modoCryptoVolumeTable();
    table.clear();
    if (!modoCryptoVolumes() || !layer) {
        return;
    }
    const std::string objectKey = idNames.empty() ? std::string("modo_object_id") : idNames[0];
    const int count = layer->getAssignmentCount();
    table.resize(count > 0 ? count : 0);
    for (int i = 0; i < count; ++i) {
        if (!layer->lookupVolumeShader(i)) {
            continue;
        }
        const scene_rdl2::rdl2::Geometry *geometry = layer->lookupGeomAndPart(i).first;
        if (!geometry) {
            continue;
        }
        scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::SceneObjectVector> key;
        try {
            key = geometry->getSceneClass().getAttributeKey<scene_rdl2::rdl2::SceneObjectVector>("primitive_attributes");
        } catch (...) {
            continue;
        }
        const scene_rdl2::rdl2::SceneObjectVector &data = geometry->get(key);
        ModoCryptoIds &ids = table[i];
        ids.mValid = modoReadCryptoId(data, objectKey, ids.mId);
        modoReadCryptoId(data, "modo_material_id", ids.mMaterialId);
        modoReadCryptoId(data, "modo_asset_id", ids.mAssetId);
    }
}

} // namespace pbr
} // namespace moonray
'''

RECORD = '''
namespace {

// Modo: the volumes a camera ray passes through, each recorded in Cryptomatte with the share of the opacity it gives,
// and what shows through them kept for the surface behind (tools/port_crypto_volumes.py).
void
modoRecordCryptoVolumes(pbr::TLState *pbrTls, const mcrt_common::Ray &ray, const Subpixel &sp, const PathVertex &pv,
                        const RayState *rs, const VolumeProperties *volumeProperties, size_t stepCount, bool opaque,
                        const scene_rdl2::math::Color &volumeRadiance)
{
    CryptomatteBuffer *buffer = nullptr;
    CryptomatteData *data = nullptr;
    if (rs) {
        if (rs->mCryptomatteDataHandle == nullHandle) {
            return;
        }
        data = static_cast<CryptomatteData *>(pbrTls->getListItem(rs->mCryptomatteDataHandle, 0));
        buffer = data->mCryptomatteBuffer;
    } else {
        buffer = static_cast<CryptomatteBuffer *>(sp.mCryptomatteBuffer);
    }
    if (!buffer || stepCount == 0) {
        return;
    }
    const float front = data ? data->volumeFront() : modoCryptoVolumeFront();

    struct Share { int mAssignmentId; float mCoverage; float mDepth; };
    constexpr int maxShares = 16;
    Share shares[maxShares];
    int shareCount = 0;
    auto add = [&](int assignmentId, float coverage, float depth) {
        if (coverage <= 0.f) {
            return;
        }
        for (int i = 0; i < shareCount; ++i) {
            if (shares[i].mAssignmentId == assignmentId) {
                shares[i].mCoverage += coverage;
                shares[i].mDepth += coverage * depth;
                return;
            }
        }
        if (shareCount < maxShares) {
            shares[shareCount++] = {assignmentId, coverage, coverage * depth};
        }
    };

    float shown = 1.f;
    for (size_t i = 0; i < stepCount; ++i) {
        const VolumeProperties &step = volumeProperties[i];
        const float sigmaT = scene_rdl2::math::luminance(step.mSigmaT);
        const float covered = shown * (1.f - std::exp(-sigmaT * step.mDelta));
        add(step.mAssignmentId, covered, step.mTStart + 0.5f * step.mDelta);
        shown -= covered;
    }
    if (opaque) {
        const VolumeProperties &last = volumeProperties[stepCount - 1];
        add(last.mAssignmentId, shown, last.mTStart + last.mDelta);
        shown = 0.f;
    }
    shown = scene_rdl2::math::clamp(shown, 0.f, 1.f);

    const float weight = pv.pathPixelWeight * front;
    const float opacity = 1.f - shown;
    if (weight > 0.f && opacity > 0.f) {
        unsigned px, py;
        uint32ToPixelLocation(sp.mPixel, &px, &py);
        const scene_rdl2::math::Color light = volumeRadiance / scene_rdl2::math::max(weight * opacity, 0.01f);
        const scene_rdl2::math::Color4 beauty(light.r, light.g, light.b, 1.f);
        const scene_rdl2::math::Vec3f normal = -scene_rdl2::math::normalize(ray.getDirection());
        const unsigned presenceDepth = pv.presenceDepth > 0 ? unsigned(pv.presenceDepth) : 0u;
        for (int i = 0; i < shareCount; ++i) {
            const ModoCryptoIds *ids = modoCryptoVolumeIds(shares[i].mAssignmentId);
            if (!ids) {
                continue;
            }
            const scene_rdl2::math::Vec3f position = ray.getOrigin() +
                ray.getDirection() * (shares[i].mDepth / shares[i].mCoverage);
            buffer->addSampleVector(px, py, ids->mId, weight * shares[i].mCoverage, position, normal, beauty,
                                    position, scene_rdl2::math::Vec3f(0.f), normal, scene_rdl2::math::Vec2f(0.f),
                                    presenceDepth, true, ids->mMaterialId, ids->mAssetId);
        }
    }

    if (data) {
        data->setVolumeFront(front * shown);
    } else {
        modoCryptoVolumeFront() = front * shown;
    }
}

} // namespace

bool
PathIntegrator::computeRadianceVolume('''

EDITS = {
    'pbr/Types.hh': [
        ('''    HUD_MEMBER(int32_t, mPresenceDepth);                            \\
''', '''    HUD_MEMBER(int16_t, mPresenceDepth);                            \\
    HUD_MEMBER(uint16_t, mVolumeFront); /* Modo: what shows through the volumes before, 0-65535 */ \\
'''),
        ('''    HUD_VALIDATE(CryptomatteData, mPresenceDepth);      \\
''', '''    HUD_VALIDATE(CryptomatteData, mPresenceDepth);      \\
    HUD_VALIDATE(CryptomatteData, mVolumeFront);        \\
'''),
    ],
    'pbr/Types.h': [
        ('''    static uint32_t hudValidation(bool verbose) { CRYPTOMATTE_DATA_VALIDATION; }
    void init(CryptomatteBuffer* buffer) {
''', '''    static uint32_t hudValidation(bool verbose) { CRYPTOMATTE_DATA_VALIDATION; }
    // Modo: how much of what lies behind the volumes this ray has passed shows through (tools/port_crypto_volumes.py).
    float volumeFront() const { return float(mVolumeFront) * (1.f / 65535.f); }
    void setVolumeFront(float front) {
        mVolumeFront = uint16_t((front < 0.f ? 0.f : front > 1.f ? 1.f : front) * 65535.f + 0.5f);
    }
    void init(CryptomatteBuffer* buffer) {
'''),
        ('''        mPresenceDepth = -1;                        // presence depth, -1 indicates that this isn't a presence path
''', '''        mPresenceDepth = -1;                        // presence depth, -1 indicates that this isn't a presence path
        mVolumeFront = 65535;                       // Modo: no volume before yet
'''),
    ],
    'pbr/integrator/PathIntegrator.cc': [
        ('''#include <moonray/rendering/pbr/core/Cryptomatte.h>
''', '''#include <moonray/rendering/pbr/core/Cryptomatte.h>
#include "ModoCryptoVolumes.h"
'''),
        ('''    mCryptoIdAttrIdx = mDeepIDAttrIdxs.empty() ? -1 : mDeepIDAttrIdxs[0];
''', '''    mCryptoIdAttrIdx = mDeepIDAttrIdxs.empty() ? -1 : mDeepIDAttrIdxs[0];
    modoCryptoVolumesBuild(scene->getLayer(), attrNames);
'''),
        ('''        if (deepParams) deepParams->mHitVolume = hitVolume;
        pv.pathThroughput *= vt.transmittance();
    }
''', '''        if (deepParams) deepParams->mHitVolume = hitVolume;
        pv.pathThroughput *= vt.transmittance();
    }
    // Modo: what shows through the volumes before this surface, for its Cryptomatte coverage.
    const float modoCryptoFront = modoCryptoVolumes() ? modoCryptoVolumeFront() : 1.f;
'''),
        ('''            ((CryptomatteBuffer *)sp.mCryptomatteBuffer)->addSampleScalar(px, py, pv.pathPixelWeight,
''', '''            ((CryptomatteBuffer *)sp.mCryptomatteBuffer)->addSampleScalar(px, py, pv.pathPixelWeight * modoCryptoFront,
'''),
        ('''    sp.mCryptomatteBuffer = (void *)cryptomatteBuffer;
''', '''    sp.mCryptomatteBuffer = (void *)cryptomatteBuffer;
    modoCryptoVolumeFront() = 1.f;
'''),
    ],
    'pbr/integrator/PathIntegratorVolume.cc': [
        ('''#include <moonray/rendering/pbr/core/Constants.h>
''', '''#include <moonray/rendering/pbr/core/Constants.h>
#include <moonray/rendering/pbr/core/Cryptomatte.h>
#include "ModoCryptoVolumes.h"
'''),
        ('''
bool
PathIntegrator::computeRadianceVolume(''', RECORD),
        ('''        float* surfaceT) const
{
    EXCL_ACCUMULATOR_PROFILE(pbrTls, EXCL_ACCUM_VOL_INTEGRATION);

    vt.reset();
''', '''        float* surfaceT) const
{
    EXCL_ACCUMULATOR_PROFILE(pbrTls, EXCL_ACCUM_VOL_INTEGRATION);

    vt.reset();
    const scene_rdl2::math::Color modoRadianceBefore = radiance;
'''),
        ('''                rayMask, sequenceID, aovs, deepParams, rs);
        }
    }

    return true;
}
''', '''                rayMask, sequenceID, aovs, deepParams, rs);
        }
    }

    if (modoCryptoVolumes() && ray.getDepth() == 0 && lobeType == 0) {
        modoRecordCryptoVolumes(pbrTls, ray, sp, pv, rs, volumeProperties, marchingStepsCount,
                                reachTransmittanceThreshold, radiance - modoRadianceBefore);
    }

    return true;
}
'''),
    ],
    'pbr/handlers/ShadeBundleHandler.cc': [
        ('''                            cryptomatteDataNext->mCryptomatteBuffer = cryptomatteData->mCryptomatteBuffer;
''', '''                            cryptomatteDataNext->mCryptomatteBuffer = cryptomatteData->mCryptomatteBuffer;
                            cryptomatteDataNext->setVolumeFront(cryptomatteData->volumeFront());
'''),
        ('''                                cryptomatteData->mCryptomatteBuffer->addSampleVector(px, py, cryptomatteData->mId,''' + ' ' + '''
                                                                                    rs->mPathVertex.pathPixelWeight,
''', '''                                cryptomatteData->mCryptomatteBuffer->addSampleVector(px, py, cryptomatteData->mId,''' + ' ' + '''
                                                                                    rs->mPathVertex.pathPixelWeight * cryptomatteData->volumeFront(),
'''),
        ('''                            cryptomatteData->mCryptomatteBuffer->addSampleVector(px, py, cryptomatteData->mId,''' + ' ' + '''
                                                                                rs->mPathVertex.pathPixelWeight,
''', '''                            cryptomatteData->mCryptomatteBuffer->addSampleVector(px, py, cryptomatteData->mId,''' + ' ' + '''
                                                                                rs->mPathVertex.pathPixelWeight * cryptomatteData->volumeFront(),
'''),
    ],
    'rndr/Film.cc': [
        ('''                            film.mCryptomatteBuf->addSampleVector(px, py, id, 1.f, position, normal, beauty,
''', '''                            film.mCryptomatteBuf->addSampleVector(px, py, id, cryptomatteData->volumeFront(), position, normal, beauty,
'''),
    ],
}

VDB_EDITS = [
    ('''    rdl2::AttributeKey<rdl2::Float>  attrEmissionSampleRate;
''', '''    rdl2::AttributeKey<rdl2::Float>  attrEmissionSampleRate;
    rdl2::AttributeKey<rdl2::SceneObjectVector> attrPrimitiveAttributes;
'''),
    ('''    sceneClass.setGroup("VDB", attrEmissionSampleRate);
''', '''    sceneClass.setGroup("VDB", attrEmissionSampleRate);

    // Modo: what the plugin gives a VDB for Cryptomatte to read its IDs from (tools/port_crypto_volumes.py).
    attrPrimitiveAttributes =
        sceneClass.declareAttribute<rdl2::SceneObjectVector>("primitive_attributes", { "primitive attributes" });
    sceneClass.setMetadata(attrPrimitiveAttributes, "label", "primitive attributes");
    sceneClass.setMetadata(attrPrimitiveAttributes, "comment",
        "Vector of UserData. Read only for the volume's Cryptomatte IDs.");
    sceneClass.setGroup("User Data", attrPrimitiveAttributes);
'''),
]


def patch_text(name, text, edits):
    for old, new in edits:
        for ending in ('\n', '\r\n'):
            o, n = old.replace('\n', ending), new.replace('\n', ending)
            if n in text:
                break
            if text.count(o) == 1:
                text = text.replace(o, n, 1)
                break
        else:
            raise RuntimeError('Crypto volume anchor missing or ambiguous in %s: %r' % (name, old[:70]))
    return text


def patch_file(source, label, edits):
    text = source.read_bytes().decode('utf-8')
    patched = patch_text(label, text, edits)
    if patched != text:
        source.write_bytes(patched.encode('utf-8'))
        print('patched', label)
    else:
        print('already in', label)


def main():
    header = RENDERING / HEADER
    if not header.exists() or header.read_text(encoding='utf-8') != HEADER_TEXT:
        header.write_text(HEADER_TEXT, encoding='utf-8')
        print('wrote', HEADER)
    for name, edits in EDITS.items():
        patch_file(RENDERING / name, name, edits)
    patch_file(MOONRAY / 'dso/geometry/Vdb/attributes.cc', 'dso/geometry/Vdb/attributes.cc', VDB_EDITS)


if __name__ == '__main__':
    main()
