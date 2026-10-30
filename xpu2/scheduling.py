"""Bounded single-owner scheduling model, NOT a native renderer or RNG.

Workers may execute in any order. The coordinator publishes complete blocks in
sample order. Native adapters must preserve MoonRay sequence arguments and assign
stable contribution branch IDs before dispatch; neither is implemented here.
"""
from dataclasses import dataclass
import math
import struct


def uint(value, name, positive=False):
    if type(value) is not int or value < int(positive):
        raise ValueError("Invalid " + name)
    return value


def f32(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("Expected finite numeric value")
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error):
        raise ValueError("Float32 overflow") from None
    if not math.isfinite(result):
        raise ValueError("Nonfinite float32 value")
    return result


@dataclass(frozen=True, order=True)
class Sample:
    seed: int
    frame: int
    pixel: int
    index: int

    def __post_init__(self):
        for name in ("seed", "pixel", "index"):
            uint(getattr(self, name), name)
        if type(self.frame) is not int:
            raise ValueError("Frame key must be an integer")


@dataclass(frozen=True)
class Plan:
    seed: int
    frame: int
    pixels: int
    spp: int
    block_size: int

    def __post_init__(self):
        Sample(self.seed, self.frame, 0, 0)
        for name in ("pixels", "spp", "block_size"):
            uint(getattr(self, name), name, True)

    @property
    def blocks(self):
        return (self.pixels * self.spp + self.block_size - 1) // self.block_size

    def samples(self, block):
        uint(block, "block")
        if block >= self.blocks:
            raise ValueError("Block outside plan")
        start = block * self.block_size
        stop = min(start + self.block_size, self.pixels * self.spp)
        return tuple(Sample(self.seed, self.frame, i % self.pixels, i // self.pixels)
                     for i in range(start, stop))


@dataclass(frozen=True)
class Contribution:
    # Stable path/branch/event identity; never arrival order or a color value.
    identity: tuple
    rgb: tuple


@dataclass(frozen=True)
class Result:
    sample: Sample
    contributions: tuple
    # RGB contributions and alpha are already weighted; weight is counted ONCE.
    alpha: float = 1.0
    weight: float = 1.0


@dataclass(frozen=True)
class Lease:
    attempt: object
    block: int
    serial: int
    device: str
    samples: tuple


class Scheduler:
    """Protocol model with bounded issued + completed-but-unpublished blocks.

    One scheduler per gate attempt, all calls on its coordinator thread. 'cpu' and
    'gpu' are simulated eligible workers, not capability approval. Faster workers
    can claim more fixed blocks; block size never follows completion speed.
    """
    def __init__(self, gate, plan, window=4, max_contributions=4096):
        if gate.active is None:
            raise ValueError("An active attempt is required")
        self.gate, self.attempt, self.plan = gate, gate.active, plan
        self.window = uint(window, "window", True)
        self.max_contributions = uint(max_contributions, "contribution cap", True)
        self.cursor = 0
        self.serial = 0
        self.leases = {}
        self.ready = {}
        self.film = [[0.0] * 5 for _ in range(plan.pixels)]
        self.counts = [0] * plan.pixels

    @property
    def active(self):
        return self.gate.active == self.attempt

    @property
    def finished(self):
        return self.active and self.cursor == self.plan.blocks

    def claim(self, device):
        if device not in ("cpu", "gpu"):
            raise ValueError("Unknown worker")
        if not self.active:
            return None
        for block in range(self.cursor, min(self.plan.blocks, self.cursor + self.window)):
            if block not in self.leases and block not in self.ready:
                self.serial += 1
                lease = Lease(self.attempt, block, self.serial, device, self.plan.samples(block))
                self.leases[block] = lease
                return lease
        return None

    def owns(self, lease):
        return (self.active and isinstance(lease, Lease)
                and self.leases.get(lease.block) == lease)

    def retry(self, lease):
        """Revoke old ownership before redispatch; sampling addresses stay fixed."""
        if not self.owns(lease):
            return False
        del self.leases[lease.block]
        return True

    def _sample_value(self, result):
        if not isinstance(result.contributions, tuple) or len(result.contributions) > self.max_contributions:
            raise ValueError("Contribution cap exceeded or mutable payload")
        seen, ordered = set(), []
        for contribution in result.contributions:
            key = contribution.identity
            if not isinstance(key, tuple) or not key:
                raise ValueError("Stable contribution identity required")
            for part in key:
                uint(part, "branch identity")
            if key in seen:
                raise ValueError("Duplicate contribution identity")
            seen.add(key)
            if not isinstance(contribution.rgb, tuple) or len(contribution.rgb) != 3:
                raise ValueError("Expected RGB")
            ordered.append((key, tuple(f32(v) for v in contribution.rgb)))
        total = [0.0] * 3
        for _, rgb in sorted(ordered):
            total = [f32(a + b) for a, b in zip(total, rgb)]
        alpha, weight = f32(result.alpha), f32(result.weight)
        if weight <= 0:
            raise ValueError("Positive sample weight required")
        return (*total, alpha, weight)

    def complete(self, lease, results):
        if not self.owns(lease):
            return False
        if not isinstance(results, tuple) or len(results) != len(lease.samples):
            raise ValueError("Complete immutable sample block required")
        mapped = {}
        for result in results:
            if not isinstance(result, Result) or result.sample in mapped:
                raise ValueError("Invalid or duplicate sample")
            mapped[result.sample] = self._sample_value(result)
        if set(mapped) != set(lease.samples):
            raise ValueError("Result samples do not match lease")
        # Validate and stage all consecutive publication BEFORE mutating state.
        pending = dict(self.ready)
        pending[lease.block] = tuple(mapped[s] for s in lease.samples)
        cursor, staged, counts = self.cursor, {}, {}
        while cursor in pending:
            for sample, value in zip(self.plan.samples(cursor), pending[cursor]):
                previous = staged.get(sample.pixel, self.film[sample.pixel])
                staged[sample.pixel] = [f32(a + b) for a, b in zip(previous, value)]
                counts[sample.pixel] = counts.get(sample.pixel, self.counts[sample.pixel]) + 1
            cursor += 1
        del self.leases[lease.block]
        self.ready[lease.block] = pending[lease.block]
        for block in range(self.cursor, cursor):
            del self.ready[block]
        for pixel, values in staged.items():
            self.film[pixel], self.counts[pixel] = values, counts[pixel]
        self.cursor = cursor
        return True

    def image(self):
        if not self.active:
            raise ValueError("Attempt is stale")
        return tuple(tuple(f32(v / row[4]) for v in row[:4]) if row[4] else None
                     for row in self.film)
