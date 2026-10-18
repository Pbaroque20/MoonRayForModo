"""Hold real CUDA streams after submission; verify cancellation retains slot resources."""
import argparse,gzip,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2 import native_work as native_flight
from xpu2.reference import digest_file
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity
CPP=r"""
static void CUDA_CB gate(void* data){
    auto& ready=*static_cast<std::atomic<bool>*>(data);
    while(!ready.load())std::this_thread::yield();
}
int main(int argc,char** argv){
    require(argc==2,"capture required");
    std::ifstream f(argv[1],std::ios::binary);
    std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)),{});
    Packet p=packet(data,0);
    auto q=std::make_unique<Queue>();
    std::atomic<bool> release{false};
    auto resources=std::make_shared<int>(7);
    std::vector<Queue::Ticket> tickets;
    {
        std::lock_guard<std::mutex> lock(q->device.mutex);
        auto& d=q->device;d.initialize();Bridge::check(d.fn_cuCtxPushCurrent_v2(d.context));
        d.allocateFlights(4);
        auto enqueue=reinterpret_cast<decltype(&cuLaunchHostFunc)>(GetProcAddress(d.lib,"cuLaunchHostFunc"));
        require(enqueue!=nullptr,"No host callback function");
        for(auto& s:d.slots)Bridge::check(enqueue(s.stream,gate,&release));
        CUcontext popped=nullptr;Bridge::check(d.fn_cuCtxPopCurrent_v2(&popped));
        for(unsigned i=0;i<32;++i){
            auto t=q->submit(p.input.data(),p.output.data(),8,99,resources);
            require(bool(t),"Credit refused");tickets.push_back(t);
        }
    }
    bool active=false;
    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    while(std::chrono::steady_clock::now()<until){
        {std::lock_guard<std::mutex> lock(q->device.mutex);active=q->device.flightSubmitted>=4 && q->device.flightPending>0;}
        if(active)break;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    // Release on every failure path before destroying the callback's state.
    if(!active){release=true;q->stop(std::chrono::seconds(5));throw std::runtime_error("Four incomplete flights not observed");}
    for(auto& t:tickets)require(q->cancel(t),"Cancellation failed");
    {
        std::lock_guard<std::mutex> lock(q->mutex);
        require(q->retainedAsync>=4,"Active resources were released early");
        require(resources.use_count()>1,"Flight lost retained scene resources");
    }
    std::array<float,64> output;output.fill(12345.f);
    for(auto& t:tickets)require(q->tryCollect(t,99,output.data())==Collect::Cancelled,"Cancelled packet was published");
    require(std::all_of(output.begin(),output.end(),[](float v){return v==12345.f;}),"Cancellation wrote output");
    {std::lock_guard<std::mutex> lock(q->device.mutex);require(q->device.compactBatches>=4,"Compact flights not exercised");}
    release=true;
    require(q->stop(std::chrono::seconds(5)),"Flight drain failed");
    require(q->retainedAsync==0 && resources.use_count()==1,"Resources retained after drain");
    require(!q->delivered && q->flightStarts==q->flightRetired,"Incomplete or duplicate retirement");
    require(q->peakFlights==4 && q->device.flightPending>0,"Concurrent stream work absent");
    for(auto& s:q->device.slots){require(!s.host&&!s.stream&&!s.done&&!s.begin&&!s.end&&!s.compactHost&&!s.compactDevice,"Slot leak");for(auto ptr:s.device)require(!ptr,"Device buffer leak");}
    std::cout<<"{\"passed\":true,\"peak_inflight\":"<<q->peakFlights<<",\"retired\":"<<q->flightRetired<<",\"retained_credits\":"<<q->retainedAsync<<",\"published\":"<<q->delivered<<"}\n";
}
"""
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','ptx','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    files=[ROOT/'xpu2'/s for s in ('native_lambert_queue.cc','native_gpu_early.py','native_tile_schedule.py','native_tile_policy.h','native_flight.py','native_flight_bridge.inc','native_flight_worker.inc','native_queue_stress.cc','native_batch.py','native_work.py','native_shared_inputs.inc')]+[a.ptx.resolve(),Path(__file__)]
    report={'status':'incomplete','source_hashes':{str(f):digest_file(f) for f in files},'gpu':gpu_identity(),'scope':'CUDA stream callback gate; proves retention during incomplete asynchronous work, not cancellation of an executing shader kernel'}
    try:
        (out/'flight.inc').write_text(native_flight.queue((ROOT/'xpu2/native_lambert_queue.cc').read_text()))
        (out/'native_tile_policy.h').write_bytes((ROOT/'xpu2/native_tile_policy.h').read_bytes())
        helpers=(ROOT/'xpu2/native_queue_stress.cc').read_text().split('int main(')[0].replace('"native_lambert_queue.cc"','"flight.inc"')
        (out/'held.cc').write_text(helpers+CPP)
        raw=gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes());(out/'packets.bin').write_bytes(raw)
        compiler=a.source/'toolchain/msys64/ucrt64/bin/g++.exe';headers=a.source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        env=environment(compiler.parent,out);env.update(XPU2_NATIVE_LAMBERT='execute',XPU2_NATIVE_LAMBERT_PTX=str(a.ptx.resolve()),XPU2_SHARED_INPUTS='1',XPU2_INFLIGHT_BATCHES='4',XPU2_TILE_BATCH_LIMIT='4',XPU2_QUEUE_CAPACITY='64')
        build=subprocess.run([str(compiler),'-std=c++17','-O2','-I'+str(headers),str(out/'held.cc'),'-o',str(out/'held.exe')],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'build.log').write_text(build.stdout+build.stderr)
        if build.returncode:raise ValueError('Compile failed')
        done=subprocess.run([str(out/'held.exe'),str(out/'packets.bin')],env=env,capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'process.log').write_text(done.stdout+done.stderr)
        if done.returncode:raise ValueError('Held flight failed')
        report['result']=json.loads(done.stdout)
        if not report['result']['passed']:raise ValueError('Missing success')
        for f,h in report['source_hashes'].items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
