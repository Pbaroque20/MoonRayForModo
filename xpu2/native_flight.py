"""Strict copied-source multi-flight queue; legacy serial path remains selectable."""
from pathlib import Path
from . import native_tile_schedule as tile
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=tile.adapter
cpp=tile.cpp
header=tile.header
ispc=tile.ispc

def queue(text):
    text=tile.queue(text)
    begin=text.index('            for(int i=0;i<count;++i) {\n                U native[8]')
    end=text.index('\n        } catch(const std::exception& e)',begin)
    validation=text[begin:end]
    methods=(HERE/'native_flight_bridge.inc').read_text().replace('        // VALIDATION_BODY',validation)
    text=once(text,'    void summary() {',methods+'\n    void summary() {')
    text=once(text,'#undef LOAD', '''        LOAD(cuMemHostAlloc) LOAD(cuMemFreeHost)
        LOAD(cuStreamCreate) LOAD(cuStreamDestroy_v2)
        LOAD(cuMemcpyHtoDAsync_v2) LOAD(cuMemcpyDtoHAsync_v2)
#undef LOAD''')
    text=once(text,'                checked(fn_cuCtxSynchronize());','''                if(!checked(fn_cuCtxSynchronize()))std::terminate();
                closeFlights();''')
    text=once(text,'        worker=std::thread([this]{work();});','''        const char* slots=std::getenv("XPU2_INFLIGHT_BATCHES");
        if(slots)flights=std::min(4,std::max(0,std::atoi(slots)));
        worker=std::thread([this]{if(flights)workFlights();else work();});''')
    return once(text,'    void work() {',(HERE/'native_flight_worker.inc').read_text()+'\n    void work() {')

def profile(text):
    text=tile.profile(text)
    return once(text,'    shaderQueue.reset();',r'''    if(const char* name=std::getenv("XPU2_NATIVE_FLIGHT_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        const auto& q=*shaderQueue;
        std::fprintf(f,"{\"slots\":%u,\"peak_inflight\":%llu,\"submitted\":%llu,\"retired\":%llu,\"queries\":%llu,\"not_ready\":%llu,\"submit_ns\":%llu,\"poll_ns\":%llu,\"error_drains\":%llu,\"kernel_us\":%llu}\n",
          q.flights,q.peakFlights,q.flightStarts,q.flightRetired,d.flightQueries,d.flightPending,q.flightSubmitNs,q.flightPollNs,d.flightDrains,kernelMicroseconds.load());std::fclose(f);
    }
    shaderQueue.reset();''')
