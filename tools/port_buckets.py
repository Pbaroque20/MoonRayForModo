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
