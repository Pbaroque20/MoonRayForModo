#pragma once
#include <algorithm>
#include <cstdlib>
#include <cstring>
// Keep scheduler and progress telemetry on the same frame-dependent grid.
inline unsigned modoBucketSize(unsigned width,unsigned height) {
    const char* value=std::getenv("MOONRAY_MODO_BUCKET_SIZE");
    if(value) {
        if(std::strcmp(value,"32")==0)return 32;
        if(std::strcmp(value,"64")==0)return 64;
        if(std::strcmp(value,"128")==0)return 128;
        if(std::strcmp(value,"256")==0)return 256;
    }
    const unsigned side=std::min(width,height);
    return side<256 ? 32 : side<512 ? 64 : side<1024 ? 128 : 256;
}
