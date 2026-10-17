"""Validate native sampler bit patterns without treating RNG tests as image parity."""
import gzip
import itertools
import json
import struct

UNKNOWN = 0xffffffff
FIELDS = ("dims", "depth", "pseudo", "total", "seed", "purpose")
MODES = ("baseline", "chunked", "reordered", "naive_resume")


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            text = stream.read()
    else:
        text = path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    if not rows or rows[0].get("schema") != 1 or rows[0].get("simd_width") != 8:
        raise ValueError("Expected versioned AVX8 sampler corpus")
    header, records = rows[0], rows[1:]
    expected = set(itertools.product((1, 2, 3), (0, 2, 3), (False, True),
                                    (UNKNOWN, 1, 16, 64), (0, 19, UNKNOWN), (0, 1, 2)))
    if header.get("cases") != len(expected) or len(records) != len(expected):
        raise ValueError("Incomplete native corpus")
    seen = set()
    for i, row in enumerate(records):
        key = tuple(row[k] for k in FIELDS)
        if key not in expected or key in seen or row.get("id") != i:
            raise ValueError("Invalid or duplicate native case")
        seen.add(key)
        count = (65 if row["total"] == UNKNOWN else row["total"]) * row["dims"]
        if type(row["sequence_hash"]) is not int or not 0 <= row["sequence_hash"] <= UNKNOWN:
            raise ValueError("Invalid sequence hash")
        for mode in MODES:
            words = row[mode]
            if not isinstance(words, list) or len(words) != count:
                raise ValueError("Incomplete sample values")
            # Uniform samples are finite and in [0, 1); verify the actual bits.
            for word in words:
                if type(word) is not int or not 0 <= word <= UNKNOWN:
                    raise ValueError("Invalid float word")
                value = struct.unpack("<f", struct.pack("<I", word))[0]
                if not 0 <= value < 1:
                    raise ValueError("Sampler value outside [0, 1)")
    return header, records


def compare(runs):
    if len(runs) < 2:
        raise ValueError("At least two native executions required")
    parsed = [read(path) for path in runs]
    reference = parsed[0][1]
    mismatch = {mode: 0 for mode in MODES[1:]}
    affected = {mode: [] for mode in MODES[1:]}
    for row in reference:
        for mode in mismatch:
            errors = sum(a != b for a, b in zip(row["baseline"], row[mode]))
            mismatch[mode] += errors
            if errors:
                affected[mode].append({**{k: row[k] for k in ("id",) + FIELDS},
                                       "different_components": errors})
    repeat = all(rows == reference and header == parsed[0][0] for header, rows in parsed[1:])
    return {
        "status": "passed" if repeat and not mismatch["chunked"] and not mismatch["reordered"]
                  and mismatch["naive_resume"] > 0 else "failed",
        "scope": "Native AVX8 C++/ISPC integrator sampler; not CUDA or rendered image parity",
        "cases": len(reference), "executions": len(runs),
        "components_per_mode": sum(len(row["baseline"]) for row in reference),
        "all_execution_records_identical": repeat,
        "different_components": mismatch, "affected_cases": affected,
    }


def matches_reference(actual, reference):
    """Compare validated bit-pattern records; compression/formatting may differ."""
    return read(actual) == read(reference)
