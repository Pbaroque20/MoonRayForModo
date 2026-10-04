#include <moonray/rendering/rndr/TileScheduler.h>
#include <scene_rdl2/render/util/Arena.h>
#include <set>
#include <vector>
#include <iostream>
#include <stdexcept>
using moonray::rndr::TileScheduler;
void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
int main() try {
    scene_rdl2::util::Ref<scene_rdl2::alloc::ArenaBlockPool> pool=scene_rdl2::util::alignedMallocCtorArgs<scene_rdl2::alloc::ArenaBlockPool>(CACHE_LINE_SIZE);
    scene_rdl2::alloc::Arena arena;arena.init(pool.get());
    unsigned cases=0;
    for(unsigned mode=0;mode<TileScheduler::NUM_TILE_SCHEDULER_TYPES;++mode)
    for(auto view:std::vector<scene_rdl2::math::Viewport>{{0,0,0,0},{0,0,519,280},{13,17,788,517},{259,270,802,602}}) {
        auto scheduler=TileScheduler::create(static_cast<TileScheduler::Type>(mode));
        unsigned width=view.mMaxX+1,height=view.mMaxY+1;
        scheduler->generateTiles(&arena,width,height,view);
        std::set<std::pair<unsigned,unsigned>> completed;
        std::pair<unsigned,unsigned> previous{~0u,~0u};
        std::vector<unsigned> coverage(width*height,0);
        for(const auto& tile:scheduler->getTiles()) {
            check(tile.mMaxX-tile.mMinX<=8 && tile.mMaxY-tile.mMinY<=8,"Changed native tile size");
            auto bucket=std::make_pair(tile.mMinX/256,tile.mMinY/256);
            if(bucket!=previous){check(!completed.count(bucket),"Bucket revisited before pass ended");completed.insert(bucket);previous=bucket;}
            for(unsigned y=tile.mMinY;y<tile.mMaxY;++y)for(unsigned x=tile.mMinX;x<tile.mMaxX;++x)++coverage[y*width+x];
        }
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)
            check(coverage[y*width+x]==unsigned(x>=unsigned(view.mMinX)&&y>=unsigned(view.mMinY)),"Missing, duplicate, or outside-region pixel");
        ++cases;
    }
    std::cout<<cases<<" scheduler/region cases passed; 256px groups contiguous; pixels covered exactly once\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
