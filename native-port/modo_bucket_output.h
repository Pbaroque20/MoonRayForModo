#pragma once
#include "modo_bucket_tracker.h"
#include "modo_bucket_size.h"
#include <sstream>
#include <cstdlib>
#include <iostream>
#include <set>
#include <algorithm>
inline void modoBucketOutput(const std::string& generation,unsigned width,unsigned height) {
    const char* enabled=std::getenv("MOONRAY_MODO_BUCKETS");
    if(!enabled || enabled[0]!='1') return;
    uint64_t rectangles[512];
    unsigned count=modoBucketSnapshot(rectangles,512);
    std::ostringstream line;
    line << "\n@@MODO_TILES " << generation << " " << width << " " << height;
    // Report occupied scheduling buckets, not invented progress percentages.
    std::set<uint64_t> active;
    const unsigned size=modoBucketSize(width,height);
    for(unsigned i=0;i<count;++i) {
        auto r=rectangles[i];
        unsigned x0=unsigned(r&65535)/size*size;
        unsigned y0=unsigned((r>>16)&65535)/size*size;
        unsigned x1=std::min(x0+size,width),y1=std::min(y0+size,height);
        active.insert(uint64_t(x0)|(uint64_t(y0)<<16)|(uint64_t(x1)<<32)|(uint64_t(y1)<<48));
    }
    for(auto r:active) {
        line << " " << (r&65535) << "," << ((r>>16)&65535) << "," << ((r>>32)&65535) << "," << ((r>>48)&65535);
    }
    std::cout << line.str() << std::endl;
}
