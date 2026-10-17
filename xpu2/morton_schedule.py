"""Morton work ordering and convergence barriers for the XPU2 protocol model.

This reuses the deterministic accumulator, not MoonRay's native adaptive estimator.
The native adapter must supply convergence decisions at complete checkpoints. CPU
and GPU labels describe eligible simulated workers, not full GPU path support.
"""
from bisect import bisect_right
from dataclasses import dataclass

from xpu2.scheduling import Sample, Scheduler, uint


def morton(x, y):
    uint(x, 'tile x')
    uint(y, 'tile y')
    code, bit = 0, 0
    while x or y:
        code |= (x & 1) << (2 * bit)
        code |= (y & 1) << (2 * bit + 1)
        x >>= 1
        y >>= 1
        bit += 1
    return code


class MortonPlan:
    """Fixed sample addresses; partial edge tiles and sparse active pixel masks."""
    def __init__(self, seed, frame, width, height, start, stop, active=None,
                 tile_size=8, block_size=256):
        Sample(seed, frame, 0, 0)
        for name, value in (('width', width), ('height', height), ('tile_size', tile_size),
                            ('block_size', block_size), ('stop', stop)):
            uint(value, name, True)
        uint(start, 'start')
        if stop <= start:
            raise ValueError('Empty sample interval')
        self.seed, self.frame = seed, frame
        self.pixels, self.spp, self.start = width * height, stop, start
        self.block_size = block_size
        active = frozenset(range(self.pixels)) if active is None else frozenset(active)
        for pixel in active:
            uint(pixel, 'active pixel')
            if pixel >= self.pixels:
                raise ValueError('Pixel outside film')
        tiles = {}
        for pixel in sorted(active):
            x, y = pixel % width, pixel // width
            tiles.setdefault((x // tile_size, y // tile_size), []).append(pixel)
        self.tiles = tuple(tuple(tiles[key]) for key in sorted(tiles, key=lambda xy: morton(*xy)))
        self.ends = []
        total = 0
        for pixels in self.tiles:
            total += (len(pixels) * (stop - start) + block_size - 1) // block_size
            self.ends.append(total)
        self.blocks = total

    def samples(self, block):
        uint(block, 'block')
        if block >= self.blocks:
            raise ValueError('Block outside plan')
        tile = bisect_right(self.ends, block)
        pixels = self.tiles[tile]
        local = block - (self.ends[tile - 1] if tile else 0)
        first = local * self.block_size
        last = min(first + self.block_size, len(pixels) * (self.spp - self.start))
        return tuple(Sample(self.seed, self.frame, pixels[i % len(pixels)], self.start + i // len(pixels))
                     for i in range(first, last))


@dataclass(frozen=True)
class Checkpoint:
    attempt: object
    samples: int
    active_pixels: frozenset
    counts: tuple
    # Immutable weighted sums, not averages of device images.
    film: tuple


class AdaptiveMortonSchedule:
    """Coordinator-only model: completion timing cannot trigger early convergence.

    advance() consumes a decision from the external estimator. Missing-resource
    jobs must remain outstanding; their placeholder values must never be completed.
    Retries retain addresses and revoke prior ownership through Scheduler.
    """
    def __init__(self, gate, seed, frame, width, height, milestones, *,
                 tile_size=8, block_size=256, window=4):
        milestones = tuple(milestones)
        if not milestones:
            raise ValueError('At least one sample milestone is required')
        previous = 0
        for value in milestones:
            uint(value, 'milestone', True)
            if value <= previous:
                raise ValueError('Milestones must increase strictly')
            previous = value
        self.gate = gate
        self.seed, self.frame, self.width, self.height = seed, frame, width, height
        self.milestones = milestones
        self.tile_size, self.block_size, self.window = tile_size, block_size, window
        self.phase = 0
        self._checkpoint = None
        self.done = False
        self.queue = Scheduler(gate, MortonPlan(seed, frame, width, height, 0, milestones[0],
                                               tile_size=tile_size, block_size=block_size), window=window)
        self.active_pixels = frozenset(range(self.queue.plan.pixels))

    @property
    def finished(self):
        return self.queue.active and self.done

    def claim(self, device):
        return None if self.done else self.queue.claim(device)

    def retry(self, lease):
        return self.queue.retry(lease)

    def complete(self, lease, results):
        return self.queue.complete(lease, results)

    def checkpoint(self):
        if self.done or not self.queue.finished:
            return None
        if self._checkpoint is None:
            self._checkpoint = Checkpoint(self.queue.attempt, self.milestones[self.phase], self.active_pixels,
                tuple(self.queue.counts), tuple(tuple(row) for row in self.queue.film))
        return self._checkpoint

    def advance(self, checkpoint, converged):
        """Apply native estimator's pixel decisions only to this complete milestone."""
        if checkpoint is None or checkpoint is not self.checkpoint() or not self.queue.active:
            return False
        converged = frozenset(converged)
        for pixel in converged:
            uint(pixel, 'converged pixel')
        if not converged <= self.active_pixels:
            raise ValueError('Convergence decision includes inactive/unknown pixels')
        remaining = self.active_pixels - converged
        if not remaining or self.phase + 1 == len(self.milestones):
            self.done = True  # Final milestone is the cap, regardless of noise.
            self._checkpoint = None
            self.active_pixels = remaining
            return True
        plan = MortonPlan(self.seed, self.frame, self.width, self.height,
                          self.milestones[self.phase], self.milestones[self.phase + 1], remaining,
                          self.tile_size, self.block_size)
        following = Scheduler(self.gate, plan, window=self.window)
        # New queue has a new lease namespace; sample ranges never overlap phases.
        following.film = self.queue.film
        following.counts = self.queue.counts
        self.queue = following
        self.active_pixels = remaining
        self.phase += 1
        self._checkpoint = None
        return True

    def image(self):
        return self.queue.image()
