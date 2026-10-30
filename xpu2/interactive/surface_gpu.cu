#include "surface_fixture.h"
extern "C" __global__ void fill(unsigned count,float* out){for(unsigned i=blockIdx.x*blockDim.x+threadIdx.x;i<count;i+=blockDim.x*gridDim.x)xpu2::interactive::surfaceFixture(i,out+i*16);}
