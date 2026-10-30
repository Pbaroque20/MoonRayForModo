#include "cpu_scene.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
int main(int argc,char** argv){try{
 cpu::need(argc==6,"scene runtime assets output unmipped required");fs::path folder(argv[4]),assets(argv[3]);rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);CanonicalSession session(argv[2],{601,0,0,0});auto frame=session.prepare(source,folder/"canonical",{601,1,1,1});
 auto plan=cpu::prepare(session,frame,{},cpu::Limits{},assets);auto reused=cpu::prepare(session,frame,plan,cpu::Limits{},assets);cpu::need(!plan->diffuseMaps.empty(),"Map fixture missing");auto file=plan->diffuseMaps.begin()->second.file;cpu::need(reused->diffuseMaps.begin()->second.file==file,"Cache not reused");
 Json::Value report;auto reject=[&](const char* label,auto action){bool refused=false;try{action();}catch(const std::exception& e){refused=true;report[label]=e.what();}cpu::need(refused,std::string("Admission accepted ")+label);};
 fs::create_directory(folder/"unrelated");reject("cached_path_outside_root",[&]{cpu::prepare(session,frame,plan,cpu::Limits{},folder/"unrelated");});
 reject("missing_asset",[&]{texture::File f(assets/"missing.tx",assets,file->system);});
 reject("missing_mips",[&]{texture::File f(fs::path(argv[5]),folder,file->system);});
 auto* map=source.getSceneObject("/texture");{rdl::SceneObject::UpdateGuard g(map);map->set<rdl::Float>("rotation_angle",20);}
 reject("unsupported_projection_rotation",[&]{cpu::prepare(source,frame,plan,cpu::Limits{},assets);});
 report["retained_host_cache"]=true;report["status"]="passed";Json::StreamWriterBuilder w;w["indentation"]="";std::cout<<Json::writeString(w,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
