"""Host reference for CUDA envelope/bit-pattern validation; no replacement RNG."""
import struct
from .sampler import read, UNKNOWN


def checksum(data):
    h = 2166136261
    for byte in data:
        h = ((h ^ byte) * 16777619) & UNKNOWN
    return h


def packet(words):
    data = struct.pack("<14I", *words)
    return data + struct.pack("<I", checksum(data))


def records(reference):
    _, rows = read(reference)
    output = []
    for row in rows:
        dims = row["dims"]
        count = len(row["baseline"]) // dims
        for index in range(count):
            words = [0x32555058, 1, dims, row["depth"], row["total"], index, int(row["pseudo"]), 6,
                     row["depth"], (77 << 16) | 96, row["seed"] % 3, row["purpose"], 0, row["seed"]]
            src = packet(words)
            supported = row["pseudo"] or row["depth"] >= 3
            values = row["baseline"][index*dims:(index+1)*dims] if supported else []
            if supported:
                words[5] += 1
            output.append({"case": row["id"], "sample": index, "dims": dims,
                           "input": src, "length": 60, "output": packet(words),
                           "result": [0 if supported else 1, row["sequence_hash"], *(values + [0]*(3-len(values)))]})
    # Invalid states exercise validation, including terminal and near-wrap cursors.
    base = [0x32555058, 1, 2, 3, 16, 0, 1, 6, 3, (77 << 16) | 96, 0, 0, 0, 0]
    bad = []
    for field, value in ((0, 0), (1, 2), (2, 4), (4, 0), (5, 16), (5, 17), (6, 2), (7, 5)):
        words = base[:]; words[field] = value
        bad.append((packet(words), 60))
    words = base[:]; words[4] = UNKNOWN; words[5] = UNKNOWN - 8
    bad.append((packet(words), 60))
    corrupt = bytearray(packet(base)); corrupt[32] ^= 1
    bad.append((bytes(corrupt), 60))
    bad.append((packet(base), 59))
    for i, (data, length) in enumerate(bad):
        output.append({"case": "invalid-" + str(i), "sample": 0, "dims": 0, "input": data,
                       "length": length, "output": data, "result": [2, 0, 0, 0, 0]})
    return output


def validate(records, returned, result_words):
    if len(returned) != len(records)*60 or len(result_words) != len(records)*5:
        raise ValueError("Truncated GPU output")
    bad_states = bad_results = components = 0
    supported = unsupported = invalid = 0
    for i, record in enumerate(records):
        bad_states += returned[i*60:(i+1)*60] != record["output"]
        bad_results += list(result_words[i*5:(i+1)*5]) != record["result"]
        status = record["result"][0]
        supported += status == 0
        unsupported += status == 1
        invalid += status == 2
        if status == 0:
            components += record["dims"]
    return {"passed": bad_states == 0 and bad_results == 0,
            "records": len(records), "supported_records": supported,
            "unsupported_records": unsupported, "invalid_records": invalid,
            "compared_sample_components": components,
            "state_mismatch_records": bad_states, "sample_or_status_mismatch_records": bad_results}
