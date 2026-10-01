#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstring>

// Both images contain tightly packed, top-to-bottom linear RGBA float pixels.
inline bool copyPreviewRgba(const float* src, unsigned sw, unsigned sh,
                            float* dst, unsigned dw, unsigned dh) {
    if(!src || !dst || !sw || !sh || !dw || !dh) return false;
    if(sw==dw && sh==dh) {
        std::memcpy(dst,src,static_cast<std::size_t>(sw)*sh*4*sizeof(float));
        return true;
    }
    for(unsigned y=0;y<dh;++y) {
        const double sy=std::max(0.0,std::min(double(sh-1),(y+.5)*sh/dh-.5));
        const unsigned y0=static_cast<unsigned>(sy),y1=std::min(y0+1,sh-1);
        const float fy=static_cast<float>(sy-y0);
        for(unsigned x=0;x<dw;++x) {
            const double sx=std::max(0.0,std::min(double(sw-1),(x+.5)*sw/dw-.5));
            const unsigned x0=static_cast<unsigned>(sx),x1=std::min(x0+1,sw-1);
            const float fx=static_cast<float>(sx-x0);
            const auto a=(static_cast<std::size_t>(y0)*sw+x0)*4;
            const auto b=(static_cast<std::size_t>(y0)*sw+x1)*4;
            const auto c=(static_cast<std::size_t>(y1)*sw+x0)*4;
            const auto d=(static_cast<std::size_t>(y1)*sw+x1)*4;
            const auto out=(static_cast<std::size_t>(y)*dw+x)*4;
            for(unsigned k=0;k<4;++k) {
                const float top=src[a+k]*(1-fx)+src[b+k]*fx;
                const float bottom=src[c+k]*(1-fx)+src[d+k]*fx;
                dst[out+k]=top*(1-fy)+bottom*fy;
            }
        }
    }
    return true;
}
