"""Pinned XPU runtime inventory and conservative log measurements."""
import hashlib
import json
import math
import re
from pathlib import Path

BINARY_SUFFIXES = {".exe", ".dll", ".so", ".proxy", ".ptx", ".json"}
TIMINGS = ("Loading scene", "Initialize renderer", "Generating procedurals",
           "Tessellation", "Building BVH", "Building GPU BVH", "Total render prep", "Mcrt time", "Total time")


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def inventory(directory):
    directory = Path(directory).resolve()
    if not (directory / "moonray.exe").is_file():
        raise ValueError("Missing moonray.exe")
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in BINARY_SUFFIXES:
            result[path.relative_to(directory).as_posix()] = {
                "size": path.stat().st_size, "sha256": digest_file(path)}
    return result


def verify(directory, expected):
    actual = inventory(directory)
    changed = sorted(key for key in expected.keys() | actual.keys()
                     if actual.get(key) != expected.get(key))
    if changed:
        raise ValueError("Pinned runtime changed: " + ", ".join(changed[:8]))


def log_metrics(text):
    # Timings are renderer-reported values, not timestamps inferred from buffered
    # stdout. Unrecognized/missing values remain absent, never zero.
    times = {}
    for label in TIMINGS:
        match = re.search(re.escape(label) + r"\s*=\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if match:
            hours, minutes, seconds = map(float, match.groups())
            times[label] = hours * 3600 + minutes * 60 + seconds
    util = re.search(r"GPU bundled intersection ray utilization\s*=\s*([0-9.]+)%", text)
    return {
        "renderer_timings_seconds": times,
        "xpu_selected": "executing an xpu render" in text.lower(),
        "gpu_setup_complete": "GPU: Setup complete" in text,
        "cpu_fallback": "falling back" in text.lower(),
        "gpu_intersection_percent": float(util.group(1)) if util else None,
        "gpu_error": any(term in text for term in
                         ("optixLaunch() failure", "cudaStreamSynchronize() error")),
    }


def compare_values(reference, actual, absolute, relative):
    """Compare corresponding raw linear channel values, not display pixels.

    This does not compare EXR metadata, coverage manifests, or deep topology.
    Values must have already been matched by pixel and channel by the caller.
    """
    if not all(math.isfinite(v) and v >= 0 for v in (absolute, relative)):
        raise ValueError("Invalid tolerance")
    if len(reference) != len(actual) or not len(reference):
        raise ValueError("Missing or unmatched samples")
    maximum = squares = 0.0
    failures = 0
    for expected, observed in zip(reference, actual):
        if not math.isfinite(expected) or not math.isfinite(observed):
            raise ValueError("Nonfinite channel value")
        error = abs(expected - observed)
        maximum = max(maximum, error)
        squares += error * error
        failures += error > absolute + relative * abs(expected)
    return {"passed": failures == 0, "failed_values": failures,
            "maximum_absolute_error": maximum,
            "rms_error": math.sqrt(squares / len(reference)),
            "values": len(reference)}
