#include "mixed_service.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool v,const char* why){if(!v)throw std::runtime_error(why);}
template<class F>static void wait(F f){auto end=resume::Clock::now()+std::chrono::seconds(120);while(!f()){check(resume::Clock::now()<end,"Window service timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
static std::vector<float> oracle(cpu::PlanView p,cpu::AccelView a){std::vector<float> out(p->width*p->height*4);for(unsigned first=0;first<p->width*p->height;first+=mixed::Capacity){mixed::Job j{};j.epoch=mixed::config(p).epoch;j.sequence=first+1;j.count=std::min(mixed::Capacity,p->width*p->height-first);j.samples=p->spp;for(unsigned i=0;i<j.count;++i)j.pixels[i]=first+i;auto r=mixed::cpuJob(p,a,j);for(unsigned i=0;i<j.count;++i)for(unsigned c=0;c<4;++c)out[(first+i)*4+c]=float(r.pixels[i].sum[c]/r.pixels[i].count);}return out;}
int main(int argc,char** argv){try{
 check(argc==6,"scene runtime ptx output assets required");fs::path out(argv[4]);std::ifstream in(argv[3]);std::string ptx((std::istreambuf_iterator<char>(in)),{});rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);CanonicalSession canonical(argv[2],{901,0,0,0});unsigned version=0;cpu::PlanView prior;
 auto prepare=[&](const char* name){auto f=canonical.prepare(source,out/name,{901,++version,1,1});auto p=cpu::prepare(canonical,f,prior,cpu::Limits{},argv[5]);check(canonical.acknowledge(f)&&canonical.publish(f),"Publication");source.commitAllChanges();prior=p;return p;};
 auto plan=prepare("initial");auto expected=oracle(plan,cpu::acceleration(plan));mixed::Service service(ptx);uint64_t ticket;Json::Value report;
 check(service.request(plan,12,ticket,0,0,0,2),"Window request");wait([&]{check(!service.closed(),"Service died");return service.counts().progressiveSkipped>0;});
 std::vector<unsigned> previous(plan->width*plan->height);unsigned previews=0;bool pendingSeen=false;
 wait([&]{auto p=service.poll();if(!p)return false;check(p->ticket==ticket&&p->error.empty()&&p->image.windows>0&&p->tier=='D'&&!p->qualified,"Window packet identity");check(p->image.raw.size()==previous.size(),"Partial film shape");
  for(size_t i=0;i<previous.size();++i){auto n=p->image.raw[i].count;check(n>=previous[i]&&n<=plan->spp,"Window counts regressed");previous[i]=n;}
  if(!p->final){++previews;pendingSeen|=p->image.pendingPaths>0;return false;}
  check(p->image.rgba==expected&&p->image.pendingPaths==0,"Window final differs");report["render_windows"]=Json::UInt64(p->image.windows);return true;
 });check(previews>0&&pendingSeen,"No preview with parked paths");report["previews_with_unfinished_paths"]=true;report["partial_images"]=previews;report["backpressure_preserves_samples"]=true;
 // Supersede a real unfinished render, retaining the old immutable plan until its
 // running slices retire. New pixels must come only from the new scene epoch.
 check(service.request(plan,12,ticket,0,0,0,1),"Old request");wait([&]{auto p=service.poll();return p&&!p->final;});
 auto* m=source.getSceneObject("/m0");{rdl::SceneObject::UpdateGuard guard(m);m->set<rdl::Rgb>("emissiveColor",rdl::Rgb(.05f,.08f,.12f));}
 auto edited=prepare("edited");auto editExpected=oracle(edited,cpu::acceleration(edited));check(service.request(edited,12,ticket,0,0,0,2),"New scene request");
 wait([&]{auto p=service.poll();if(!p)return false;check(p->ticket==ticket&&p->epoch==edited->source->routing->epoch&&p->error.empty(),"Old scene surfaced");if(!p->final)return false;check(p->image.rgba==editExpected,"Edited image differs");return true;});report["scene_edit_preserves_ownership"]=true;
 check(service.request(edited,12,ticket,0,0,0,1),"Cancel request");wait([&]{auto p=service.poll();return p&&!p->final;});service.cancel();wait([&]{return service.active()==0;});check(!service.poll(),"Cancelled pixels surfaced");
 check(service.request(edited,12,ticket,1,0,0,2),"Failure request");wait([&]{auto p=service.poll();if(!p)return false;check(p->final&&!p->error.empty()&&p->image.rgba.empty(),"Bad slice published image");return true;});
 check(service.request(edited,12,ticket,0,0,0,2),"Recovery request");wait([&]{auto p=service.poll();if(!p)return false;check(p->error.empty(),"Recovery error");if(!p->final)return false;check(p->image.rgba==editExpected,"Recovery image differs");return true;});
 check(service.request(edited,12,ticket,0,0,0,1),"Shutdown request");wait([&]{auto p=service.poll();return p&&!p->final;});service.close();service.join();check(!service.poll()&&service.closed(),"Close exposed pixels");auto c=service.counts();check(c.cpuWorkersCreated==12&&c.cpuWorkersJoined==12&&c.cpuJobsSubmitted==c.cpuJobsCollected&&c.cpuJobsDiscarded==0&&c.failed==1&&c.gpuStarts==2,"Service lifecycle audit");
 report["cancel_failure_recovery_close"]=true;report["cpu_workers_created"]=Json::UInt64(c.cpuWorkersCreated);report["cpu_workers_joined"]=Json::UInt64(c.cpuWorkersJoined);report["cpu_slices_submitted"]=Json::UInt64(c.cpuJobsSubmitted);report["cpu_slices_collected"]=Json::UInt64(c.cpuJobsCollected);report["gpu_contexts"]=Json::UInt64(c.gpuStarts);report["snapshots_skipped"]=Json::UInt64(c.progressiveSkipped);report["status"]="passed";Json::StreamWriterBuilder w;w["indentation"]="";std::cout<<Json::writeString(w,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
