// Experimental bounded neighbor policy. No scene traversal or lane regrouping.
#pragma once
#include <cstdint>
#include <cstddef>
namespace xpu2tile {
constexpr uint32_t unknown=0xffffffffu;
struct Policy {
    bool neighbor=false;
    uint32_t previous=unknown;
    uint64_t claims=0,local=0,shared=0,aged=0,reordered=0,inspected=0,switches=0;
    template<class Q> size_t choose(const Q& pending) {
        size_t chosen=0;
        if(neighbor && claims-pending.front()->queuedClaim>=64){++aged;}
        else if(neighbor && previous!=unknown){
            bool found=false;
            for(size_t i=0;i<pending.size();++i){
                ++inspected;const auto t=pending[i]->tile;
                if(t==unknown)continue;
                const int dx=int(t&0xffff)-int(previous&0xffff);
                const int dy=int(t>>16)-int(previous>>16);
                if(dx>=-1 && dx<=1 && dy>=-1 && dy<=1){chosen=i;found=true;break;}
            }
            if(found)++local;else ++shared;
        } else ++shared;
        if(chosen)++reordered;
        const auto t=pending[chosen]->tile;
        if(t!=unknown){if(previous!=unknown && previous!=t)++switches;previous=t;}
        ++claims;return chosen;
    }
};
// MoonRay pbr::pixelLocationToUint32 encodes y<<16 | x.
// Mixed packets stay intact; their first active lane supplies only a locality hint.
inline uint32_t tileFor(const uint32_t* pixels,bool& mixed) {
    uint32_t first=unknown;mixed=false;
    if(!pixels)return first;
    for(unsigned i=0;i<8;++i){
        if(pixels[i]==unknown)continue;
        const uint32_t tile=((pixels[i]>>20)<<16)|((pixels[i]&0xffff)>>4);
        if(first==unknown)first=tile;else if(first!=tile)mixed=true;
    }
    return first;
}
}
