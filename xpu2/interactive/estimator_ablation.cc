// Private causal estimator test: same camera/hit/material events for all variants.
// Not a native MoonRay MIS port, GPU benchmark, or production material change.
#include "cpu_jobs.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
int main(int argc,char** argv){try{
 cpu::need(argc==6,"scene runtime assets output seed");fs::path out(argv[4]);
 rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);
 CanonicalSession canonical(argv[2],{8801,0,0,0});auto frame=canonical.prepare(source,out/"canonical",{8801,1,1,1});auto plan=cpu::prepare(canonical,frame,{},cpu::Limits{},argv[3],cpu::Domain::SurfaceTextures);
 cpu::need(plan->surfaceLimit==1&&plan->width*uint64_t(plan->height)<=16384&&plan->spp==64,"Ablation fixture bounds");auto accel=cpu::acceleration(plan);mixed::CpuStageBackend backend{plan,accel};auto seed=unsigned(std::stoul(argv[5]));
 size_t pixels=plan->width*plan->height;std::array<std::vector<double>,6> sums;for(auto& a:sums)a.resize(pixels*4);uint64_t rays=0,hits=0;
 // Both sampler arms use identical Sobol camera jitter. Only directional sampling changes.
 for(unsigned pixel=0;pixel<pixels;++pixel)for(unsigned si=0;si<plan->spp;++si){sample::Identity id{pixel,si,seed,0};float x,y;surface::Ray ray;
  cpu::need(surface::filter(plan->filter,plan->filterWidth,sample::draw(id,0,3),x)&&surface::filter(plan->filter,plan->filterWidth,sample::draw(id,1,3),y)&&surface::cameraRay(plan->camera,float(pixel%plan->width)+x,float(pixel/plan->width)+y,ray),"Ablation camera");auto hit=backend.trace(ray);if(hit.geom==~0u)continue;++hits;surface::Lambert mat;cpu::need(backend.material(hit,ray,mat),"Ablation material");
  for(unsigned q=0;q<2;++q){unsigned policy=q?3:1;auto second=id;second.branch=1;surface::Sample a,b;
   cpu::need(surface::lambert(mat,hit.normal,sample::draw(id,16,policy),sample::draw(id,17,policy),a)&&surface::lambert(mat,hit.normal,sample::draw(second,16,policy),sample::draw(second,17,policy),b),"Ablation BSDF");
   bool va=backend.visible(hit.origin,a.wi),vb=backend.visible(hit.origin,b.wi);rays+=2;
   float u=sample::draw(second,16,policy),v=sample::draw(second,17,policy),z=1-2*u,sn,cs;surface::sincosSample(v*(2*surface::Pi),sn,cs);float radius=std::sqrt(std::max(0.f,1-z*z));surface::V3 wi{radius*cs,radius*sn,z};
   float cosine=std::max(0.f,surface::dot(hit.normal,wi));bool vl=false;if(cosine>0){vl=backend.visible(hit.origin,wi);++rays;}
   float lp=1.f/(4*surface::Pi),bp=cosine*surface::InvPi;double wa=double(a.pdf)*a.pdf/(double(a.pdf)*a.pdf+double(lp)*lp),wl=double(lp)*lp/(double(bp)*bp+double(lp)*lp);
   float aa[3]={mat.albedo.x,mat.albedo.y,mat.albedo.z},fa[3]={a.f.x,a.f.y,a.f.z},fb[3]={b.f.x,b.f.y,b.f.z},sky[3]={plan->sky.x,plan->sky.y,plan->sky.z},em[3]={mat.emission.x,mat.emission.y,mat.emission.z};
   for(int c=0;c<3;++c){double ca=va&&a.pdf>0?double(fa[c]/a.pdf):0,cb=vb&&b.pdf>0?double(fb[c]/b.pdf):0,cl=vl?double(aa[c])*4*cosine:0;
    sums[q*3][pixel*4+c]+=em[c]+sky[c]*ca;sums[q*3+1][pixel*4+c]+=em[c]+sky[c]*(ca+cb)*.5;sums[q*3+2][pixel*4+c]+=em[c]+sky[c]*(ca*wa+cl*wl);}
   for(unsigned e=0;e<3;++e)sums[q*3+e][pixel*4+3]+=1;
  }
 }
 Json::Value report;report["seed"]=seed;report["width"]=plan->width;report["height"]=plan->height;report["spp"]=plan->spp;report["primary_hits"]=Json::UInt64(hits);report["shared_experiment_shadow_rays"]=Json::UInt64(rays);
 const char* labels[6]={"philox-bsdf1","philox-bsdf2","philox-mis","sobol-bsdf1","sobol-bsdf2","sobol-mis"};
 for(unsigned n=0;n<6;++n){std::vector<float> raw;raw.reserve(pixels*4);for(double v:sums[n]){cpu::need(std::isfinite(v),"Nonfinite ablation");raw.push_back(float(v/plan->spp));}auto path=out/(std::string(labels[n])+".rgba");std::ofstream f(path,std::ios::binary);f.write((char*)raw.data(),raw.size()*4);cpu::need(bool(f),"Write ablation");report["images"][labels[n]]=path.string();}
 accel->device->check();report["status"]="passed";Json::StreamWriterBuilder b;b["indentation"]="";std::cout<<Json::writeString(b,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
