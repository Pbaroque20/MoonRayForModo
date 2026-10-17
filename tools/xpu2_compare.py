"""Compare simple full-frame RGBA EXRs in raw linear space, without denoising.

Development diagnostic only: not a full AOV/deep/Cryptomatte parity validator.
Both numerical tolerances must be supplied explicitly; there is no implicit
production parity threshold. Each run requires a fresh output directory.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/"tools")]
from xpu2.reference import digest_file
from xpu2.images import read_rgba, compare_rgba
from xpu2_baseline import environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--actual", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--absolute", required=True, type=float)
    parser.add_argument("--relative", required=True, type=float)
    args = parser.parse_args()
    if any(not math.isfinite(x) or x < 0 for x in (args.absolute, args.relative)):
        parser.error("Tolerances must be finite and nonnegative")
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    runtime = args.runtime.resolve()
    env = environment(runtime, folder)
    report = {"status": "failed", "scope": "Full-frame linear RGBA only",
              "absolute_tolerance": args.absolute, "relative_tolerance": args.relative}
    try:
        report["image_tool_sha256"] = digest_file(runtime/"oiiotool.exe")
        a = read_rgba(runtime, args.reference, folder, "reference", env)
        b = read_rgba(runtime, args.actual, folder, "actual", env)
        report.update(compare_rgba(a, b, args.absolute, args.relative))
        report["sources"] = {"reference": a["sha256"], "actual": b["sha256"]}
    except Exception as exc:
        report["error"] = str(exc)
    (folder/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
