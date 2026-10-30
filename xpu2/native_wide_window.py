"""Isolated 16-block experiment with a bounded 512-packet numeric queue."""
from . import native_window as base
from .native_gpu_paths import once
adapter=base.adapter
cpp=base.cpp
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
ispc=base.ispc
multisampler=base.multisampler
bundled=base.bundled

def queue(text):
    text=base.queue(text)
    return once(text, 'capacity=std::min(64,std::max(0,std::atoi(p)))',
                'capacity=std::min(512,std::max(0,std::atoi(p)))')

def header(text):
    text=base.header(text)
    text=once(text, 'WindowBlock blocks[4];', 'WindowBlock blocks[16];')
    return once(text, 'std::min(4,std::atoi(size))', 'std::min(16,std::atoi(size))')
