"""Copied-source disjoint CPU sampling probe; does not enable the XPU2 bridge."""
import re,shutil
from pathlib import Path
from .native_gpu_paths import once
PATCH_HANDLER=True

def patch(out):
 for name in ('native_cpu_cost.h','native_exclusive.h'):shutil.copyfile(Path(__file__).with_name(name),out/name)
 p=out/'native_gpu_paths.inc';s=p.read_text();s='#include "native_cpu_cost.h"\n'+s
 s=once(s,'void begin(bool fixedSamples){','void begin(bool fixedSamples){\n xpu2cpu::reset();')
 s=once(s,'void finish(){','void finish(){\n xpu2cpu::finish();');p.write_text(s)
 decl='extern "C" uniform uint64 CPP_xpu2CpuCostBegin(uniform unsigned stage,uniform unsigned lanes);\nextern "C" void CPP_xpu2CpuCostEnd(uniform uint64 token);\n'
 p=out/'PathIntegratorUtil.ispc';s=decl+p.read_text()
 old='else isValid=BsdfSampler_sample(pbrTls,&bSampler,lobeIndex,bsdfSample[0],bsdfSample[1],bsmp[s]);'
 assert s.count(old)==2
 s=s.replace(old,'else { uniform uint64 cpuCost=CPP_xpu2CpuCostBegin((lobe->mName==BSDF_LOBE_LAMBERT || lobe->mName==BSDF_LOBE_FLAT_DIFFUSE)?0:1,getActiveLaneCount()); isValid=BsdfSampler_sample(pbrTls,&bSampler,lobeIndex,bsdfSample[0],bsdfSample[1],bsmp[s]); CPP_xpu2CpuCostEnd(cpuCost); }')
 old='}else f=BsdfLobe_eval(lobe,*slice,lsmp.wi,&pdf);'
 s=once(s,old,'}else { uniform uint64 cpuCost=CPP_xpu2CpuCostBegin(2,getActiveLaneCount()); f=BsdfLobe_eval(lobe,*slice,lsmp.wi,&pdf); CPP_xpu2CpuCostEnd(cpuCost); }')
 for name,stage in [('LightSetSampler_sampleIntersectAndEval',3),('LightTree_sample',4)]:
  matches=list(re.finditer(r'\b'+name+r'\([\s\S]*?;',s));assert len(matches)==1
  m=matches[0];s=s[:m.start()]+'{ uniform uint64 cpuCost=CPP_xpu2CpuCostBegin('+str(stage)+',getActiveLaneCount()); '+m.group()+' CPP_xpu2CpuCostEnd(cpuCost); }'+s[m.end():]
 p.write_text(s)
 p=out/'ShadeBundleHandler.cc';s=p.read_text()
 s='#include <cstdint>\nextern "C" uint64_t CPP_xpu2CpuCostBegin(unsigned,unsigned);\nextern "C" void CPP_xpu2CpuCostEnd(uint64_t);\n'+s
 matches=list(re.finditer(r'shading::shadev\([\s\S]*?;',s));assert len(matches)==2
 for m in reversed(matches):s=s[:m.start()]+'{ auto cpuCost=CPP_xpu2CpuCostBegin(5,workLoadSize); '+m.group()+' CPP_xpu2CpuCostEnd(cpuCost); }'+s[m.end():]
 p.write_text(s)
