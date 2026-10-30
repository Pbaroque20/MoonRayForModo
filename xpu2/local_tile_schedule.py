"""Bounded-checkpoint scheduling model; no native renderer or GPU execution.

Both policies use the same capability-filtered queues and exclusive leases.
Neighbor-first adds per-tile queues with a shared fallback, not a scene scan.
The Python lock models ownership only; its timing is not native atomic cost.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
import math


@dataclass(frozen=True)
class Batch:
    key: tuple  # Stable logical sample/contribution identity, never append order.
    tile: tuple
    eligible: frozenset

    def __post_init__(self):
        if type(self.key) is not tuple or not self.key or any(type(x) is not int or x < 0 for x in self.key):
            raise ValueError('Invalid stable batch key')
        if type(self.tile) is not tuple or len(self.tile) != 2 or any(type(x) is not int or x < 0 for x in self.tile):
            raise ValueError('Invalid tile')
        if not isinstance(self.eligible, frozenset) or not self.eligible <= {'cpu', 'gpu'}:
            raise ValueError('Invalid eligibility')


@dataclass(frozen=True)
class Lease:
    batch: Batch
    worker: str
    device: str
    attempt: int


class TileQueues:
    def __init__(self, batches, policy='shared', *, prefer_cpu_only=False):
        if type(prefer_cpu_only) is not bool:
            raise ValueError('Invalid CPU-only priority')
        if policy not in ('shared', 'neighbor'):
            raise ValueError('Unknown policy')
        batches = tuple(batches)
        if any(not isinstance(b, Batch) for b in batches):
            raise ValueError('Expected immutable batches')
        if len({b.key for b in batches}) != len(batches):
            raise ValueError('Duplicate batch key')
        self.policy = policy
        self.prefer_cpu_only = prefer_cpu_only
        self.cpu_only = deque()
        self.batches = {b.key: b for b in batches}
        self.state = {b.key: 'pending' for b in batches}
        self.shared = {d: deque() for d in ('cpu', 'gpu')}
        self.tiles = {d: defaultdict(deque) for d in ('cpu', 'gpu')}
        self.last = {}
        self.leases = {}
        self.results = {}
        self.sequence = 0
        self.closed = False
        self.lock = Lock()
        self.candidate_checks = self.tile_probes = self.local_claims = 0
        for batch in batches:
            self._enqueue(batch)

    def _enqueue(self, batch):
        if self.prefer_cpu_only and batch.eligible == frozenset({'cpu'}):
            self.cpu_only.append(batch.key)
        for device in batch.eligible:
            self.shared[device].append(batch.key)
            if self.policy == 'neighbor':
                self.tiles[device][batch.tile].append(batch.key)

    def _take(self, queue):
        while queue:
            key = queue.popleft()
            self.candidate_checks += 1
            if self.state[key] == 'pending':
                return key
        return None

    def claim(self, worker, device):
        if not isinstance(worker, str) or not worker or device not in self.shared:
            raise ValueError('Invalid worker/device')
        with self.lock:
            if self.closed:
                return None
            key = self._take(self.cpu_only) if device == 'cpu' and self.prefer_cpu_only else None
            if key is None and self.policy == 'neighbor' and worker in self.last:
                x, y = self.last[worker]
                # Fixed, bounded neighborhood; sparse/empty tiles need no traversal.
                for dx, dy in ((0,0),(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1)):
                    self.tile_probes += 1
                    key = self._take(self.tiles[device].get((x+dx,y+dy), ()))
                    if key is not None:
                        self.local_claims += 1
                        break
            if key is None:
                key = self._take(self.shared[device])
            if key is None:
                return None
            self.sequence += 1
            lease = Lease(self.batches[key], worker, device, self.sequence)
            self.state[key] = 'leased'
            self.leases[key] = lease
            self.last[worker] = lease.batch.tile
            return lease

    def complete(self, lease, payload):
        with self.lock:
            if self.closed or self.leases.get(lease.batch.key) is not lease:
                return False
            payload = tuple(payload)
            if len(payload) != 3 or any(type(x) not in (float, int) or not math.isfinite(x) for x in payload):
                raise ValueError('Invalid numerical payload')
            self.results[lease.batch.key] = payload
            del self.leases[lease.batch.key]
            self.state[lease.batch.key] = 'done'
            return True

    def retry(self, lease):
        with self.lock:
            if self.closed or self.leases.get(lease.batch.key) is not lease:
                return False
            del self.leases[lease.batch.key]
            self.state[lease.batch.key] = 'pending'
            self._enqueue(lease.batch)
            return True

    def cancel(self):
        with self.lock:
            self.closed = True
            self.leases.clear()
            # This model has no device buffers or native resources to drain.

    def checkpoint(self):
        with self.lock:
            if self.closed or len(self.results) != len(self.batches):
                return None
            # Fixed key order models publication; payload generation is independent.
            return tuple((key, self.results[key]) for key in sorted(self.results))
