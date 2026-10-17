# Explicit publication of owned native sample windows; isolated optional build.
from xpu2.profile_patch import replace

def apply(code):
    def edit(old,new,count=1):
        nonlocal code
        code=replace(code,old,new,count)
    edit('bool done=false,cancelled=false,consumed=false,credit=false;',
         'bool done=false,cancelled=false,consumed=false,credit=false,dispatchable=true;')
    edit('bool mixed=false,split=false;', 'bool mixed=false,split=false,explicitWindow=false;')
    edit('p=std::getenv("XPU2_QUEUE_COALESCE_US");',
         'p=std::getenv("XPU2_WINDOW_DISPATCH");explicitWindow=p && !std::strcmp(p,"1");\n        p=std::getenv("XPU2_QUEUE_COALESCE_US");')
    edit('stopping=true;available.notify_all();',r'''stopping=true;
        // Unpublished work cannot be rendered during shutdown. Its credits and
        // waiters are released; already published work drains normally.
        for(auto it=pending.begin();it!=pending.end();) {
            auto request=*it;
            if(!request->dispatchable) {
                request->cancelled=true;++explicitCancelled;++pruned;
                releaseCredit(request);request->completed.notify_all();
                it=pending.erase(it);
            }else ++it;
        }
        available.notify_all();''')
    edit('Ticket submit(const float* input,const float* native,int count,uint64_t revision) {',
         'Ticket submit(const float* input,const float* native,int count,uint64_t revision,bool held=false) {')
    edit('request->owner=ownerToken;request->revision=revision;request->credit=true;',
         'request->owner=ownerToken;request->revision=revision;request->credit=true;request->dispatchable=!held;')
    edit('void releaseCredit(const Ticket& request) {',r'''// Validate the entire window before publishing any request. All fields and
    // membership are protected by the same queue mutex as cancellation/stop.
    bool publish(const std::vector<Ticket>& window,uint64_t revision) {
        std::lock_guard<std::mutex> lock(mutex);
        if(stopping || window.empty() || window.size()>16)return false;
        for(size_t i=0;i<window.size();++i) {
            const auto& r=window[i];
            if(!r || r->owner!=ownerToken || r->revision!=revision || r->cancelled ||
               r->consumed || r->done || r->dispatchable || !r->credit ||
               std::find(pending.begin(),pending.end(),r)==pending.end())return false;
            for(size_t j=0;j<i;++j)if(window[j]==r)return false;
        }
        for(const auto& r:window)r->dispatchable=true;
        available.notify_one();return true;
    }
    bool hasDispatchable() const {
        return std::any_of(pending.begin(),pending.end(),[](const Ticket& r){return r->dispatchable;});
    }
    void releaseCredit(const Ticket& request) {''')
    edit('available.wait(lock,[&]{return stopping || !pending.empty();});',
         'available.wait(lock,[&]{return stopping || hasDispatchable();});')
    edit('if(coalesceUs) {','if(coalesceUs && !explicitWindow) {')
    edit('while(!pending.empty() && batch.size()<64){batch.push_back(pending.front());pending.pop_front();}',r'''for(auto it=pending.begin();it!=pending.end() && batch.size()<64;) {
                    if((*it)->dispatchable){batch.push_back(*it);it=pending.erase(it);}
                    else ++it; // An unfinished producer must not block another.
                }''')
    edit('thread_local int currentSlot=0;', 'thread_local int currentSlot=0;\nthread_local bool windowPending=false;')
    edit('current().ticket=q.submit(input,output,count,1);',
         'current().ticket=q.submit(input,output,count,1,q.explicitWindow);\n    if(current().ticket && q.explicitWindow)windowPending=true;')
    edit('auto& m=metrics();\n    if(current().ticket){',r'''auto& m=metrics();
    if(windowPending) {
        std::vector<Queue::Ticket> tickets;
        for(const auto& scope:scopes) {
            if(scope.sampling || scope.light)throw std::runtime_error("Unfinished window publication");
            if(scope.ticket)tickets.push_back(scope.ticket);
        }
        if(!tickets.empty() && !deferredQueue().publish(tickets,1))throw std::runtime_error("Window publication rejected");
        windowPending=false;
    }
    if(current().ticket){''')
    return "#define XPU2_WINDOW_DISPATCH_BUILT 1\n"+code
