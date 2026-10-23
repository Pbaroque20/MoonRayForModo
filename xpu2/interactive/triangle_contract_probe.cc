// Private regression cases independent of the gallery/workshop image samples.
#include "cpu_jobs.h"
#include <iostream>
using namespace xpu2::interactive;
int main(){try{
 unsigned checks=0;auto check=[&](bool b,const char* why){cpu::need(b,why);++checks;};
 surface::V3 a{0,0,0},b{1,0,0},c{0,1,0};surface::Ray r{{.25f,.25f,2},{0,0,-1},{},{},0,10};triangle::Coordinates h;
 check(triangle::coordinates(r,a,b,c,h)&&triangle::contains(h,r)&&h.t==2&&h.u==.25&&h.v==.25,"Interior coordinates");
 check(triangle::coordinates(r,a,c,b,h)&&triangle::contains(h,r)&&h.t==2,"Reverse winding");
 r.origin.x=.75f;r.origin.y=.75f;check(triangle::coordinates(r,a,b,c,h)&&!triangle::contains(h,r),"Outside triangle");
 r.origin.x=.5f;r.origin.y=.5f;check(triangle::coordinates(r,a,b,c,h)&&triangle::contains(h,r),"Shared edge");
 r.nearT=3;check(!triangle::contains(h,r),"Near clipping");r.nearT=0;r.farT=1;check(!triangle::contains(h,r),"Far clipping");r.farT=10;r.direction={1,0,0};check(!triangle::coordinates(r,a,b,c,h),"Parallel ray");
 r.direction={0,0,-1};check(!triangle::coordinates(r,a,a,c,h),"Degenerate triangle");
 check(double(triangle::upperDistance(16.-1.e-7))>=16.-1.e-7,"Outward traversal limit");
 check(triangle::nearer(1,0,9,1,1,0)&&!triangle::nearer(1,1,0,1,0,9),"Stable geometry tie");
 check(triangle::nearer(1,0,2,1,0,3)&&!triangle::nearer(1,0,3,1,0,2),"Stable primitive tie");
 auto plane=[](float z){auto m=std::make_shared<cpu::MeshData>();m->positions={{0,0,z},{1,0,z},{0,1,z}};m->triangles={{0,1,2}};return m;};
 for(unsigned order=0;order<3;++order){auto mutablePlan=std::make_shared<cpu::Plan>();mutablePlan->domain=cpu::Domain::DiffuseMesh;mutablePlan->meshes={{plane(order==1?1.e-7f:0),0},{plane(order==0?1.e-7f:0),0}};cpu::PlanView p=mutablePlan;auto accel=cpu::acceleration(p);mixed::CpuStageBackend backend{p,accel};surface::Ray ray{{.25f,.25f,16},{0,0,-1},{},{},0,100};auto hit=backend.trace(ray);check(hit.geom==(order==0?1u:0u),"Closest surface within one float distance bin / tie order");check(!backend.visible(ray.origin,ray.direction),"Occluder");check(backend.visible({2,2,16},ray.direction),"Unoccluded ray");check(cpu::acceleration(p,accel)==accel,"Stable acceleration reuse");auto planar=std::make_shared<cpu::Plan>(*p);planar->domain=cpu::Domain::Planar;check(cpu::acceleration(planar,accel)!=accel,"Domain switch rebuilds acceleration");}
 std::cout<<"{\"status\":\"passed\",\"checks\":"<<checks<<"}"<<std::endl;return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
