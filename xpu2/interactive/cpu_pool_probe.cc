#include "cpu_pool.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
template<class F>static void wait(F f){auto until=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(!f()){check(std::chrono::steady_clock::now()<until,"CPU pool timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
static void equal(const mixed::Result& a,const mixed::Result& b){check(a.sequence==b.sequence&&path::equal(a.epoch,b.epoch)&&a.count==b.count,"CPU identity");for(unsigned i=0;i<a.count;++i){const auto& x=a.pixels[i];const auto& y=b.pixels[i];check(x.pixel==y.pixel&&x.count==y.count&&x.status==y.status,"CPU count/status");for(unsigned c=0;c<4;++c)check(x.sum[c]==y.sum[c],"CPU result changed");}}
int main(int argc,char** argv){try{
 check(argc==4,"scene runtime output required");fs::path folder(argv[3]);rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);CanonicalSession session(argv[2],{701,0,0,0});
 auto frame=session.prepare(source,folder/"initial",{701,1,1,1});auto plan=cpu::prepare(session,frame);auto accel=cpu::acceleration(plan);check(session.acknowledge(frame)&&session.publish(frame),"Initial publication");source.commitAllChanges();
 auto* material=source.getSceneObject("/m0");{rdl::SceneObject::UpdateGuard g(material);material->set<rdl::Rgb>("diffuseColor",rdl::Rgb(.2f,.4f,.7f));}
 auto frame2=session.prepare(source,folder/"edit",{701,2,1,1});auto second=cpu::prepare(session,frame2,plan);auto accel2=cpu::acceleration(second,accel);check(session.acknowledge(frame2)&&session.publish(frame2),"Edit publication");
 mixed::CpuPool pool;uint64_t seq=0;Json::Value report;std::map<uint64_t,mixed::Result> expected;
 auto job=[&](cpu::PlanView p){mixed::Job j{};j.epoch=mixed::config(p).epoch;j.sequence=++seq;j.count=2;j.pixels[0]=0;j.pixels[1]=31;j.samples=3;j.first=unsigned(seq%200);return j;};
 auto submit=[&](cpu::PlanView p,cpu::AccelView a){auto j=job(p);if(!pool.submit(p,a,j))return false;expected.emplace(j.sequence,mixed::cpuJob(p,a,j));return true;};
 auto drain=[&]{mixed::Result result;while(pool.poll(result)){auto found=expected.find(result.sequence);check(found!=expected.end(),"Duplicate/unknown CPU completion");equal(result,found->second);expected.erase(found);}return expected.empty();};
 pool.begin(1);check(submit(plan,accel)&&submit(plan,accel),"Initial two credits");auto refused=job(plan);check(!pool.submit(plan,accel,refused),"Uncollected completions bypass credit bound");wait([&]{return pool.counts().parked==1;});check(pool.counts().outstanding==2,"Premature credit return");wait(drain);pool.finish();report["bounded_result_backpressure"]=true;
 // Reconfigure active width repeatedly, preserve actual threads, mix old/new
 // immutable epochs in the worker transport without overwriting shared state.
 for(unsigned pass=0;pass<64;++pass){unsigned width=pass%3==0?1:12;pool.begin(width);unsigned sent=0;while(sent<47||!expected.empty()){
  while(sent<47){bool old=(sent+pass)&1;if(!submit(old?plan:second,old?accel:accel2))break;++sent;}drain();std::this_thread::yield();
 }check(pool.counts().outstanding==0,"Pass still owns work");pool.finish();}
 check(pool.counts().created==12&&pool.counts().joined==0,"Thread recreation during width/pass changes");report["mixed_retained_epochs_exact"]=true;
 pool.begin(12);bool overlap=false;try{pool.begin(1);}catch(...){overlap=true;}check(overlap,"Overlapping passes accepted");bool owner=false;std::thread alien([&]{try{pool.counts();}catch(const std::logic_error&){owner=true;}});alien.join();check(owner,"Second feeder accepted");
 // Genuine CPU evaluation failure, not a fake completion packet. It cannot kill
 // the worker, silently become black success, or poison the following job.
 auto bad=std::make_shared<cpu::Plan>(*plan);bad->camera.nearClip=-1;auto badJob=job(bad);check(pool.submit(bad,accel,badJob),"Bad job enqueue");mixed::Result error;wait([&]{return pool.poll(error);});check(error.sequence==badJob.sequence&&error.pixels[0].status==99,"CPU failure hidden");check(submit(plan,accel),"Recovery enqueue");wait(drain);pool.finish();report["cpu_exception_recovery"]=true;
 // Last plan/acceleration references travel back in the completion; idle workers
 // and emptied slots must not retain obsolete scenes.
 pool.begin(12);auto owned=std::make_shared<cpu::Plan>(*plan);auto heldAccel=cpu::acceleration(owned);std::weak_ptr<const cpu::Plan> weakPlan=owned;std::weak_ptr<const cpu::Acceleration> weakAccel=heldAccel;auto heldJob=job(owned);check(pool.submit(owned,heldAccel,heldJob),"Retained job");owned.reset();heldAccel.reset();wait([&]{return pool.counts().parked==12;});check(!weakPlan.expired()&&!weakAccel.expired(),"In-flight scene released early");mixed::Result result;wait([&]{return pool.poll(result);});check(weakPlan.expired()&&weakAccel.expired(),"Idle worker retains obsolete scene");pool.finish();report["scene_reference_retirement"]=true;
 auto submittedBefore=pool.counts().submitted;
 try{mixed::CpuPass pass(pool,12);for(unsigned i=0;i<24;++i){auto j=job(plan);check(pool.submit(plan,accel,j),"Exception-drain enqueue");}throw std::runtime_error("injected feeder failure");}catch(const std::runtime_error&){}
 auto counts=pool.counts();check(counts.submitted==submittedBefore+24&&counts.outstanding==0&&counts.submitted==counts.collected,"Exceptional feeder exit leaves pending jobs");pool.begin(1);check(submit(second,accel2),"Post-unwind enqueue");wait(drain);pool.finish();report["feeder_unwind_drains"]=true;
 wait([&]{return pool.counts().parked==12;});counts=pool.counts();check(counts.peakOutstanding<=24&&counts.failures==1&&counts.created==12&&counts.joined==0,"Pool audit");report["idle_workers_parked"]=counts.parked;
 pool.close();counts=pool.counts();check(counts.joined==12&&counts.discarded==0&&counts.outstanding==0,"Pool shutdown");bool closed=false;try{pool.begin(1);}catch(...){closed=true;}check(closed,"Closed pool reopened");
 report["created"]=Json::UInt64(counts.created);report["joined"]=Json::UInt64(counts.joined);report["passes"]=Json::UInt64(counts.passes);report["submitted"]=Json::UInt64(counts.submitted);report["collected"]=Json::UInt64(counts.collected);report["failed_jobs"]=Json::UInt64(counts.failures);report["peak_outstanding"]=counts.peakOutstanding;for(auto n:counts.perWorker)report["jobs_per_worker"].append(Json::UInt64(n));report["coordinator_guard"]=owner;report["overlapping_pass_guard"]=overlap;report["status"]="passed";Json::StreamWriterBuilder w;w["indentation"]="";std::cout<<Json::writeString(w,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
