#include <moonray/rendering/rndr/TileScheduler.h>
#include <scene_rdl2/render/util/Arena.h>
#include <set>
#include "modo_bucket_size.h"
#include <vector>
#include <iostream>
#include <stdexcept>
using moonray::rndr::TileScheduler;
void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
int main() try {
    scene_rdl2::util::Ref<scene_rdl2::alloc::ArenaBlockPool> pool=scene_rdl2::util::alignedMallocCtorArgs<scene_rdl2::alloc::ArenaBlockPool>(CACHE_LINE_SIZE);
    scene_rdl2::alloc::Arena arena;arena.init(pool.get());
    unsigned cases=0;
    _putenv_s("MOONRAY_MODO_BUCKET_SIZE","0");
    check(modoBucketSize(240,240)==32,"Tiny preview size");
    check(modoBucketSize(256,384)==64,"Small preview size");
    check(modoBucketSize(512,960)==128,"Medium preview size");
    check(modoBucketSize(1024,2048)==256,"Large render size");
    for(const char* setting:{"0","32","64","128","256"}) {
    _putenv_s("MOONRAY_MODO_BUCKET_SIZE",setting);
    for(unsigned mode=0;mode<TileScheduler::NUM_TILE_SCHEDULER_TYPES;++mode)
    for(auto view:std::vector<scene_rdl2::math::Viewport>{{0,0,0,0},{0,0,255,255},{0,0,383,383},{0,0,511,511},{0,0,1023,1023},{0,0,519,280},{13,17,788,517},{259,270,802,602}}) {
        auto scheduler=TileScheduler::create(static_cast<TileScheduler::Type>(mode));
        unsigned width=view.mMaxX+1,height=view.mMaxY+1;
        scheduler->generateTiles(&arena,width,height,view);
        std::set<std::pair<unsigned,unsigned>> completed;
        std::pair<unsigned,unsigned> previous{~0u,~0u};
        std::vector<unsigned> coverage(width*height,0);
        for(const auto& tile:scheduler->getTiles()) {
            check(tile.mMaxX-tile.mMinX<=8 && tile.mMaxY-tile.mMinY<=8,"Changed native tile size");
            auto bucket=std::make_pair(tile.mMinX/modoBucketSize(width,height),tile.mMinY/modoBucketSize(width,height));
            if(bucket!=previous){check(!completed.count(bucket),"Bucket revisited before pass ended");completed.insert(bucket);previous=bucket;}
            for(unsigned y=tile.mMinY;y<tile.mMaxY;++y)for(unsigned x=tile.mMinX;x<tile.mMaxX;++x)++coverage[y*width+x];
        }
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)
            check(coverage[y*width+x]==unsigned(x>=unsigned(view.mMinX)&&y>=unsigned(view.mMinY)),"Missing, duplicate, or outside-region pixel");
        ++cases;
    }
    }
    _putenv_s("MOONRAY_MODO_BUCKET_SIZE","0");
    std::cout<<cases<<" scheduler/region cases passed; auto/manual groups contiguous; pixels covered exactly once\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
