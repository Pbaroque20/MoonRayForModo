"""Batch light samples inside their existing native owner lifetime."""
from .native_gpu_paths import once

def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 s=once(s,'if(!count||count>128)','if(!count||count>512)')
 s=once(s,'                    void* args[]={&s.input,&s.output,&s.count};','''                    if(const char* stop=std::getenv("XPU2_LIGHT_HOLD_PACKET")){
                        if(batches.load()+1==std::strtoull(stop,nullptr,10)){
                            std::fprintf(stdout,"@@XPU2_LIGHT_GROUP_HELD\\n");std::fflush(stdout);
                            std::this_thread::sleep_for(std::chrono::milliseconds(1000));
                        }
                    }
                    void* args[]={&s.input,&s.output,&s.count};''')

 s+='\nextern "C" bool CPP_lightGroup(){static const bool grouped=[](){const char* p=std::getenv("XPU2_LIGHT_GROUP");return p && !std::strcmp(p,"1");}();return grouped;}\n'
 p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text()
 start=s.index('inline uniform uint64 xpu2PrepareDirectLight(');end=s.index('inline void\nintegrateLightSetSample(',start)
 old=s[start:end]
 packed=once(old,'inline uniform uint64 xpu2PrepareDirectLight','inline uniform bool xpu2PackDirectLight')
 packed=once(packed,'const varying Rdl2LightSetList *uniform parentLobeLightSets){','const varying Rdl2LightSetList *uniform parentLobeLightSets,uniform float *uniform input){')
 packed=once(packed,'uniform float input[16*8*32];for(uniform int j=0;j<16*8*32;++j)input[j]=0.f;','for(uniform int j=0;j<lobeCount*8*32;++j)input[j]=0.f;')
 packed=once(packed,'return anyPrepared?CPP_lightSubmit(input,lobeCount*8):0;','return anyPrepared;')
 wrapper=old[:old.index('    const varying BsdfSlice')]+"    uniform float input[16*8*32];\n    return xpu2PackDirectLight(lSampler,lightIndex,bSampler,pv,lsmp,parentLobeLightSets,input)?CPP_lightSubmit(input,BsdfSampler_getLobeCount(&bSampler)*8):0;\n}\n"
 s=s[:start]+'extern "C" uniform bool CPP_lightGroup();\n'+packed+wrapper+s[end:]
 anchor='    uniform uint64 lightHandles[16];varying bool lightValid[16];'
 s=once(s,anchor,'''    const uniform int lightLanes=BsdfSampler_getLobeCount(&bSampler)*8;
    const uniform int groupLanes=reduce_max(lightSampleCount)*lightLanes;
    uniform bool groupLight=lightMode && CPP_lightGroup() && groupLanes>0 && groupLanes<=512;
    uniform float groupInput[512*32],groupResults[512*9];
    uniform bool groupPrepared=false;
    if(groupLight)for(uniform int j=0;j<groupLanes*32;++j)groupInput[j]=0.f;
'''+anchor)
 s=once(s,'            lightHandles[i]=xpu2PrepareDirectLight(lSampler,lightIndex,bSampler,pv,currSamp,parentLobeLightSets);','''            if(groupLight){
                if(xpu2PackDirectLight(lSampler,lightIndex,bSampler,pv,currSamp,parentLobeLightSets,&groupInput[i*lightLanes*32]))groupPrepared=true;
            }else lightHandles[i]=xpu2PrepareDirectLight(lSampler,lightIndex,bSampler,pv,currSamp,parentLobeLightSets);''')
 s=once(s,'    if(lightMode){\n        for(uniform int i=0;i<reduce_max(lightSampleCount);++i){','''    if(lightMode){
        if(groupLight){
            uniform uint64 handle=groupPrepared?CPP_lightSubmit(groupInput,groupLanes):0;
            CPP_lightCollect(pbrTls,handle,groupResults,groupLanes);
        }
        for(uniform int i=0;i<reduce_max(lightSampleCount);++i){''')
 s=once(s,'            CPP_lightCollect(pbrTls,lightHandles[i],results,BsdfSampler_getLobeCount(&bSampler)*8);','            if(!groupLight)CPP_lightCollect(pbrTls,lightHandles[i],results,lightLanes);')
 s=once(s,'parentLobeLightSets,results,lightMode);','parentLobeLightSets,groupLight?&groupResults[i*lightLanes*9]:results,lightMode);')
 p.write_text(s)
