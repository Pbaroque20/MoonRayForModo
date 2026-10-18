"""Exercise group admission, copied inputs, cancellation and GPU retirement."""
import argparse,gzip,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2 import native_work as native_batch
from xpu2.reference import digest_file
from xpu2_baseline import environment

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','ptx','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','runs':[]}
    try:
        files=[ROOT/'xpu2'/n for n in ('native_work.py','native_shared_inputs.inc','native_batch.py','native_flight.py','native_flight_bridge.inc','native_flight_worker.inc','native_tile_schedule.py','native_tile_policy.h','native_gpu_early.py','native_lambert_queue.cc','native_queue_stress.cc')]+[a.ptx.resolve(),Path(__file__).resolve()]
        hashes={str(f):digest_file(f) for f in files};report['source_hashes']=hashes
        (out/'native_lambert_queue.cc').write_text(native_batch.queue((ROOT/'xpu2/native_lambert_queue.cc').read_text()))
        (out/'native_tile_policy.h').write_bytes((ROOT/'xpu2/native_tile_policy.h').read_bytes())
        (out/'reference.bin').write_bytes(gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes()))
        prefix=(ROOT/'xpu2/native_queue_stress.cc').read_text().split('int main(')[0]
        cc=out/'groups.cc';cc.write_text(prefix+r'''
int main(int argc,char** argv){try{
    require(argc==4,"capture capacity scenario required");
    std::ifstream file(argv[1],std::ios::binary);std::vector<unsigned char> data((std::istreambuf_iterator<char>(file)),{});
    auto p=packet(data,0);bool missing=std::string(argv[3])=="missing",cancel=std::string(argv[3])=="cancel";
    unsigned capacity=std::atoi(argv[2]);Queue q;std::unique_lock<std::mutex> hold(q.device.mutex);
    std::array<float,16*192> inputs;std::array<uint32_t,16*8> pixels{};
    for(unsigned j=0;j<16;++j)std::copy(p.input.begin(),p.input.end(),inputs.begin()+j*192);
    Queue::Ticket tickets[32];
    bool rejected=false;try{q.submitGroup(inputs.data(),p.output.data(),pixels.data(),17,17,tickets);}catch(const std::invalid_argument&){rejected=true;}
    require(rejected && q.next==0,"Invalid group mutated queue");
    q.submitGroup(inputs.data(),p.output.data(),pixels.data(),16,17,tickets);
    unsigned first=std::min(16u,capacity);
    if(first)waitFor(q,[&]{return q.pending.size()<first;});
    q.submitGroup(inputs.data(),p.output.data(),pixels.data(),16,17,tickets+16);
    unsigned accepted=std::min(32u,capacity);
    for(unsigned i=0;i<32;++i)require(bool(tickets[i])==(i<accepted),"Partial admission misplaced token");
    inputs.fill(-1234);pixels.fill(0xffffffff); // No caller storage may be borrowed.
    std::array<float,64> result;result.fill(1234);
    require(q.tryCollect(std::make_shared<Request>(),17,result.data())==Collect::WrongOwner,"Foreign token accepted");
    if(cancel){
        require(accepted==32,"Cancel fixture capacity");
        require(q.cancel(tickets[0]) && !q.cancel(tickets[0]),"In-flight cancellation failed");
        require(q.tryCollect(tickets[31],18,result.data())==Collect::Stale,"Stale revision accepted");
        require(std::all_of(result.begin(),result.end(),[](float x){return x==1234;}),"Rejected collection published");
    }
    hold.unlock();
    require(q.stop(std::chrono::milliseconds(5000)),"Group flights did not drain");
    for(unsigned i=accepted;i>0;){--i;
        auto status=q.tryCollect(tickets[i],17,result.data());
        if(cancel && (i==0 || i==31)){require(status==Collect::Cancelled,"Cancelled result published");continue;}
        require(status==Collect::Ready,"Group lost result");
        require(result==(missing?p.output:p.expected),"Group result differs");
        require(q.tryCollect(tickets[i],17,result.data())==Collect::Duplicate,"Duplicate accepted");
    }
    require(q.retainedAsync==0 && q.flightStarts==q.flightRetired && !q.device.cleanupErrors,"Group credit/resource leak");
    for(auto& slot:q.device.slots)require(!slot.host && !slot.stream && !slot.compactHost && !slot.compactDevice,"Flight resources retained");
    for(auto& ticket:tickets)ticket.reset();
    q.submitGroup(inputs.data(),p.output.data(),pixels.data(),16,17,tickets);
    for(unsigned i=0;i<16;++i)require(!tickets[i],"Stopped queue admitted group");
    std::cout<<"{\"passed\":true,\"admitted\":"<<accepted<<",\"retired\":"<<q.flightRetired<<",\"peak\":"<<q.peakFlights<<"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what();return 1;}}
''')
        compiler=a.source.resolve()/'toolchain/msys64/ucrt64/bin/g++.exe';headers=a.source.resolve()/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        env=environment(compiler.parent,out);exe=out/'groups.exe'
        done=subprocess.run([str(compiler),'-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(headers),str(cc),'-o',str(exe)],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'compile.log').write_text(done.stdout+done.stderr)
        if done.returncode:raise ValueError('Compile failed')
        report['executable_sha256']=digest_file(exe)
        for capacity,case in ((0,'normal'),(5,'normal'),(32,'normal'),(32,'cancel'),(32,'missing')):
            env=environment(compiler.parent,out);env.update(XPU2_SHARED_INPUTS='1',XPU2_GROUP_PACKETS='1',XPU2_INFLIGHT_BATCHES='2',XPU2_TILE_BATCH_LIMIT='8',XPU2_QUEUE_CAPACITY=str(capacity),XPU2_NATIVE_LAMBERT='sentinel',XPU2_NATIVE_LAMBERT_PTX=str(out/'missing.ptx' if case=='missing' else a.ptx.resolve()))
            done=subprocess.run([str(exe),str(out/'reference.bin'),str(capacity),case],env=env,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(str(capacity)+'-'+case+'.log')).write_text(done.stdout+done.stderr)
            if done.returncode:raise ValueError('Group check failed '+case+': '+done.stderr)
            result=json.loads(done.stdout);assert result['passed'];report['runs'].append(dict(capacity=capacity,case=case,result=result))
        for f,h in hashes.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
