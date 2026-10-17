"""Strict evidence checks for native cache-window continuation diagnostics."""
import gzip
import itertools
import json
import struct

FIELDS = ("dims", "depth", "seed", "purpose", "origin")
ORIGINS = (0, 1, 7, 1009, 1013, 1015)
MODES = ("baseline", "restored", "index_only")


def anchors(origin, begin):
    anchor = origin
    result = []
    for index in range(origin, 1048):
        if index >= begin:
            result.append(anchor)
        if index - anchor == 8:
            anchor = index
    return result


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            text = stream.read()
    else:
        text = path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    if not rows or rows[0] != {"schema": 4, "simd_width": 8, "cases": 324, "guards": 6}:
        raise ValueError("Expected complete AVX8 cache-window corpus and guards")
    expected = set(itertools.product((1, 2, 3), (0, 2), (0, 19, 0xffffffff),
                                    (0, 1, 2), ORIGINS))
    if len(rows) != 325:
        raise ValueError("Incomplete cache-window corpus")
    seen = set()
    for i, row in enumerate(rows[1:]):
        if any(type(row.get(k)) is not int for k in FIELDS):
            raise ValueError("Invalid case fields")
        key = tuple(row[k] for k in FIELDS)
        if key not in expected or key in seen or type(row.get("id")) is not int or row["id"] != i:
            raise ValueError("Invalid/duplicate case")
        seen.add(key)
        begin = max(1000, row["origin"])
        if type(row.get("begin")) is not int or row["begin"] != begin:
            raise ValueError("Wrong boundary interval")
        actual = row.get("anchors")
        if (not isinstance(actual, list) or any(type(n) is not int for n in actual)
                or actual != anchors(row["origin"], begin)):
            raise ValueError("Cache-window coverage drift")
        if type(row.get("sequence_hash")) is not int or not 0 <= row["sequence_hash"] <= 0xffffffff:
            raise ValueError("Invalid sequence hash")
        for mode in MODES:
            words = row.get(mode)
            if not isinstance(words, list) or len(words) != (1048 - begin) * row["dims"]:
                raise ValueError("Incomplete boundary samples")
            for word in words:
                if type(word) is not int or not 0 <= word <= 0xffffffff:
                    raise ValueError("Invalid float word")
                value = struct.unpack("<f", struct.pack("<I", word))[0]
                if not 0 <= value < 1:
                    raise ValueError("Sampler value outside [0, 1)")
    return rows


def compare(runs):
    if len(runs) < 2:
        raise ValueError("Repeated native executions required")
    parsed = [read(path) for path in runs]
    records = parsed[0][1:]
    mismatch = dict.fromkeys(MODES[1:], 0)
    affected = {mode: [] for mode in MODES[1:]}
    for row in records:
        for mode in mismatch:
            differences = [i for i, (a, b) in enumerate(zip(row["baseline"], row[mode])) if a != b]
            mismatch[mode] += len(differences)
            if differences:
                affected[mode].append({k: row[k] for k in ("id",) + FIELDS} | {
                    "different_components": len(differences),
                    "sample_indices": sorted({row["begin"] + i // row["dims"] for i in differences})})
    repeat = all(rows == parsed[0] for rows in parsed[1:])
    return {
        "status": "passed" if repeat and mismatch["restored"] == 0 and mismatch["index_only"] > 0 else "failed",
        "scope": "Native AVX8 cache reconstruction at table/R-sequence boundary; no CUDA or image validation",
        "cases": len(records), "executions": len(runs),
        "components_per_mode": sum(len(row["baseline"]) for row in records),
        "all_execution_records_identical": repeat,
        "different_components": mismatch, "affected_cases": affected,
    }
