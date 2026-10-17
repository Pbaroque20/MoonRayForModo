"""Compile and execute isolated CUDA sampler diagnostics; never install a runtime."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xpu2.cuda_samples import records, validate


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bind(lib, name, args):
    fn = getattr(lib, name)
    fn.argtypes = args
    fn.restype = C.c_int
    def call(*values):
        result = fn(*values)
        if result:
            raise RuntimeError(name + " returned " + str(result))
    return call


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--reference", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    out, source = a.output.resolve(), a.source.resolve()
    if out.is_relative_to(source):
        p.error("Output must be isolated from shared source/runtime")
    out.mkdir(parents=True, exist_ok=False)
    toolkit = source / "toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin"
    with os.add_dll_directory(str(toolkit)):
        builtins = C.WinDLL(str(toolkit / "nvrtc-builtins64_128.dll"))
        nvrtc = C.WinDLL(str(toolkit / "nvrtc64_120_0.dll"))
    driver = C.WinDLL("nvcuda.dll")
    ptr, u64, size, integer = C.c_void_p, C.c_uint64, C.c_size_t, C.c_int
    init = bind(driver, "cuInit", [C.c_uint])
    device_get = bind(driver, "cuDeviceGet", [C.POINTER(integer), integer])
    name_get = bind(driver, "cuDeviceGetName", [ptr, integer, integer])
    capability = bind(driver, "cuDeviceComputeCapability", [C.POINTER(integer), C.POINTER(integer), integer])
    version_get = bind(driver, "cuDriverGetVersion", [C.POINTER(integer)])
    create = bind(driver, "cuCtxCreate_v2", [C.POINTER(ptr), C.c_uint, integer])
    destroy = bind(driver, "cuCtxDestroy_v2", [ptr])
    alloc = bind(driver, "cuMemAlloc_v2", [C.POINTER(u64), size])
    h2d = bind(driver, "cuMemcpyHtoD_v2", [u64, ptr, size])
    d2h = bind(driver, "cuMemcpyDtoH_v2", [ptr, u64, size])
    sync = bind(driver, "cuCtxSynchronize", [])
    load = bind(driver, "cuModuleLoadData", [C.POINTER(ptr), ptr])
    get_function = bind(driver, "cuModuleGetFunction", [C.POINTER(ptr), ptr, C.c_char_p])
    stream_create = bind(driver, "cuStreamCreate", [C.POINTER(ptr), C.c_uint])
    launch = bind(driver, "cuLaunchKernel", [ptr, *([C.c_uint]*7), ptr, C.POINTER(ptr), ptr])
    init(0)
    device, major, minor, version = integer(), integer(), integer(), integer()
    device_get(C.byref(device), 0); capability(C.byref(major), C.byref(minor), device)
    name = C.create_string_buffer(256); name_get(name, 256, device); version_get(C.byref(version))
    print("CUDA device: " + name.value.decode(), flush=True)
    kernel = ROOT / "xpu2/sampler_cuda.cu"
    code = kernel.read_bytes()
    (out / "sampler_cuda.cu").write_bytes(code)
    dependencies = [kernel, a.reference, toolkit / "nvrtc64_120_0.dll", toolkit / "nvrtc-builtins64_128.dll"]
    before = {str(path): sha(path) for path in dependencies}
    program = ptr()
    compile_flags = ["--std=c++14", "--gpu-architecture=compute_" + str(major.value) + str(minor.value),
                     "--fmad=false", "--ftz=false", "--prec-div=true", "--prec-sqrt=true"]
    bind(nvrtc, "nvrtcCreateProgram", [C.POINTER(ptr), C.c_char_p, C.c_char_p, integer, ptr, ptr])(
        C.byref(program), code, b"sampler_cuda.cu", 0, None, None)
    try:
        compile_fn = nvrtc.nvrtcCompileProgram
        compile_fn.argtypes = [ptr, integer, C.POINTER(C.c_char_p)]
        options = (C.c_char_p*len(compile_flags))(*(s.encode() for s in compile_flags))
        status = compile_fn(program, len(compile_flags), options)
        length = size()
        bind(nvrtc, "nvrtcGetProgramLogSize", [ptr, C.POINTER(size)])(program, C.byref(length))
        log = C.create_string_buffer(length.value)
        bind(nvrtc, "nvrtcGetProgramLog", [ptr, ptr])(program, log)
        (out / "compile.log").write_bytes(log.value)
        if status:
            raise RuntimeError("NVRTC compilation failed: " + str(status) + "; see compile.log")
        bind(nvrtc, "nvrtcGetPTXSize", [ptr, C.POINTER(size)])(program, C.byref(length))
        ptx = C.create_string_buffer(length.value)
        bind(nvrtc, "nvrtcGetPTX", [ptr, ptr])(program, ptx)
        (out / "sampler.ptx").write_bytes(ptx.value)
    finally:
        bind(nvrtc, "nvrtcDestroyProgram", [C.POINTER(ptr)])(C.byref(program))
    expected = records(a.reference)
    count = len(expected)
    context = ptr()
    create(C.byref(context), 0, device)
    reports = []
    try:
        module, function = ptr(), ptr()
        load(C.byref(module), ptx); get_function(C.byref(function), module, b"sampler")
        streams = [ptr(), ptr()]
        for stream in streams:
            stream_create(C.byref(stream), 1)
        buffers = [u64() for _ in range(4)]
        for buffer, length in zip(buffers, (count*60, count*4, count*60, count*20)):
            alloc(C.byref(buffer), length)
        for run, block in enumerate((64, 128, 256)):
            shuffled = list(expected); random.Random(8123+run).shuffle(shuffled)
            raw = b"".join(r["input"] for r in shuffled)
            lengths = struct.pack("<" + str(count) + "I", *(r["length"] for r in shuffled))
            src, lens = C.create_string_buffer(raw), C.create_string_buffer(lengths)
            h2d(buffers[0], src, len(raw)); h2d(buffers[1], lens, len(lengths))
            # Two CUDA streams; uploads/downloads remain synchronous in this check.
            split = count // 2
            for start, n, stream in ((0, split, streams[0]), (split, count-split, streams[1])):
                args = [u64(buffers[i].value + start*stride) for i, stride in enumerate((60, 4, 60, 20))]
                args.append(C.c_uint(n))
                parameters = (ptr*len(args))(*(C.cast(C.byref(v), ptr) for v in args))
                launch(function, (n+block-1)//block, 1, 1, block, 1, 1, 0, stream, parameters, None)
            sync()
            returned = C.create_string_buffer(count*60)
            words = (C.c_uint*(count*5))()
            d2h(returned, buffers[2], count*60); d2h(words, buffers[3], count*20)
            summary = validate(shuffled, returned.raw, words)
            summary.update(block_size=block, streams=2,
                           state_output_sha256=hashlib.sha256(returned.raw).hexdigest(),
                           result_output_sha256=hashlib.sha256(bytes(words)).hexdigest())
            reports.append(summary)
            (out / ("states-" + str(run) + ".bin")).write_bytes(returned.raw)
            (out / ("results-" + str(run) + ".bin")).write_bytes(bytes(words))
            print(json.dumps(summary), flush=True)
    finally:
        destroy(context)  # Releases all test streams, modules and allocations.
    if before != {str(path): sha(path) for path in dependencies}:
        raise ValueError("CUDA source/reference/compiler drift")
    report = {"status": "passed" if all(r["passed"] for r in reports) else "failed",
              "scope": "Real CUDA transport and pseudo-random sampling subset; no shading/rendered parity",
              "device": name.value.decode(), "compute_capability": [major.value, minor.value],
              "cuda_driver_api": version.value, "compile_flags": compile_flags,
              "inputs_sha256": before, "ptx_sha256": sha(out / "sampler.ptx"), "runs": reports}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
