"""Connect numeric direct-light jobs to native light-sample preparation/consumption."""
from pathlib import Path
from .native_gpu_paths import once
from .native_light_unit import ISPC as CAPTURE
HERE=Path(__file__).resolve().parent
DECL='\nextern "C" uniform int CPP_lightMode(uniform PbrTLState *uniform tls);\nextern "C" uniform uint64 CPP_lightSubmit(const uniform float *uniform input,uniform unsigned int count);\nextern "C" void CPP_lightCollect(uniform PbrTLState *uniform tls,uniform uint64 handle,uniform float *uniform result,uniform unsigned int count);\nextern "C" void CPP_lightUsed(uniform unsigned int gpu,uniform unsigned int cpu);\nextern "C" void CPP_lightVerified(uniform unsigned int checked,uniform unsigned int mismatch);\n'

def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 s='namespace xpu2::lightqueue {void begin();void end();}\n'+s
 s=once(s,'inline void earlyReset(){','inline void earlyReset(){xpu2::lightqueue::begin();')
 s=once(s,'inline void earlyFinish(){','inline void earlyFinish(){xpu2::lightqueue::end();')
 s+='\n'+(HERE/'native_light_queue.h').read_text();p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text()
 # Copy the qualified input encoding; reference-output capture is not part of the new packet.
 start=CAPTURE.index('    if(lobe->mName');stop=CAPTURE.index('            expected[o]=')
 pack=CAPTURE[start:stop]
 pack=pack.replace('return;','return false;').replace('        float weight=powerHeuristic(ni*lsmp.misPdf,nk*pdf);\n','')
 pack=pack.replace('        uniform float input[8*32],expected[8*8];uniform unsigned int count=0;\n','')
 pack=pack.replace('uniform int b=count*32,o=count*8;','uniform int b=lane*32;')
 pack='inline uniform bool xpu2PackLight(const varying BsdfLobe *uniform lobe,const varying BsdfSlice &slice,\n    const varying LightSample &lsmp,const varying Color &throughput,float ni,int nk,uniform float *uniform input){\n    for(uniform int j=0;j<8*32;++j)input[j]=0.f;\n'+pack+'        }\n    }\n    return any(eligible);\n}\n'
 start=s.index('inline void\nintegrateLightSetSample(');end=s.index('\nextern "C" bool\nCPP_aov',start)
 original=s[start:end]
 loop=original[original.index('    for (uniform int k = 0; k < lobeCount; ++k) {'):original.index('        // Evaluate the lobe')]
 prepare='inline uniform uint64 xpu2PrepareDirectLight(const varying LightSetSampler &lSampler,uniform int lightIndex,\n    const varying BsdfSampler &bSampler,const varying PathVertex &pv,const varying LightSample &lsmp,\n    const varying Rdl2LightSetList *uniform parentLobeLightSets){\n    const varying BsdfSlice *uniform slice=BsdfSampler_getBsdfSlice(&bSampler);\n    BsdfLobeType flags=BsdfSlice_getSurfaceFlags(slice,*BsdfSampler_getBsdf(&bSampler),lsmp.wi);\n    const uniform int lobeCount=BsdfSampler_getLobeCount(&bSampler);\n    if(lobeCount>16)return 0;\n    uniform float input[16*8*32];for(uniform int j=0;j<16*8*32;++j)input[j]=0.f;\n    uniform bool anyPrepared=false;\n'+loop+'        if(xpu2PackLight(lobe,*slice,lsmp,pv.pathThroughput,(float)LightSetSampler_getLightSampleCount(&lSampler),BsdfSampler_getLobeSampleCount(&bSampler,k),&input[k*8*32]))anyPrepared=true;\n    }\n    return anyPrepared?CPP_lightSubmit(input,lobeCount*8):0;\n}\n'
 body=once(original,'const varying Rdl2LightSetList * uniform parentLobeLightSets)','const varying Rdl2LightSetList * uniform parentLobeLightSets,const uniform float *uniform gpuResults,uniform int lightMode)')
 body=once(body,'        Color f = BsdfLobe_eval(lobe, *slice, lsmp.wi, &pdf);','        Color f;bool useGpu=false;\n        if(gpuResults!=NULL)useGpu=gpuResults[k*8*9+programIndex*9+8]==1.f;\n        if(useGpu && lightMode!=2){\n            f=Color_ctor(gpuResults[k*8*9+programIndex*9],gpuResults[k*8*9+programIndex*9+1],gpuResults[k*8*9+programIndex*9+2]);\n            pdf=gpuResults[k*8*9+programIndex*9+3];\n        }else f=BsdfLobe_eval(lobe,*slice,lsmp.wi,&pdf);\n')
 body=once(body,'        Color t = factor * f * powerHeuristic(ni * lsmp.misPdf, nk * pdf);','        Color t;\n        if(useGpu && lightMode!=2)t=Color_ctor(gpuResults[k*8*9+programIndex*9+4],gpuResults[k*8*9+programIndex*9+5],gpuResults[k*8*9+programIndex*9+6]);\n        else t=factor*f*powerHeuristic(ni*lsmp.misPdf,nk*pdf);\n        if(useGpu && lightMode==2){\n            bool bad=intbits(f.r)!=intbits(gpuResults[k*8*9+programIndex*9]) || intbits(f.g)!=intbits(gpuResults[k*8*9+programIndex*9+1]) || intbits(f.b)!=intbits(gpuResults[k*8*9+programIndex*9+2]) || intbits(pdf)!=intbits(gpuResults[k*8*9+programIndex*9+3]) || intbits(t.r)!=intbits(gpuResults[k*8*9+programIndex*9+4]) || intbits(t.g)!=intbits(gpuResults[k*8*9+programIndex*9+5]) || intbits(t.b)!=intbits(gpuResults[k*8*9+programIndex*9+6]);\n            CPP_lightVerified(getActiveLaneCount(),getActiveLaneCount(bad));\n        }\n        if(lightMode)CPP_lightUsed(getActiveLaneCount(useGpu),getActiveLaneCount(!useGpu));\n')
 s=s[:start]+DECL+pack+prepare+body+s[end:]
 start=s.index('void\ndrawLightSamples(');brace=s.index('{',start);depth=1;end=brace+1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 body=s[start:end]
 anchor='    // Loop over each light\' samples'
 body=once(body,anchor,'    uniform int lightMode=CPP_lightMode(pbrTls);\n    if(!all(pv.nonMirrorDepth==0) || reduce_max(lightSampleCount)>16 || BsdfSampler_getLobeCount(&bSampler)>16)lightMode=0;\n    uniform uint64 lightHandles[16];varying bool lightValid[16];\n    for(uniform int j=0;j<16;++j){lightHandles[j]=0;unmasked {lightValid[j]=false;}}\n'+anchor)
 call='        integrateLightSetSample(lSampler, lightIndex, bSampler, pv, currSamp,\n                clampingDepth, clampingValue, parentLobeLightSets);'
 body=once(body,call,'        if(lightMode){\n            lightHandles[i]=xpu2PrepareDirectLight(lSampler,lightIndex,bSampler,pv,currSamp,parentLobeLightSets);\n            lightValid[i]=true;\n        }else integrateLightSetSample(lSampler,lightIndex,bSampler,pv,currSamp,clampingDepth,clampingValue,parentLobeLightSets,NULL,0);')
 body=body[:-1]+'    if(lightMode){\n        for(uniform int i=0;i<reduce_max(lightSampleCount);++i){\n            uniform float results[16*8*9];\n            CPP_lightCollect(pbrTls,lightHandles[i],results,BsdfSampler_getLobeCount(&bSampler)*8);\n            if(lightValid[i])integrateLightSetSample(lSampler,lightIndex,bSampler,pv,lsmp[i],clampingDepth,clampingValue,parentLobeLightSets,results,lightMode);\n        }\n    }\n}'
 s=s[:start]+body+s[end:];p.write_text(s)
