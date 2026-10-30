"""Executable XPU2 protocol specification, NOT a rendering implementation.

Single-threaded reference model. It does not prove CUDA visibility, concurrent
memory safety, MoonRay estimator equivalence, or speed. Records deliberately
remain allocated for auditing; the total record cap bounds a model run.
"""
from collections import deque
from dataclasses import dataclass, field
import math

MAX_U64 = (1 << 64) - 1


def uint(value, name, maximum=MAX_U64):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("Invalid " + name)
    return value


def device(value):
    if value not in ("cpu", "gpu"):
        raise ValueError("Invalid device")
    return value


@dataclass(frozen=True)
class Epoch:
    session: int
    scene: int
    camera: int
    settings: int

    def __post_init__(self):
        for name in ("session", "scene", "camera", "settings"):
            uint(getattr(self, name), name)


@dataclass(frozen=True)
class Sample:
    pixel: int
    index: int

    def __post_init__(self):
        uint(self.pixel, "pixel")
        uint(self.index, "sample index")


@dataclass
class _Record:
    epoch: Epoch
    sample: Sample
    owner: str
    state: str = "unstarted"
    pending: set = field(default_factory=set)
    rgba: tuple = (0.0, 0.0, 0.0, 0.0)
    started: bool = False
    serial: int = 0


@dataclass(frozen=True)
class Packet:
    key: tuple
    sender: str
    receiver: str
    serial: int
    resume_state: str


class Ledger:
    """Coordinator-owned model of exclusive work ownership and sample trees."""

    def __init__(self, epoch, max_records=4096, mailbox_capacity=16, max_leaves=64):
        if not isinstance(epoch, Epoch):
            raise ValueError("Invalid epoch")
        for name, value in (("max_records", max_records),
                            ("mailbox_capacity", mailbox_capacity),
                            ("max_leaves", max_leaves)):
            if uint(value, name) == 0:
                raise ValueError("Empty capacity")
        self.epoch = epoch
        self.max_records = max_records
        self.mailbox_capacity = mailbox_capacity
        self.max_leaves = max_leaves
        self.records = {}
        self.mailbox = deque()
        self.film = {}
        self.counts = {}
        self.accept_starts = True
        self._seen_epochs = {epoch}

    def issue(self, sample, owner):
        device(owner)
        if not isinstance(sample, Sample):
            raise ValueError("Invalid sample")
        key = (self.epoch, sample)
        if key in self.records:
            raise ValueError("Duplicate sample reservation")
        if len(self.records) >= self.max_records:
            return None
        self.records[key] = _Record(self.epoch, sample, owner)
        return key

    def _owned(self, key, owner, states):
        device(owner)
        rec = self.records[key]
        if rec.epoch != self.epoch:
            return None
        if rec.owner != owner or rec.state not in states:
            raise ValueError("Work is not owned in the required state")
        return rec

    def start(self, key, owner):
        rec = self._owned(key, owner, ("unstarted",))
        if rec is None or not self.accept_starts:
            return False
        rec.started = True
        rec.state = "active"
        rec.pending.add(())
        return True

    def cutoff(self):
        self.accept_starts = False

    def next_frame(self):
        # Same epoch: late samples and parked paths remain valid.
        self.accept_starts = True

    def cancel_unstarted(self, key, owner):
        rec = self._owned(key, owner, ("unstarted",))
        if rec is None:
            return False
        rec.state = "cancelled"
        return True

    def transfer(self, key, sender, receiver, migration=False):
        """Reserve a ring slot BEFORE surrendering ownership (MBX-04/06)."""
        device(receiver)
        if sender == receiver:
            raise ValueError("Cross-device transfer requires different devices")
        states = ("active", "parked") if migration else ("unstarted",)
        rec = self._owned(key, sender, states)
        if rec is None or len(self.mailbox) == self.mailbox_capacity:
            return None
        packet = Packet(key, sender, receiver, rec.serial + 1, rec.state)
        # These transitions are atomic only in this sequential specification.
        # The native adapter needs its own tested publication protocol.
        self.mailbox.append(packet)
        rec.serial = packet.serial
        rec.owner = "mailbox"
        rec.state = "transit"
        return packet

    def receive(self):
        if not self.mailbox:
            return None
        packet = self.mailbox.popleft()
        rec = self.records[packet.key]
        if rec.epoch != self.epoch:
            return None
        if (rec.owner, rec.state, rec.serial) != ("mailbox", "transit", packet.serial):
            return None  # Duplicate/replayed grant has no effect.
        rec.owner = packet.receiver
        rec.state = packet.resume_state
        return packet

    def stage(self, key, owner, branch=(), rgba=(0.0, 0.0, 0.0, 0.0),
              children=0, texture_miss=False):
        """Commit one sample-tree branch transaction or park with zero effects.

        Random-number state is not implemented here. A real adapter must restore
        it, medium/LPE state, rays and AOV transactions together on a miss.
        """
        rec = self._owned(key, owner, ("active", "parked"))
        if rec is None:
            return False
        if type(texture_miss) is not bool:
            raise ValueError("Invalid miss flag")
        if branch not in rec.pending:
            raise ValueError("Duplicate or unknown branch")
        uint(children, "child count", self.max_leaves)
        if len(rec.pending) - 1 + children > self.max_leaves:
            return False  # Backpressure retains the unfinished branch.
        if len(rgba) != 4 or any(type(x) not in (int, float) or
                                 not math.isfinite(x) for x in rgba):
            raise ValueError("Invalid contribution")
        combined = tuple(a+b for a, b in zip(rec.rgba, rgba))
        if not all(math.isfinite(x) for x in combined):
            raise ValueError("Contribution overflow")
        leaves = (rec.pending - {branch}) | {branch+(i,) for i in range(children)}
        if texture_miss:
            rec.state = "parked"
            return False
        # Validate the terminal film write before mutating any sample state.
        new_film = None
        if not leaves:
            current = self.film.get(rec.sample.pixel, (0.0,)*4)
            new_film = tuple(a+b for a, b in zip(current, combined))
            if not all(math.isfinite(x) for x in new_film):
                raise ValueError("Film overflow")
        rec.rgba = combined
        rec.pending = leaves
        rec.state = "active" if leaves else "done"
        if new_film is not None:
            self.film[rec.sample.pixel] = new_film
            self.counts[rec.sample.pixel] = self.counts.get(rec.sample.pixel, 0)+1
        return True

    def invalidate(self, epoch):
        """Invalidate a whole epoch. No individual slow sample is discarded."""
        if not isinstance(epoch, Epoch) or epoch in self._seen_epochs:
            raise ValueError("Epoch identity must never be reused")
        if epoch.session == self.epoch.session:
            before = (self.epoch.scene, self.epoch.camera, self.epoch.settings)
            after = (epoch.scene, epoch.camera, epoch.settings)
            if any(a < b for a, b in zip(after, before)):
                raise ValueError("Epoch counters cannot go backwards")
        for rec in self.records.values():
            if rec.epoch == self.epoch:
                rec.state = "invalidated"
        self._seen_epochs.add(epoch)
        self.epoch = epoch
        self.film.clear()
        self.counts.clear()
        self.accept_starts = True
        # Old packets remain pending retirement: receiving them cannot publish.

    def quiescent(self):
        return not self.mailbox and not any(
            r.state in ("active", "parked", "transit") for r in self.records.values())

    def audit(self):
        current = [r for r in self.records.values() if r.epoch == self.epoch]
        started = sum(r.started for r in current)
        done = sum(r.state == "done" for r in current)
        outstanding = sum(r.started and r.state in ("active", "parked", "transit")
                          for r in current)
        if started != done + outstanding or sum(self.counts.values()) != done:
            raise AssertionError("Sample conservation violated")
        if self.quiescent() and started != done:
            raise AssertionError("Incomplete sample at quiescence")
        return {"started":started, "completed":done, "outstanding":outstanding}


@dataclass(frozen=True)
class Cell:
    id: int
    x: int
    y: int
    width: int
    height: int
    owner: str


def checker_grid(width=1920, height=1080, cell_size=64):
    if cell_size not in (32,64,128):
        raise ValueError("Unsupported cell size")
    if not uint(width, "width") or not uint(height, "height"):
        raise ValueError("Empty image")
    cols=(width+cell_size-1)//cell_size
    rows=(height+cell_size-1)//cell_size
    if cols*rows > 65536:
        raise ValueError("Cell ID exceeds proposed wire format")
    return tuple(Cell(y*cols+x,x*cell_size,y*cell_size,
                      min(cell_size,width-x*cell_size),
                      min(cell_size,height-y*cell_size),
                      "gpu" if (x+y)%2==0 else "cpu")
                 for y in range(rows) for x in range(cols))
