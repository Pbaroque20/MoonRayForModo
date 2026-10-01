#include "image_resample.hpp"
#include <array>
#include <cassert>
#include <cmath>
int main() {
    const std::array<float,16> pixels={1,0,0,1, 0,1,0,1, 0,0,1,1, 1,1,1,1};
    std::array<float,36> larger{};
    assert(copyPreviewRgba(pixels.data(),2,2,larger.data(),3,3));
    for(unsigned k=0;k<3;++k) assert(std::abs(larger[16+k]-.5f)<1e-6f);
    assert(larger[0]==1 && larger[1]==0 && larger[2]==0);
    assert(larger[24]==0 && larger[25]==0 && larger[26]==1);
    for(unsigned i=3;i<larger.size();i+=4) assert(larger[i]==1);
    std::array<float,4> smaller{};
    assert(copyPreviewRgba(pixels.data(),2,2,smaller.data(),1,1));
    for(unsigned k=0;k<3;++k) assert(std::abs(smaller[k]-.5f)<1e-6f);
    std::array<float,16> same{};
    assert(copyPreviewRgba(pixels.data(),2,2,same.data(),2,2));
    assert(same==pixels);
    assert(!copyPreviewRgba(nullptr,2,2,same.data(),2,2));
    assert(!copyPreviewRgba(pixels.data(),0,2,same.data(),2,2));
}
