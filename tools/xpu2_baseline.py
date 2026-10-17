"""Pin and measure the XPU reference without launching Modo or changing a kit.

Generates a self-contained, uniform-sampling sphere fixture. A fresh output
directory is required. --reference reuses the exact fixture and runtime lock
from an earlier run. File hashing warms caches: timings are NOT cold-start
benchmarks. No XPU2 execution or parity certification is claimed.
"""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "kit/MoonRayForModo/python")]
from xpu2.reference import digest_file, identity, inventory, log_metrics, verify


def fixture(segments):
    rings = segments // 2
    vertices = [[math.sin(math.pi*r/rings)*math.cos(2*math.pi*s/segments),
                 math.cos(math.pi*r/rings),
                 math.sin(math.pi*r/rings)*math.sin(2*math.pi*s/segments)]
                for r in range(rings+1) for s in range(segments)]
    faces = [[r*segments+s, r*segments+(s+1)%segments,
              (r+1)*segments+(s+1)%segments, (r+1)*segments+s]
             for r in range(rings) for s in range(segments)]
    return {
        "camera": {"matrix": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,4,1],
                   "focal_mm": 50, "film_mm": 36},
        "materials": {"red": {"color": [.7,.03,.02], "roughness": .3}},
        "lights": [],
        "meshes": [{"name": "XPU2 reference sphere", "identity": "sphere",
                    "vertices": vertices, "faces": faces, "material": "red"}],
        "render_settings": {"sampling_mode": 0, "max_depth": 4,
                            "max_diffuse_depth": 2, "max_glossy_depth": 4},
    }


def environment(runtime, temporary):
    # Deliberately do not inherit renderer/OCIO switches or development DSO paths.
    # Windows, driver and process-launch environment only.
    keys = {"SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE", "LOCALAPPDATA",
            "APPDATA", "PROGRAMDATA", "SYSTEMDRIVE", "NUMBER_OF_PROCESSORS"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keys}
    windows = Path(env.get("SystemRoot", env.get("SYSTEMROOT", r"C:\Windows")))
    env.update(PATH=os.pathsep.join([str(runtime), str(windows/"System32"), str(windows)]),
               TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
               REZ_MOONRAY_ROOT=str(runtime),
               RDL2_DSO_PATH=os.pathsep.join(str(p) for p in
                                           (runtime/"rdl2dso", runtime) if p.is_dir()))
    return env


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--reference", type=Path, help="An existing reference.json lock")
    p.add_argument("--segments", type=int, default=64)
    p.add_argument("--repetitions", type=int, default=2)
    p.add_argument("--threads", type=int, default=0, help="0 uses MoonRay's automatic thread count")
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args()
    if not 8 <= args.segments <= 1024 or not 1 <= args.repetitions <= 10 or args.threads < 0 or args.timeout <= 0:
        p.error("Invalid segments, repetitions, threads or timeout")
    runtime, out = args.runtime.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    temporary = out/"temporary"
    temporary.mkdir()
    report = {"status": "failed", "scope": "XPU reference only; no XPU2 backend",
              "cache_state": "uncontrolled/warmed by inventory; not a cold-load measurement",
              "first_correct_pixel_seconds": None, "runs": [],
              "platform": platform.platform(), "python": sys.version,
              "host_scene_capture_seconds": None,
              "limits": ["Generated fixture, not a Modo capture", "No external textures",
                         "No GPU shading or demand paging exercised",
                         "Runtime hash does not establish binary-to-source provenance"]}
    try:
        if args.reference:
            lock = json.loads(args.reference.read_text(encoding="utf-8"))
            if lock.get("schema") != 1 or lock["identity"] != identity(lock["contract"]):
                raise ValueError("Invalid reference lock")
            source = args.reference.parent/"scene.rdla"
            if digest_file(source) != lock["contract"]["scene_sha256"]:
                raise ValueError("Reference scene changed")
            if args.threads != lock["contract"]["threads"]:
                raise ValueError("Use the same thread setting as the reference")
            verify(runtime, lock["contract"]["runtime"])
            (out/"scene.rdla").write_bytes(source.read_bytes())
        else:
            from moonray_modo import rdla
            began = time.perf_counter()
            snapshot = fixture(args.segments)
            report["fixture_creation_seconds"] = time.perf_counter()-began
            began = time.perf_counter()
            text = rdla.scene_text(snapshot, 256, 144, 4, .3)
            (out/"scene.rdla").write_text(text, encoding="utf-8")
            report["scene_serialization_seconds"] = time.perf_counter()-began
            report["geometry"] = {"vertices": len(snapshot["meshes"][0]["vertices"]),
                                  "faces": len(snapshot["meshes"][0]["faces"])}
            contract = {"runtime": inventory(runtime),
                        "scene_sha256": digest_file(out/"scene.rdla"),
                        "source_manifest_sha256": digest_file(ROOT/"patches/native-windows/sources.json"),
                        "threads": args.threads, "execution_mode": "xpu",
                        "width": 256, "height": 144, "pixel_sample_grid": 4,
                        "source_overrides": "unset; upstream behavior for opt-in patches"}
            lock = {"schema": 1, "identity": identity(contract), "contract": contract}
        (out/"reference.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
        report["reference_identity"] = lock["identity"]
        for index in range(args.repetitions):
            folder = out/("run-%02d" % index)
            folder.mkdir()
            image = folder/"beauty.exr"
            command = [str(runtime/"moonray.exe"), "-in", str(out/"scene.rdla"),
                       "-out", str(image), "-exec_mode", "xpu", "-info",
                       "-stats", str(folder/"stats.csv")]
            if args.threads:
                command += ["-threads", str(args.threads)]
            timed_out = False
            began = time.perf_counter()
            with (folder/"render.log").open("w", encoding="utf-8") as stream:
                try:
                    process = subprocess.run(command, env=environment(runtime, temporary),
                                             cwd=folder, stdout=stream, stderr=subprocess.STDOUT,
                                             timeout=args.timeout,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    exit_code = process.returncode
                except subprocess.TimeoutExpired:
                    timed_out, exit_code = True, None
            elapsed = time.perf_counter()-began
            text = (folder/"render.log").read_text(encoding="utf-8", errors="replace")
            metrics = log_metrics(text)
            present = image.is_file() and image.stat().st_size > 16
            passed = (exit_code == 0 and present and metrics["xpu_selected"]
                      and metrics["gpu_setup_complete"] and not metrics["cpu_fallback"]
                      and not metrics["gpu_error"] and (metrics["gpu_intersection_percent"] or 0) > 0)
            report["runs"].append(dict(metrics, wall_seconds=elapsed, exit_code=exit_code,
                                       timed_out=timed_out, image_created=present,
                                       passed=passed, command=command))
            if not passed:
                break
        # Refuse to certify a baseline if another build replaced its libraries.
        verify(runtime, lock["contract"]["runtime"])
        report["status"] = "passed" if (len(report["runs"]) == args.repetitions
                                       and all(r["passed"] for r in report["runs"])) else "failed"
    except Exception as exc:
        report["error"] = str(exc)
    (out/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}, indent=2))
    for run in report["runs"]:
        print(json.dumps({k: v for k, v in run.items() if k != "command"}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
