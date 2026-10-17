"""Compare simple full-frame RGBA EXRs in raw linear space, without denoising.

Development diagnostic only: not a full AOV/deep/Cryptomatte parity validator.
Both numerical tolerances must be supplied explicitly; there is no implicit
production parity threshold. Each run requires a fresh output directory.
"""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/"tools")]
from validate_reference_images import pixels
from xpu2.reference import compare_values, digest_file
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
              "absolute_tolerance": args.absolute, "relative_tolerance": args.relative,
              "channels": {}, "sources": {}}
    images = []
    try:
        report["image_tool_sha256"] = digest_file(runtime/"oiiotool.exe")
        metadata = []
        for label, source in (("reference", args.reference), ("actual", args.actual)):
            source = source.resolve()
            report["sources"][label] = {"path": str(source), "sha256": digest_file(source)}
            result = subprocess.run([str(runtime/"oiiotool.exe"), "--info", "-v", str(source)],
                                    env=env, capture_output=True, text=True, timeout=120,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            info = result.stdout+result.stderr
            (folder/(label+"-info.txt")).write_text(info, encoding="utf-8")
            if result.returncode:
                raise ValueError("Cannot read "+label)
            names = re.findall(r"channel list:\s*([^\r\n]+)", info)
            if len(names) != 1 or {n.strip() for n in names[0].split(",")} != {"R","G","B","A"}:
                raise ValueError("Expected one RGBA image; absent channels must not become zero")
            if any(token in info.lower() for token in ("deep data", "data origin", "full/display", "2 subimages")):
                raise ValueError("Deep, offset, or multipart images need a different comparator")
            fields = {}
            for field in ("colorInteropID", "oiio:ColorSpace", "PixelAspectRatio"):
                match = re.search(re.escape(field)+r":\s*([^\r\n]+)", info)
                fields[field] = match.group(1).strip() if match else None
            metadata.append(fields)
            held = {}
            dimensions = None
            for suffix, channels in (("rgb", "R,G,B"), ("alpha", "A,A,A")):
                path = folder/(label+"-"+suffix+".pfm")
                converted = subprocess.run([str(runtime/"oiiotool.exe"), str(source),
                                             "--ch", channels, "-o", str(path)],
                                            env=env, capture_output=True, text=True, timeout=120,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if converted.returncode:
                    raise ValueError("Conversion failed: "+converted.stderr)
                size, values = pixels(path)
                if dimensions is not None and size != dimensions:
                    raise ValueError("Channel dimensions differ")
                dimensions = size
                if suffix == "rgb":
                    held.update({channel: values[index::3] for index, channel in enumerate("RGB")})
                else:
                    held["A"] = values[::3]
            images.append((dimensions, held))
        if metadata[0] != metadata[1]:
            raise ValueError("Color-space or pixel-aspect metadata differs")
        if images[0][0] != images[1][0]:
            raise ValueError("Image dimensions differ")
        report["dimensions"] = images[0][0]
        report["metadata"] = metadata[0]
        for channel in "RGBA":
            report["channels"][channel] = compare_values(images[0][1][channel], images[1][1][channel],
                                                         args.absolute, args.relative)
        report["status"] = "passed" if all(c["passed"] for c in report["channels"].values()) else "failed"
    except Exception as exc:
        report["error"] = str(exc)
    (folder/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
