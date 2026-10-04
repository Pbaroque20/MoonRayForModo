"""Install opt-in active tile telemetry; repeatable source patch, no renderer tests."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
base=root/'upstream/openmoonray/moonray/moonray'
p=base/'lib/rendering/rndr/RenderFramePasses.cc'
s=p.read_text(encoding='utf-8')
if 'ModoBucketScope' not in s:
    anchor='    const Pass &pass = driver->mTileWorkQueue.getPass(group.mPassIdx);'
    start=s.index('RenderDriver::renderTile(RenderDriver *driver,')
    index=s.index(anchor,start)
    s=s[:index]+"""    const auto& modoTile=(*driver->getTiles())[params.mTileIdx];
    ModoBucketScope modoBucket(tls->mThreadIdx,modoTile.mMinX,modoTile.mMinY,modoTile.mMaxX,modoTile.mMaxY);
"""+s[index:]
    s='#define MODO_BUCKET_IMPLEMENTATION\n#include "modo_bucket_tracker.h"\n'+s
    p.write_bytes(s.encode('utf-8'))
if '#define MODO_BUCKET_IMPLEMENTATION' not in s:
    s='#define MODO_BUCKET_IMPLEMENTATION\n'+s
    p.write_bytes(s.encode('utf-8'))
p=base/'cmd/raas_cmd/moonray/moonray.cc'
s=p.read_text(encoding='utf-8')
if '#include "modo_bucket_output.h"' not in s:
    s='#include "modo_bucket_output.h"\n'+s
    anchor='        printStatusLine(renderContext, driver->getLastFrameMcrtStartTime(), false);'
    assert anchor in s
    s=s.replace(anchor,anchor+'\n        modoBucketOutput("0",driver->getWidth(),driver->getHeight());')
    p.write_bytes(s.encode('utf-8'))
print('Active tile telemetry source enabled')

# Upstream BATCH hard-codes Morton. Use the supported scene setting also
# exported for progressive previews, rather than an undeclared batch attribute.
p=base/'lib/rendering/rndr/RenderContext.cc'
s=p.read_text(encoding='utf-8')
old='case RenderMode::BATCH:\n        fs->mTileSchedulerType = TileScheduler::MORTON;'
new='case RenderMode::BATCH:\n        fs->mTileSchedulerType = (unsigned)vars.get(scene_rdl2::rdl2::SceneVariables::sProgressiveTileOrder);'
if old in s:
    s=s.replace(old,new,1)
    p.write_bytes(s.encode('utf-8'))
elif new not in s:
    raise RuntimeError('Batch scheduler source changed; cannot apply tile-order setting safely')

# Schedule contiguous 256px buckets while retaining MoonRay's required 8px
# film/SIMD tiles. The selected traversal orders buckets and their inner tiles.
p=base/'lib/rendering/rndr/TileScheduler.cc'
s=p.read_text(encoding='utf-8')
anchor='    generateTileIndices(arena, numTilesX, numTilesY, mTileIndices.get(), uint32_t(mRenderNodeIdx));'
if 'Modo 256px scheduling buckets' not in s:
    assert anchor in s
    s=s.replace(anchor,anchor+"""

    // Modo 256px scheduling buckets; do not change the 8x8 film storage.
    const unsigned bucketTiles = 32;
    const unsigned offsetX = (unsigned(viewport.mMinX) >> 3) % bucketTiles;
    const unsigned offsetY = (unsigned(viewport.mMinY) >> 3) % bucketTiles;
    const unsigned bucketsX = (offsetX + numTilesX + bucketTiles - 1) / bucketTiles;
    const unsigned bucketsY = (offsetY + numTilesY + bucketTiles - 1) / bucketTiles;
    std::vector<uint32_t> bucketOrder(bucketsX * bucketsY);
    generateTileIndices(arena, bucketsX, bucketsY, bucketOrder.data(), uint32_t(mRenderNodeIdx));
    std::vector<uint32_t> orderedTiles(numTiles);
    for (unsigned i = 0; i < numTiles; ++i) orderedTiles[i] = i;
    auto bucketRank = [&](unsigned i) {
        return bucketOrder[((i / numTilesX + offsetY) / bucketTiles) * bucketsX +
                           ((i % numTilesX + offsetX) / bucketTiles)];
    };
    std::sort(orderedTiles.begin(), orderedTiles.end(), [&](unsigned a, unsigned b) {
        unsigned ba = bucketRank(a), bb = bucketRank(b);
        return ba == bb ? mTileIndices[a] < mTileIndices[b] : ba < bb;
    });
    for (unsigned rank = 0; rank < numTiles; ++rank) mTileIndices[orderedTiles[rank]] = rank;
""",1)
    p.write_bytes(s.encode('utf-8'))

# Upgrade both existing 256px patches and clean builds to resolution-aware sizing.
s=p.read_text(encoding='utf-8')
if '#include "modo_bucket_size.h"' not in s:s='#include "modo_bucket_size.h"\n'+s
s=s.replace('const unsigned bucketTiles = 32;', 'const unsigned bucketTiles = modoBucketSize(width,height) / 8;')
p.write_bytes(s.encode('utf-8'))
