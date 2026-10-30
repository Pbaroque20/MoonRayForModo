    // Each slot owns its requests and scratch vectors through event retirement.
    struct Flight {
        std::vector<Ticket> requests;
        std::vector<float> input,output;
        std::unique_ptr<xpu2::transport::Batch> batch;
        xpu2::transport::Batch::Token token{};
        bool packed=false;
        const float* inputData(){return packed?batch->input():input.data();}
        float* outputData(){return packed?batch->resultStorage(token):output.data();}
        int count=0;
        bool active=false;
        std::chrono::steady_clock::time_point started;
    };
    bool transport=std::getenv("XPU2_BATCH_TRANSPORT") && !std::strcmp(std::getenv("XPU2_BATCH_TRANSPORT"),"1");
    unsigned long long transportPacks=0,transportRetired=0,transportFailed=0,transportDiscarded=0,transportBypass=0;
    unsigned long long packNs=0,retireNs=0;
    unsigned transportActive=0;
    unsigned flights=0;
    unsigned long long peakFlights=0,flightStarts=0,flightRetired=0,flightSubmitNs=0,flightPollNs=0;
    void workFlights() {
        Flight slots[4];
        for(unsigned i=0;i<4;++i){
            auto& f=slots[i];f.requests.reserve(64);
            if(transport && i<flights)f.batch=std::make_unique<xpu2::transport::Batch>();
            else if(!transport){f.input.reserve(512*24);f.output.reserve(512*8);}
        }
        unsigned active=0;
        auto retire=[&](unsigned i,bool failed){
            auto& f=slots[i];
            const auto retireStart=std::chrono::steady_clock::now();
            float* result=f.outputData();
            if(f.active)device.finishFlight(i,f.inputData(),result,f.count,failed);
            std::lock_guard<std::mutex> lock(mutex);
            deviceNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-f.started).count();
            ++merged;maxBatch=std::max(maxBatch,(unsigned long long)f.count);
            if(f.packed){
                const bool allCancelled=std::all_of(f.requests.begin(),f.requests.end(),[](const Ticket& r){return r->cancelled;});
                if(allCancelled && !f.batch->cancel(f.token))std::terminate();
                const auto state=f.batch->complete(f.token,!failed && !device.flightBroken);
                if(state==xpu2::transport::Completion::Rejected)std::terminate();
                if(allCancelled){if(state!=xpu2::transport::Completion::Retired)std::terminate();++transportDiscarded;}
                else if(state==xpu2::transport::Completion::Failed)++transportFailed;
                ++transportRetired;--transportActive;
            }
            int offset=0;
            for(auto& r:f.requests){
                if(r->cancelled){++late;releaseCredit(r);}
                else {std::memcpy(r->output,result+offset*8,r->count*32);r->done=true;r->completed.notify_one();}
                offset+=r->count;
            }
            if(f.packed && f.batch->phase()!=xpu2::transport::Phase::Empty && !f.batch->release(f.token))std::terminate();
            f.packed=false;f.requests.clear();
            if(f.active){f.active=false;--active;++flightRetired;}
            gpuPending.store(active>0);
            snapshot();
            retireNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-retireStart).count();
        };
        for(;;){
            // Fill all available slots before polling. No completion wait on submit.
            for(unsigned i=0;i<flights;++i){
                auto& f=slots[i];if(f.active)continue;
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    const auto selectStart=std::chrono::steady_clock::now();
                    while(!pending.empty() && f.requests.size()<batchLimit){
                        auto chosen=tilePolicy.choose(pending);
                        f.requests.push_back(pending[chosen]);pending.erase(pending.begin()+chosen);
                    }
                    selectionNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-selectStart).count();
                }
                if(f.requests.empty())continue;
                const auto packStart=std::chrono::steady_clock::now();
                const auto revision=f.requests.front()->revision;
                f.packed=transport && revision && std::all_of(f.requests.begin(),f.requests.end(),[&](const Ticket& r){return r->owner==ownerToken && r->revision==revision;});
                if(f.packed){
                    xpu2::transport::PacketView views[xpu2::transport::Layout::maxPackets];
                    for(unsigned j=0;j<f.requests.size();++j){const auto& r=f.requests[j];views[j]={r->input,r->output,unsigned(r->count)};}
                    f.token=f.batch->pack(views,unsigned(f.requests.size()),revision);
                    f.count=int(f.batch->samples());
                    if(!f.batch->submit(f.token))std::terminate();
                    ++transportPacks;++transportActive;
                }else{
                    if(transport)++transportBypass;
                    f.count=0;for(auto& r:f.requests)f.count+=r->count;
                    f.input.resize(f.count*24);f.output.resize(f.count*8);
                    int offset=0;
                    for(auto& r:f.requests){std::memcpy(f.input.data()+offset*24,r->input,r->count*96);std::memcpy(f.output.data()+offset*8,r->output,r->count*32);offset+=r->count;}
                }
                packNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-packStart).count();
                f.started=std::chrono::steady_clock::now();
                const bool started=device.startFlight(i,flights,f.inputData(),f.count);
                flightSubmitNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-f.started).count();
                if(!started){retire(i,true);continue;}
                f.active=true;++active;++flightStarts;
                peakFlights=std::max(peakFlights,(unsigned long long)active);
                stagingBytes+=device.lastTransferBytes;
                gpuPending.store(true);
            }
            bool progress=false;
            for(unsigned i=0;i<flights;++i)if(slots[i].active){
                const auto pollStart=std::chrono::steady_clock::now();
                const int status=device.pollFlight(i);
                flightPollNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-pollStart).count();
                if(status){retire(i,status<0);progress=true;}
            }
            std::unique_lock<std::mutex> lock(mutex);
            if(!active && pending.empty()){
                if(stopping){
                    if(transportActive || transportPacks!=transportRetired)std::terminate();
                    lock.unlock();bool cleaned=device.close();lock.lock();
                    cleanupOk=cleaned;workerExited=true;snapshot();stopped.notify_all();return;
                }
                const auto idleStart=std::chrono::steady_clock::now();
                available.wait(lock,[&]{return stopping || !pending.empty();});
                idleNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-idleStart).count();
            } else if(!progress){
                lock.unlock();std::this_thread::yield();
            }
        }
    }
