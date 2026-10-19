"""Measure the full all-lobe BSDF/MIS light contribution instead of its inner lobe."""
from .native_cpu_cost import patch as base_patch
from .native_exclusive_profile import body
PATCH_HANDLER=True
PATCH_DEPENDENCIES=('xpu2/native_cpu_cost.py','xpu2/native_exclusive_profile.py')

def patch(out):
 base_patch(out)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text()
 old='}else { uniform uint64 cpuCost=CPP_xpu2CpuCostBegin(2,getActiveLaneCount()); f=BsdfLobe_eval(lobe,*slice,lsmp.wi,&pdf); CPP_xpu2CpuCostEnd(cpuCost); }'
 assert s.count(old)==1
 s=s.replace(old,'}else f=BsdfLobe_eval(lobe,*slice,lsmp.wi,&pdf);')
 a,b=body(s,'integrateLightSetSample');part=s[a+1:b]
 assert 'return;' not in part
 s=s[:a+1]+'\n uniform uint64 bsdfCost=CPP_xpu2CpuCostBegin(2,getActiveLaneCount());'+part+'\n CPP_xpu2CpuCostEnd(bsdfCost);\n'+s[b:];p.write_text(s)
 p=out/'native_cpu_cost.h';s=p.read_text().replace('"lobe_eval"','"all_lobes_mis"');p.write_text(s)
