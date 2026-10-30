"""Numeric native sampler reuse within a bounded owner-thread material window."""
from pathlib import Path
from . import native_window as base
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=base.adapter
cpp=base.cpp
queue=base.queue
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
ispc=base.ispc

def header(text):
    text=base.header(text)
    text=once(text,'struct WindowBlock {','struct alignas(64) SamplerStorageUnit {unsigned char data[64];};\ninline std::atomic<uint64_t> samplerDiscarded;\nstruct WindowBlock {std::vector<SamplerStorageUnit> sampler;unsigned samplerSize=0;bool samplerStored=false;')
    text=once(text,'inline void clearBlock(WindowBlock& b){','inline void clearBlock(WindowBlock& b){if(b.samplerStored){++samplerDiscarded;b.samplerStored=false;}')
    text=once(text,'inline void windowReset(){','inline void samplerCacheReset();inline void samplerCacheFinish();\ninline void windowReset(){samplerCacheReset();')
    text=once(text,'inline void windowFinish(){','inline void windowFinish(){samplerCacheFinish();')
    extra=(HERE/'native_sampler_cache.inc').read_text().replace(',samplerDiscarded{0}','')
    return text+'\n'+extra

def multisampler(text):
    text=base.multisampler(text)
    text=once(text,'#include "LightSetSampler.isph"','#include "LightSetSampler.isph"\n'+(HERE/'native_sampler_cache.ispc.inc').read_text())
    return once(text,'BsdfSampler_init(&bSampler, arena, bsdf, slice, maxSamplesPerLobe, doIndirect);','xpu2SamplerInit(&bSampler, arena, bsdf, slice, maxSamplesPerLobe, doIndirect);')

def bundled(text):
    text=base.bundled(text)
    text=once(text,'#include "BsdfSampler.isph"','#include "BsdfSampler.isph"\n'+(HERE/'native_sampler_cache.ispc.inc').read_text())
    return once(text,'BsdfSampler_init(&sampler,tls->mArena,bsdf,slice,integrator->mBsdfSamples,indirect);','xpu2SamplerInit(&sampler,tls->mArena,bsdf,slice,integrator->mBsdfSamples,indirect);')
