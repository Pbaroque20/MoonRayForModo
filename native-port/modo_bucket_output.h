#pragma once
#include "modo_bucket_tracker.h"
#include <sstream>
#include <cstdlib>
#include <iostream>
inline void modoBucketOutput(const std::string& generation,unsigned width,unsigned height) {
    const char* enabled=std::getenv("MOONRAY_MODO_BUCKETS");
    if(!enabled || enabled[0]!='1') return;
    uint64_t rectangles[512];
    unsigned count=modoBucketSnapshot(rectangles,512);
    std::ostringstream line;
    line << "\n@@MODO_TILES " << generation << " " << width << " " << height;
    for(unsigned i=0;i<count;++i) {
        auto r=rectangles[i];
        line << " " << (r&65535) << "," << ((r>>16)&65535) << "," << ((r>>32)&65535) << "," << ((r>>48)&65535);
    }
    std::cout << line.str() << std::endl;
}
