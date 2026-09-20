"""
Counts unique tracks that transition from the "before" side to the "passed"
side of a CrossingLine. Each track is counted at most once per cycle, which
is what lets us match "how many left the queue" against "how many arrived at
the far end" for the corridor-clear check.
"""
from typing import Dict, Set, List


class CrossingCounter:
    def __init__(self):
        self._last_side: Dict[int, bool] = {}
        self._counted: Set[int] = set()
        self.passed_count: int = 0
        self.passed_ids: List[int] = []

    def update(self, track_id: int, has_passed: bool):
        prev = self._last_side.get(track_id)
        if has_passed and prev is False and track_id not in self._counted:
            self.passed_count += 1
            self.passed_ids.append(track_id)
            self._counted.add(track_id)
        self._last_side[track_id] = has_passed

    def reset_cycle(self):
        """Call at the start of a new green phase so counts reflect only this phase."""
        self.passed_count = 0
        self.passed_ids = []
        self._counted = set()
        # _last_side is intentionally kept so a vehicle mid-crossing at the
        # reset boundary isn't double-counted right after reset.
