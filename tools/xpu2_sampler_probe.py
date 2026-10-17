"""Build/run an isolated native AVX sampler corpus from retained reference inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xpu2.reference import inventory, verify
from xpu2.sampler import compare, matches_reference, compare_handoffs
from xpu2.window_samples import compare as compare_windows, read as read_windows


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path,
                        help="Existing isolated ray-probe build with retained inputs")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference", type=Path, help="Pinned .jsonl or .jsonl.gz native corpus")
    parser.add_argument("--handoff", action="store_true", help="Test serialized native sampler handoffs")
    parser.add_argument("--tables", action="store_true", help="Export native integrator sample tables")
    parser.add_argument("--cmj", action="store_true", help="Broader known-count 2D native corpus")
    parser.add_argument("--window", action="store_true", help="Test native table/cache boundary continuation")
    args = parser.parse_args()
    if args.window and (args.handoff or args.tables or args.cmj):
        parser.error("--window is a separate experiment")
    if (args.cmj or args.tables) and args.handoff:
        parser.error("--cmj and --handoff are separate experiments")
    if args.handoff and not args.reference:
        parser.error("--handoff requires the pinned --reference corpus")
    build, out = args.build.resolve(), args.output.resolve()
    manifest = json.loads((build / "build-inputs.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "built":
        raise ValueError("Completed isolated reference build required")
    source = Path(manifest["source"])
    if out.is_relative_to(source) or out.is_relative_to(build):
        raise ValueError("Use an isolated fresh output folder")
    out.mkdir(parents=True, exist_ok=False)
    runtime = build / "control"
    runtime_lock = inventory(runtime)
    frozen = [(build / item["copy"], item["sha256"]) for item in manifest["inputs"]]
    for path, digest in frozen:
        if sha(path) != digest:
            raise ValueError("Retained build input drift: " + str(path))
    # Preprocess the current headers once into a frozen translation unit. The
    # existing sampler table/ISPC objects are retained, not rebuilt from source.
    original_command = manifest["compile_command"]
    compiler = original_command[0]
    flags = original_command[1:original_command.index("-iquote")]
    env = dict(os.environ)
    env["PATH"] = str(runtime) + os.pathsep + str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
    cpp = out / "sampler_probe.cc"
    cpp.write_bytes((ROOT / "xpu2" / ("sampler_window_probe.cc" if args.window else "sampler_handoff.cc" if args.handoff else "sampler_probe.cc")).read_bytes())
    if args.handoff or args.window:
        (out / "sampler_state.h").write_bytes((ROOT / "xpu2/sampler_state.h").read_bytes())
    if args.window:
        (out / "sampler_window.h").write_bytes((ROOT / "xpu2/sampler_window.h").read_bytes())
        (out / "sampler_exchange.h").write_bytes((ROOT / "xpu2/sampler_exchange.h").read_bytes())
    def run(command, name, stdout=None):
        with (out / (name + ".log")).open("w", encoding="utf-8") as log:
            if stdout:
                with stdout.open("w", encoding="utf-8") as data:
                    done = subprocess.run(command, cwd=out, env=env, stdout=data, stderr=log,
                                          timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                done = subprocess.run(command, cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode:
            raise RuntimeError(name + " failed; see " + str(out / (name + ".log")))
    print("Freezing native sampler headers", flush=True)
    pp = out / "sampler.ii"
    run([compiler, *flags, "-E", str(cpp), "-o", str(pp)], "preprocess")
    print("Compiling native AVX sampler", flush=True)
    obj = out / "sampler.obj"
    run([compiler, *flags, "-c", str(pp), "-o", str(obj)], "compile")
    rsp = out / "link.rsp"
    rsp.write_bytes((build / "control.rsp").read_bytes())
    exe = out / "sampler.exe"
    print("Linking retained native inputs", flush=True)
    run([compiler, "-O3", "-pthread", "-o", str(exe), str(obj), "@" + str(rsp)], "link")
    if args.tables:
        run([str(exe), "1", "tables"], "tables", out / "tables.json")
    if args.window:
        run([str(exe), "1", "moebius"], "moebius", out / "moebius.json")
    outputs = []
    for index, workers in enumerate((1, 1, 4)):
        print("Sampling with " + str(workers) + " CPU workers", flush=True)
        output = out / ("samples-" + str(index) + ".jsonl")
        run([str(exe), str(workers)] + (["cmj"] if args.cmj else []), "run-" + str(index), output)
        outputs.append(output)
    result = (compare_windows(outputs) if args.window else
              compare_handoffs(outputs, args.reference) if args.handoff else compare(outputs))
    if args.reference and not args.handoff:
        result["reference_match"] = (read_windows(outputs[0]) == read_windows(args.reference) if args.window
                                     else matches_reference(outputs[0], args.reference))
        result["reference_sha256"] = sha(args.reference)
        if not result["reference_match"]:
            result["status"] = "failed"
    # Detect header drift during this build, not just retained-object drift.
    second_pp = out / "sampler-verify.ii"
    run([compiler, *flags, "-E", str(cpp), "-o", str(second_pp)], "preprocess-verify")
    if sha(pp) != sha(second_pp):
        raise ValueError("Native headers changed during probe")
    for path, digest in frozen:
        if sha(path) != digest:
            raise ValueError("Retained build input changed")
    verify(runtime, runtime_lock)
    if args.tables:
        table_meta = json.loads((out / "tables.json").read_text(encoding="utf-8"))
        if table_meta != {"one_count": 4194304, "two_count": 4194304}:
            raise ValueError("Unexpected native table dimensions")
        result["tables"] = {name: {"sha256": sha(out / name), "bytes": (out / name).stat().st_size}
                            for name in ("samples1d.bin", "samples2d.bin")}
    if args.reference:
        result["reference_sha256"] = sha(args.reference)
    if args.window:
        if json.loads((out / "moebius.json").read_text(encoding="utf-8")) != {"count": 16384}:
            raise ValueError("Unexpected native Moebius table size")
        result["moebius"] = {"sha256": sha(out / "moebius.bin"), "bytes": (out / "moebius.bin").stat().st_size}
        result["window_header_sha256"] = sha(out / "sampler_window.h")
        result["exchange_header_sha256"] = sha(out / "sampler_exchange.h")
        result["exchange_protocol"] = "XWB2-XWO2"
    if args.handoff or args.window:
        result["state_header_sha256"] = sha(out / "sampler_state.h")
    result.update({
        "build_manifest_sha256": sha(build / "build-inputs.json"),
        "cpp_sha256": sha(cpp), "preprocessed_sha256": sha(pp),
        "executable_sha256": sha(exe), "compile_flags": flags,
        "runtime_inventory": runtime_lock,
        "workers": [1, 1, 4],
        "corpus_sha256": [sha(p) for p in outputs],
        "scope_build": "Current frozen headers with retained native objects; not a clean runtime build",
    })
    (out / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "cases", "components_per_mode",
                                          "all_execution_records_identical", "different_components")}))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
