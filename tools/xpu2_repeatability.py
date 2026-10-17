"""Repeat the pinned fixture in vector/XPU at one and fixed multiple threads.

No Modo or production kit modifications. Exit 0 means exact numeric RGBA
repeatability observed in this matrix; 2 means measured differences; 1 means
an invalid/incomplete experiment. No threshold is relaxed to manufacture a pass.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/"tools")]
from xpu2.reference import digest_file, identity, verify, log_metrics
from xpu2.images import read_rgba, compare_rgba
from xpu2_baseline import environment


def cases(threads):
    if threads < 2:
        raise ValueError("Multithread case needs at least two threads")
    return [(mode+"-"+str(count), mode, count)
            for mode in ("vectorized", "xpu") for count in (1, threads)]


def successful(mode, requested_threads, code, log, stats, image):
    metrics = log_metrics(log)
    match = re.search(r"^Thread\(s\),(\d+)\s*$", stats, re.MULTILINE)
    actual_threads = int(match.group(1)) if match else None
    selected = (metrics["xpu_selected"] if mode == "xpu" else
                "executing a vectorized render" in log.lower())
    gpu_ok = (metrics["gpu_setup_complete"] and
              (metrics["gpu_intersection_percent"] or 0) > 0) if mode == "xpu" else True
    passed = (code == 0 and image and selected and gpu_ok
              and actual_threads == requested_threads
              and not metrics["cpu_fallback"] and not metrics["gpu_error"])
    return dict(metrics, actual_threads=actual_threads, passed=bool(passed))


def gpu_identity():
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,uuid",
                                 "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--threads", type=int, default=12)
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args()
    if args.threads < 2 or not 2 <= args.repetitions <= 10 or args.timeout <= 0:
        p.error("Use >=2 threads, 2..10 repetitions and positive timeout")
    runtime, out = args.runtime.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    temporary = out/"temporary"
    temporary.mkdir()
    report = {"status": "incomplete", "runs": [], "within_case": {}, "cross_case": {},
              "scope": "Fixed-sample RGBA fixture; no adaptive, denoising, textures or AOV certification",
              "frame": 0, "lock_frame_noise": True, "gpu": gpu_identity(),
              "cpu": os.environ.get("PROCESSOR_IDENTIFIER"), "logical_cpus": os.cpu_count(),
              "timings": "Not controlled performance measurements; caches are warmed by hashing"}
    images = {}
    try:
        lock = json.loads((ROOT/"xpu2/reference/reference.json").read_text(encoding="utf-8"))
        if identity(lock["contract"]) != lock["identity"]:
            raise ValueError("Reference lock checksum mismatch")
        original = ROOT/"xpu2/reference/scene.rdla"
        if digest_file(original) != lock["contract"]["scene_sha256"]:
            raise ValueError("Pinned fixture changed")
        print("Verifying pinned runtime", flush=True)
        verify(runtime, lock["contract"]["runtime"])
        # A diagnostic derivative, not a mutation of the byte-pinned original.
        scene = original.read_bytes() + b'\nSceneVariables { ["frame"] = 0, ["min_frame"] = 0, ["max_frame"] = 0, ["lock_frame_noise"] = true }\n'
        (out/"scene.rdla").write_bytes(scene)
        report.update(reference_identity=lock["identity"],
                      diagnostic_scene_sha256=digest_file(out/"scene.rdla"))
        env = environment(runtime, temporary)
        # Interleave cases to avoid always comparing only first-start vs warm-start.
        for repetition in range(args.repetitions):
            for label, mode, threads in cases(args.threads):
                key = label+"-"+str(repetition)
                folder = out/key
                folder.mkdir()
                print("Rendering "+key, flush=True)
                command = [str(runtime/"moonray.exe"), "-in", str(out/"scene.rdla"),
                           "-out", str(folder/"beauty.exr"), "-exec_mode", mode,
                           "-threads", str(threads), "-info", "-stats", str(folder/"stats.csv")]
                began = time.perf_counter()
                with (folder/"render.log").open("w", encoding="utf-8") as stream:
                    try:
                        done = subprocess.run(command, cwd=folder, env=env,
                                              stdout=stream, stderr=subprocess.STDOUT,
                                              timeout=args.timeout,
                                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        code = done.returncode
                    except subprocess.TimeoutExpired:
                        code = None
                elapsed = time.perf_counter()-began
                log = (folder/"render.log").read_text(encoding="utf-8", errors="replace")
                stats = (folder/"stats.csv").read_text(encoding="utf-8", errors="replace") if (folder/"stats.csv").exists() else ""
                image = folder/"beauty.exr"
                result = successful(mode, threads, code, log, stats, image.exists() and image.stat().st_size > 16)
                result.update(case=label, repetition=repetition, exit_code=code, wall_seconds=elapsed)
                report["runs"].append(result)
                if not result["passed"]:
                    raise ValueError("Invalid render: "+key)
                images[key] = read_rgba(runtime, image, folder, "raw", env)
        for label, _, _ in cases(args.threads):
            report["within_case"][label] = [
                dict(compare_rgba(images[label+"-"+str(i)], images[label+"-"+str(j)]),
                     repetitions=[i, j])
                for i in range(args.repetitions) for j in range(i+1, args.repetitions)]
        anchor = images["vectorized-1-0"]
        report["cross_case"] = {label: compare_rgba(anchor, images[label+"-0"])
                                for label, _, _ in cases(args.threads) if label != "vectorized-1"}
        verify(runtime, lock["contract"]["runtime"])
        if gpu_identity() != report["gpu"]:
            raise ValueError("GPU/driver identity changed during experiment")
        exact = all(row["status"] == "passed" for group in report["within_case"].values() for row in group)
        report["status"] = "exact_repeatability_observed" if exact else "repeatability_differences"
    except Exception as exc:
        report["error"] = str(exc)
    (out/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report["status"], out/"report.json", flush=True)
    return {"exact_repeatability_observed": 0, "repeatability_differences": 2}.get(report["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
