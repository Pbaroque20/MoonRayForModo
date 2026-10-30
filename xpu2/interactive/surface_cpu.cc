#include "surface_fixture.h"
extern "C" __declspec(dllexport) void fill(unsigned count,float* out){for(unsigned i=0;i<count;++i)xpu2::interactive::surfaceFixture(i,out+i*16);}
