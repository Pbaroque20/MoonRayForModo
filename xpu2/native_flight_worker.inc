    // Each slot owns its requests and scratch vectors through event retirement.
    struct Flight {
        std::vector<Ticket> requests;
        std::vector<float> input,output;
        int count=0;
        bool active=false;
        std::chrono::steady_clock::time_point started;
    };
    unsigned flights=0;
    unsigned long long peakFlights=0,flightStarts=0,flightRetired=0,flightSubmitNs=0,flightPollNs=0;
    void workFlights() {
        Flight slots[4];
        for(auto& f:slots){f.requests.reserve(64);f.input.reserve(512*24);f.output.reserve(512*8);}
        unsigned active=0;
        auto retire=[&](unsigned i,bool failed){
            auto& f=slots[i];
            if(f.active)device.finishFlight(i,f.input.data(),f.output.data(),f.count,failed);
            std::lock_guard<std::mutex> lock(mutex);
            deviceNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-f.started).count();
            ++merged;maxBatch=std::max(maxBatch,(unsigned long long)f.count);
            int offset=0;
            for(auto& r:f.requests){
                if(r->cancelled){++late;releaseCredit(r);}
                else {std::memcpy(r->output,f.output.data()+offset*8,r->count*32);r->done=true;r->completed.notify_one();}
                offset+=r->count;
            }
            f.requests.clear();
            if(f.active){f.active=false;--active;++flightRetired;}
            gpuPending.store(active>0);
            snapshot();
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
                f.count=0;for(auto& r:f.requests)f.count+=r->count;
                f.input.resize(f.count*24);f.output.resize(f.count*8);
                int offset=0;
                for(auto& r:f.requests){std::memcpy(f.input.data()+offset*24,r->input,r->count*96);std::memcpy(f.output.data()+offset*8,r->output,r->count*32);offset+=r->count;}
                f.started=std::chrono::steady_clock::now();
                const bool started=device.startFlight(i,flights,f.input.data(),f.count);
                flightSubmitNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-f.started).count();
                if(!started){retire(i,true);continue;}
                f.active=true;++active;++flightStarts;
                peakFlights=std::max(peakFlights,(unsigned long long)active);
                stagingBytes+=static_cast<unsigned long long>(f.count)*232;
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
