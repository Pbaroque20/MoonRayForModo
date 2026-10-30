#include "sample_fixture.h"
extern "C" __global__ void check(unsigned int* out){if(threadIdx.x==0&&blockIdx.x==0)*out=xpu2::interactive::sampletest::checks();}
extern "C" __global__ void fill(unsigned long long first,unsigned int blocks,unsigned int* out){
    using namespace xpu2::interactive;
    for(unsigned int j=blockIdx.x*blockDim.x+threadIdx.x;j<blocks;j+=gridDim.x*blockDim.x){
        auto w=sampletest::fixture(first+j);
        for(int k=0;k<4;++k){out[j*8+k]=w.v[k];float f=sample::unit(w.v[k]);
            // Type-punning by byte copy, without a second GPU-only conversion.
            auto dst=reinterpret_cast<unsigned char*>(out+j*8+4+k);
            auto src=reinterpret_cast<const unsigned char*>(&f);for(int b=0;b<4;++b)dst[b]=src[b];
        }
    }
}
