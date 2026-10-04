"""Reproducible, opt-in native surface Cryptomatte categories (object/material/asset).
Does not implement volume integration. Run explicitly before rebuilding all native targets.
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'upstream/openmoonray/moonray'
pending={}
def edit(rel,old,new,count=1):
 p=BASE/rel;s=pending.get(p,p.read_text(encoding='utf-8'))
 if new in s:return
 if s.count(old)!=count:raise RuntimeError('Unexpected patch anchor count: '+rel+' / '+old[:70])
 pending[p]=s.replace(old,new)
R='scene_rdl2/lib/scene/rdl2/RenderOutput'
edit(R+'.h','    static AttributeKey<Int> sAttrCryptomatteDepth;','    static AttributeKey<Int> sAttrCryptomatteDepth;\n    static AttributeKey<Int> sAttrCryptomatteIdChannel;')
edit(R+'.h','    int getCryptomatteDepth() const;','    int getCryptomatteDepth() const;\n    int getCryptomatteIdChannel() const { return get(sAttrCryptomatteIdChannel); }')
edit(R+'.cc','AttributeKey<Int> RenderOutput::sAttrCryptomatteDepth;','AttributeKey<Int> RenderOutput::sAttrCryptomatteDepth;\nAttributeKey<Int> RenderOutput::sAttrCryptomatteIdChannel;')
edit(R+'.cc','    sAttrCryptomatteDepth = sceneClass.declareAttribute<Int>("cryptomatte_depth", 6);','''    sAttrCryptomatteIdChannel = sceneClass.declareAttribute<Int>("cryptomatte_id_channel", 0);
    sceneClass.setMetadata(sAttrCryptomatteIdChannel, SceneClass::sComment,
                          "Modo surface category: 0 primary deep ID, 1 modo_material_id, 2 modo_asset_id.");
    sAttrCryptomatteDepth = sceneClass.declareAttribute<Int>("cryptomatte_depth", 6);''')
C='moonray/lib/rendering/pbr/core/Cryptomatte'
edit(C+'.h','#include <list>','#include <list>\n#include <memory>\n#include <stdexcept>')
# Only the intersection result needs extra IDs; fragments remain independently ranked.
edit(C+'.h','    bool mHit;\n    float mId;','    bool mHit;\n    float mId;\n    float mMaterialId;\n    float mAssetId;')
edit(C+'.h','void computeCryptomatteResults(', 'void computeCryptomatteCategoryIds(moonray::shading::Intersection &isect, float &material, float &asset);\n\nvoid computeCryptomatteResults(')
edit(C+'.h','    void clear();','''    void clear();
    void resetCategory(unsigned width, unsigned height, bool multiPresenceOn);
    CryptomatteBuffer* categoryBuffer(int index) {
        if (index == mCategoryIndex) return this;
        if (mCategoryIndex == 0 && index > 0 && size_t(index) <= mCategories.size()) return mCategories[index-1].get();
        throw std::runtime_error("Cryptomatte category unavailable; export all three Modo deep ID attributes");
    }
    const CryptomatteBuffer* categoryBuffer(int index) const {
        return const_cast<CryptomatteBuffer*>(this)->categoryBuffer(index);
    }''')
edit(C+'.h','    unsigned mWidth;','    unsigned mWidth;\n    int mCategoryIndex = 0;\n    std::vector<std::unique_ptr<CryptomatteBuffer>> mCategories;')
edit(C+'.h','bool incrementSamples = true);','bool incrementSamples = true, float materialId = 0.f, float assetId = 0.f);')
edit(C+'.h','unsigned depth);','unsigned depth, float materialId = 0.f, float assetId = 0.f);')
edit(C+'.cc','''    MNRY_ASSERT_REQUIRE(numIdChannels == 1);     // Production only wants simple 32-bit ids at present

    mWidth = width;''','''    if (numIdChannels < 1 || numIdChannels > 3) throw std::runtime_error("Cryptomatte supports one to three category channels");
    mCategories.clear();
    resetCategory(width, height, multiPresenceOn);
    for (unsigned channel = 1; channel < numIdChannels; ++channel) {
        std::unique_ptr<CryptomatteBuffer> buffer(new CryptomatteBuffer);
        buffer->mCategoryIndex = channel;
        buffer->resetCategory(width, height, multiPresenceOn);
        mCategories.push_back(std::move(buffer));
    }
}

void CryptomatteBuffer::resetCategory(unsigned width, unsigned height, bool multiPresenceOn)
{
    for (auto &entries : mPixelEntries) entries.clear();
    mWidth = width;''')
edit(C+'.cc','void CryptomatteBuffer::clear()\n{','void CryptomatteBuffer::clear()\n{\n    for (auto &buffer : mCategories) buffer->clear();')
edit(C+'.cc','void computeCryptomatteResults(','''void computeCryptomatteCategoryIds(moonray::shading::Intersection &isect, float &material, float &asset)
{
    static const shading::TypedAttributeKey<float> materialKey("modo_material_id");
    static const shading::TypedAttributeKey<float> assetKey("modo_asset_id");
    material = isect.isProvided(materialKey) ? isect.getAttribute(materialKey) : 0.f;
    asset = isect.isProvided(assetKey) ? isect.getAttribute(assetKey) : 0.f;
}

void computeCryptomatteResults(''')
edit(C+'.cc','    results.mId = 0.0f;','    computeCryptomatteCategoryIds(isect, results.mMaterialId, results.mAssetId);\n    results.mId = 0.0f;')
edit(C+'.cc','    PixelEntry &pixelEntry = mPixelEntries[cryptoType][y * mWidth + x];\n\n    const float                    sampleId',"""    for (auto &buffer : mCategories) {
        CryptomatteResults result = cryptomatteResults;
        result.mId = buffer->mCategoryIndex == 1 ? result.mMaterialId : result.mAssetId;
        buffer->addSampleScalar(x, y, weight, result, beauty, presenceDepth, cryptoType);
    }
    PixelEntry &pixelEntry = mPixelEntries[cryptoType][y * mWidth + x];

    const float                    sampleId""")
edit(C+'.cc','''                                        bool incrementSamples)
{
    // Lock''','''                                        bool incrementSamples, float materialId, float assetId)
{
    for (auto &buffer : mCategories) {
        buffer->addSampleVector(x, y, buffer->mCategoryIndex == 1 ? materialId : assetId, weight,
                                position, normal, beauty, refP, p0, refN, uv, presenceDepth, incrementSamples);
    }
    // Lock''')
edit(C+'.cc','                                              unsigned depth) ', '                                              unsigned depth, float materialId, float assetId) ')
edit(C+'.cc','scene_rdl2::math::Vec2f(0.f), depth, false);','scene_rdl2::math::Vec2f(0.f), depth, false, materialId, assetId);')
edit(C+'.cc','''    if (mFinalized) {
        return;
    }''','''    for (auto &buffer : mCategories) buffer->finalize(samplesCount);
    if (mFinalized) {
        return;
    }''')
edit(C+'.cc','''    if (!mFinalized) {
        return;
    }''','''    for (auto &buffer : mCategories) buffer->unfinalize(samplesCount);
    if (!mFinalized) {
        return;
    }''')
edit(C+'.cc','    // Clamp numLayers so the output string will contain 2 digits 00-99 (per Cryptomatte spec)','''    if (ro.getCryptomatteIdChannel() != mCategoryIndex) {
        categoryBuffer(ro.getCryptomatteIdChannel())->outputFragments(x, y, numLayers, dest, ro);
        return;
    }
    // Clamp numLayers so the output string will contain 2 digits 00-99 (per Cryptomatte spec)''')
T='moonray/lib/rendering/pbr/Types'
edit(T+'.hh','    HUD_MEMBER(uint32_t, mHit);', '    HUD_MEMBER(uint8_t, mHit);')
edit(T+'.hh','    HUD_MEMBER(uint32_t, mPrevPresence);','    HUD_MEMBER(uint8_t, mPrevPresence);                            \\\n    HUD_MEMBER(uint8_t, mIsFirstSample);                           \\\n    HUD_MEMBER(uint8_t, mCryptoPadding);')
edit(T+'.hh','    HUD_MEMBER(float, mId);','    HUD_MEMBER(float, mId);                                         \\\n    HUD_MEMBER(float, mMaterialId);                                 \\\n    HUD_MEMBER(float, mAssetId);')
edit(T+'.hh','    HUD_MEMBER(float, mPathPixelWeight);                            \\\n    HUD_MEMBER(uint32_t, mIsFirstSample)', '    HUD_MEMBER(float, mPathPixelWeight) /* compact category record */')
edit(T+'.hh','    HUD_VALIDATE(CryptomatteData, mId);','    HUD_VALIDATE(CryptomatteData, mId);                 \\\n    HUD_VALIDATE(CryptomatteData, mMaterialId);         \\\n    HUD_VALIDATE(CryptomatteData, mAssetId);            \\\n    HUD_VALIDATE(CryptomatteData, mCryptoPadding);')
edit(T+'.h','        mId = 0;                                    // id for hit','        mId = 0;                                    // id for hit\n        mMaterialId = 0; mAssetId = 0; mCryptoPadding = 0;')
edit(T+'.h','finline void\nuint32ToPixelLocation', 'static_assert(sizeof(CryptomatteData) <= 64, "CryptomatteData must fit the ray allocation cache line");\n\nfinline void\nuint32ToPixelLocation')
S='moonray/lib/rendering/pbr/handlers/ShadeBundleHandler.cc'
edit(S,'                // Retrieve the first deep id (if present)', '                computeCryptomatteCategoryIds(*isect, cryptomatteData->mMaterialId, cryptomatteData->mAssetId);\n                // Retrieve the first deep id (if present)')
# Restrict replacements to the two Cryptomatte sample calls, not other presence APIs.
p=BASE/S;s=pending.get(p,p.read_text(encoding='utf-8'))
import re
pattern=r'(cryptomatteData->mCryptomatteBuffer->addSampleVector\([\s\S]*?rs->mPathVertex.presenceDepth)\);'
s,n=re.subn(pattern,r'\1, true, cryptomatteData->mMaterialId, cryptomatteData->mAssetId);',s)
if n!=2 and 'presenceDepth, true, cryptomatteData->mMaterialId' not in s:raise RuntimeError('Expected two presence sample calls')
pending[p]=s
F='moonray/lib/rendering/rndr/Film.cc'
edit(F,'refP, p0, refN, uv, depth);','refP, p0, refN, uv, depth, true, cryptomatteData->mMaterialId, cryptomatteData->mAssetId);')
edit(F,'addBeautySampleVector(px, py, id, beauty, depth);','addBeautySampleVector(px, py, id, beauty, depth, cryptomatteData->mMaterialId, cryptomatteData->mAssetId);',count=2)
Q='moonray/lib/rendering/rndr/RenderOutputDriverImplRead.cc'
edit(Q,'''            pbr::CryptomatteBuffer* cryptomatteBuf = film.getCryptomatteBuffer();
            cryptomatteBuf->clear();
            cryptomatteBuf->init(reader.getWidth(), reader.getHeight(), 1, cryptomatteBuf->getMultiPresenceOn());''','''            pbr::CryptomatteBuffer* cryptomatteBuf = film.getCryptomatteBuffer()->categoryBuffer(ro->getCryptomatteIdChannel());
            // Reset only this category: other EXR parts may already be restored.
            cryptomatteBuf->resetCategory(reader.getWidth(), reader.getHeight(), cryptomatteBuf->getMultiPresenceOn());''')
changed=0
for p,s in pending.items():
 if p.read_text(encoding='utf-8')!=s:p.write_text(s,encoding='utf-8');changed+=1
print('Native surface Cryptomatte categories patched:',changed,'files. Rebuild required; runtime tests deferred.')
