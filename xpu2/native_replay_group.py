"""Opt-in bounded replay groups; keep byte identity and ownership checks."""
from .native_gpu_paths import once

def patch(out):
    p=out/'native_gpu_early.h';s=p.read_text(encoding='utf-8')
    s=once(s,'inline unsigned windowSize=0;', '''inline unsigned windowSize=0;
inline bool replayGrouped=false;
inline std::atomic<uint64_t> replayGroups{0},replayPackets{0},replayLocks{0},replayReuse{0},replayFallback{0};''')
    s=once(s,'inline void windowReset(){', '''inline void windowReset(){
    const char* grouped=std::getenv("XPU2_REPLAY_GROUPED");replayGrouped=grouped && !std::strcmp(grouped,"1");
    replayGroups=0;replayPackets=0;replayLocks=0;replayReuse=0;replayFallback=0;''')
    s=once(s,'inline void windowFinish(){', r'''inline void windowFinish(){
    if(replayPackets!=replayReuse+replayFallback || replayLocks!=replayGroups)throw std::logic_error("Unaccounted grouped replay packet");
    if(const char* name=std::getenv("XPU2_REPLAY_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"enabled\":%s,\"groups\":%llu,\"packets\":%llu,\"locks\":%llu,\"reused\":%llu,\"fallback\":%llu}\n",replayGrouped?"true":"false",(unsigned long long)replayGroups.load(),(unsigned long long)replayPackets.load(),(unsigned long long)replayLocks.load(),(unsigned long long)replayReuse.load(),(unsigned long long)replayFallback.load());std::fclose(f);
    }''')
    anchor='    if(currentWindow && (currentWindow->record || currentWindow->replay)){'
    s=once(s,anchor,'''    if(replayGrouped && currentWindow && currentWindow->replay && !currentWindow->record){
        // Compare immutable copied payloads and synchronize all completion reads
        // once. Native shader/arena state remains on this window's original owner.
        auto& b=*currentWindow->replay;
        unsigned reused=0;
        {
            std::lock_guard<std::mutex> lock(shaderQueue->mutex);
            ++replayLocks;
            for(unsigned i=0;i<count;++i){
                tokens[i]=0;
                if(b.cursor>=b.packets.size())continue;
                auto& packet=b.packets[b.cursor++];
                const bool changed=windowMismatch || std::memcmp(packet.input,input+i*192,sizeof(packet.input)) || std::memcmp(packet.pixels,pixels+i*8,sizeof(packet.pixels));
                if(changed)++windowChanged;
                if(changed || windowDrop){
                    if(packet.owner){shaderQueue->cancelLocked(*packet.owner);packet.owner.reset();++windowDiscarded;}
                }else if(packet.owner){
                    if((*packet.owner)->done)++windowReady;
                    tokens[i]=reinterpret_cast<uint64_t>(packet.owner.release());++reused;
                }
            }
        }
        ++replayGroups;replayPackets+=count;replayReuse+=reused;replayFallback+=count-reused;windowReused+=reused;
        // Submission takes its own lock. Keep fallback outside the group lock.
        for(unsigned i=0;i<count;++i)if(!tokens[i])tokens[i]=CPP_gpuEarlySubmitRaw(input+i*192,pixels+i*8);
        return;
    }
'''+anchor)
    p.write_text(s,encoding='utf-8')
