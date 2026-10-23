// Private shared bounded job ABI. Whole samples, no constructed BSDF crosses PCIe.
#pragma once
#include "surface_core.h"
#include "path_stage.h"
#include "texture_core.h"
namespace xpu2::interactive::resume {struct Batch;}
namespace xpu2::interactive::mixed {
using sample::U32;using sample::U64;
constexpr U32 Capacity=256;
struct Config {path::Epoch epoch;surface::Camera camera;surface::V3 sky;U32 width,height,seed,meshes;surface::Filter filter;float filterWidth;U32 spatial=0,surfaceLimit=1,spp=1,textures=0,sampling=3;};
struct Job {path::Epoch epoch{};U64 sequence=0;U32 count=0,first=0,samples=0,fault=0;U64 delay=0;U32 pixels[Capacity]{};};
struct Pixel {double sum[4]{};U32 count=0,status=0,pixel=0,pad=0;};
struct Result {path::Epoch epoch{};U64 sequence=0;U32 count=0,pad=0;Pixel pixels[Capacity]{};};
struct Geometry {const surface::V3* vertices;const surface::Triangle* triangles;U32 vertexCount,triangleCount;};
struct Params {const Config* scene;const surface::Lambert* materials;U64 traversable;Result* result;Job job;resume::Batch* continuation=nullptr;U32 stageSteps=0,reset=0;const Geometry* geometry=nullptr;const tex::Maps* maps=nullptr;};
static_assert(sizeof(Pixel)==48&&sizeof(Job)==1088&&sizeof(Params)==1152&&sizeof(Result)==12336,"Shared job ABI");
X2_HD inline bool same(const Job& j,const Config& c){return path::equal(j.epoch,c.epoch)&&j.count>0&&j.count<=Capacity&&j.samples>0&&j.samples<=4096&&c.sampling<=3&&j.first<=0xffffffffu-j.samples;}
}
