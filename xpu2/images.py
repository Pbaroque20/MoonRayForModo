"""Read diagnostic RGBA EXRs without display transforms and locate differences."""
import json
import math
from pathlib import Path
import re
import subprocess

from tools.validate_reference_images import pixels
from .reference import compare_values, digest_file


def read_rgba(runtime, source, folder, label, env):
    source, runtime, folder = Path(source).resolve(), Path(runtime), Path(folder)
    result = subprocess.run([str(runtime/"oiiotool.exe"), "--info", "-v", str(source)],
                            env=env, capture_output=True, text=True, timeout=120,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    info = result.stdout+result.stderr
    (folder/(label+"-info.txt")).write_text(info, encoding="utf-8")
    if result.returncode:
        raise ValueError("Cannot read "+label)
    names = re.findall(r"channel list:\s*([^\r\n]+)", info)
    if len(names) != 1 or [n.strip() for n in names[0].split(",")] != list("RGBA"):
        raise ValueError("Expected one RGBA image; absent channels must not become zero")
    subimages = re.search(r"oiio:subimages:\s*(\d+)", info)
    if (subimages and int(subimages.group(1)) != 1) or any(
            token in info.lower() for token in ("deep data", "data origin", "full/display", "mip-map")):
        raise ValueError("Deep, offset, multipart or mipmapped images need a different comparator")
    metadata = {}
    for field in ("colorInteropID", "oiio:ColorSpace", "PixelAspectRatio"):
        match = re.search(re.escape(field)+r":\s*([^\r\n]+)", info)
        metadata[field] = match.group(1).strip() if match else None
    held, dimensions = {}, None
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
    return {"dimensions": dimensions, "channels": held, "metadata": metadata,
            "sha256": digest_file(source)}


def compare_rgba(reference, actual, absolute=0, relative=0):
    if reference["dimensions"] != actual["dimensions"]:
        raise ValueError("Image dimensions differ")
    if reference["metadata"] != actual["metadata"]:
        raise ValueError("Color-space or pixel-aspect metadata differs")
    width, height = reference["dimensions"]
    a, b = reference["channels"], actual["channels"]
    if set(a) != set("RGBA") or set(b) != set("RGBA"):
        raise ValueError("Missing RGBA channel")
    if any(len(values) != width*height for values in list(a.values())+list(b.values())):
        raise ValueError("Channel size does not match dimensions")
    channels = {key: compare_values(a[key], b[key], absolute, relative) for key in "RGBA"}
    differences = []
    for i in range(width*height):
        peak = max(abs(a[key][i]-b[key][i]) for key in "RGBA")
        if peak:
            differences.append((peak, i))
    def sample(row):
        peak, i = row
        return {"x": i % width, "y_from_bottom": i // width,
                "reference": [a[key][i] for key in "RGBA"],
                "actual": [b[key][i] for key in "RGBA"], "max_absolute_error": peak}
    return {"status": "passed" if all(c["passed"] for c in channels.values()) else "failed",
            "dimensions": [width, height], "channels": channels,
            "exactly_different_pixels": len(differences),
            "first_difference": sample(differences[0]) if differences else None,
            "largest_differences": [sample(row) for row in sorted(differences, reverse=True)[:8]],
            "coordinate_convention": "PFM rows, bottom first; zero-based pixel coordinates",
            "metadata": reference["metadata"]}
