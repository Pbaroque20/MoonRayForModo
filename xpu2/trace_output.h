// Shared across diagnostic translation units; separate from renderer progress.
#pragma once
#include <cstdio>
#include <cstdlib>
inline FILE* xpu2TraceOutput()
{
    static FILE* stream=[]() {
        const char* path=std::getenv("XPU2_TRACE_FILE");
        if (!path || !*path) return stderr;
        FILE* file=std::fopen(path,"w");
        if (!file) std::fprintf(stderr,"XPU2: cannot open diagnostic trace file\n");
        return file ? file : stderr;
    }();
    return stream;
}

#include <cmath>
#include <limits>
struct Xpu2SurfaceNormal { float x=0,y=0,z=0; bool valid=false; };
inline Xpu2SurfaceNormal* xpu2SurfaceNormals() { static Xpu2SurfaceNormal normals[2]; return normals; }
inline int xpu2PixelSlot(unsigned pixel) {
    return pixel==((77u<<16)|96u) ? 0 : pixel==((96u<<16)|132u) ? 1 : -1;
}
inline void xpu2RememberNormal(unsigned pixel, int sample, int depth, float x,float y,float z) {
    const int slot=xpu2PixelSlot(pixel);
    if (slot<0 || sample!=0 || depth!=0) return;
    const float length=std::sqrt(x*x+y*y+z*z);
    if (!(length>0)) return;
    xpu2SurfaceNormals()[slot]={x/length,y/length,z/length,true};
}
