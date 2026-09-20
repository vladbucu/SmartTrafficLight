"""
Counts vehicles that are inside a queue zone AND have been near-stationary for
a configurable window — i.e. actually waiting, not just passing through the
zone. A car that merely transits the queue-zone polygon without stopping must
NOT be counted as "in the queue".
"""
import math
from collections import defaultdict, deque
from typing import Dict, Iterable


class QueueCounter:
    def __init__(
        self,
        stationary_window_sec: float = 2.5,
        stationary_max_disp_frac: float = 0.02,
        min_track_age_sec: float = 1.0,
    ):
        self.window_sec = stationary_window_sec
        self.max_disp_frac = stationary_max_disp_frac
        self.min_age_sec = min_track_age_sec
        self._history: Dict[int, deque] = defaultdict(deque)  # track_id -> deque[(t, cx, cy)]
        self._first_seen: Dict[int, float] = {}

    def update(self, track_id: int, centroid, t: float, in_zone: bool):
        if not in_zone:
            # Vehicle left the queue zone (or was never in it this frame) —
            # drop its history so stale state can't linger and mis-count later.
            self._history.pop(track_id, None)
            self._first_seen.pop(track_id, None)
            return
        if track_id not in self._first_seen:
            self._first_seen[track_id] = t
        hist = self._history[track_id]
        hist.append((t, centroid[0], centroid[1]))
        while hist and (t - hist[0][0]) > self.window_sec:
            hist.popleft()

    def is_stationary(self, track_id: int, t: float, frame_diag: float) -> bool:
        if track_id not in self._first_seen:
            return False
        if (t - self._first_seen[track_id]) < self.min_age_sec:
            return False
        hist = self._history.get(track_id)
        if not hist or len(hist) < 2:
            return False
        if (hist[-1][0] - hist[0][0]) < self.window_sec * 0.6:
            return False  # not enough history accumulated yet
        xs = [p[1] for p in hist]
        ys = [p[2] for p in hist]
        max_disp = max(math.hypot(x - xs[0], y - ys[0]) for x, y in zip(xs, ys))
        return (max_disp / frame_diag) < self.max_disp_frac

    def count(self, active_track_ids: Iterable[int], t: float, frame_diag: float) -> int:
        return sum(1 for tid in active_track_ids if self.is_stationary(tid, t, frame_diag))
