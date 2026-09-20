"""
Enhanced state machine for construction zone traffic control.
Instead of "A vs B", uses "lane_0 vs lane_1" with queue depth awareness.

Decision rules:
1. Give green to the lane with larger queue
2. Hold green for: 3-5 seconds per waiting vehicle (adaptable)
3. Fallback: if queues equal, alternate based on last served
4. Safety: never exceed max_green_sec, never less than min_green_sec
"""
import time
from enum import Enum
from typing import List, Tuple


class Signal(Enum):
    RED_RED = "RED_RED"
    GREEN_0 = "GREEN_0"  # Lane 0 (camera 0)
    GREEN_1 = "GREEN_1"  # Lane 1 (camera 1)


class ConstructionZoneStateMachine:
    """
    Controls traffic signal for construction zone with two entry lanes.
    """

    def __init__(
        self,
        min_green_sec: float = 15,
        max_green_sec: float = 120,
        red_wait_fallback_sec: float = 90,
        clock=time.monotonic,
    ):
        """
        min_green_sec: minimum time to keep signal green once selected
        max_green_sec: maximum time before forced switch
        red_wait_fallback_sec: if RED_RED for this long with vehicles, force green
        """
        self.min_green_sec = min_green_sec
        self.max_green_sec = max_green_sec
        self.red_wait_fallback_sec = red_wait_fallback_sec
        self._clock = clock

        self.state = Signal.RED_RED
        self._state_since = self._clock()
        self._last_green_lane = None  # 0 or 1
        self.log: List[Tuple[float, str, str, str]] = []

    def _elapsed(self) -> float:
        return self._clock() - self._state_since

    def _set_state(self, new_state: Signal, reason: str):
        """Record state transition."""
        self.log.append((self._clock(), self.state.value, new_state.value, reason))
        self.state = new_state
        self._state_since = self._clock()

    def _pick_lane(self, queue_0: int, queue_1: int, moving_0: int, moving_1: int) -> int:
        """Select which lane should get green."""
        # Primary: larger queue
        if queue_0 > queue_1:
            return 0
        if queue_1 > queue_0:
            return 1

        # Secondary: more moving traffic (prevent deadlock)
        if moving_0 > moving_1:
            return 0
        if moving_1 > moving_0:
            return 1

        # Tertiary: alternate
        return 1 if self._last_green_lane == 0 else 0

    def step(
        self,
        queue_0: int,
        queue_1: int,
        moving_0: int = 0,
        moving_1: int = 0,
    ) -> Signal:
        """
        Call once per frame with current queue counts.
        Returns current signal state.
        """
        elapsed = self._elapsed()
        total_queue = queue_0 + queue_1

        if self.state == Signal.RED_RED:
            # Check if we've been red too long (safety fallback)
            if elapsed >= self.red_wait_fallback_sec and total_queue > 0:
                self.log.append(
                    (self._clock(), "RED_RED", "RED_RED",
                     "WARNING: forced clear via fallback timer — vision never confirmed")
                )

            # If anyone waiting, pick a lane
            if total_queue > 0:
                lane = self._pick_lane(queue_0, queue_1, moving_0, moving_1)
                if lane == 0:
                    self._set_state(Signal.GREEN_0, f"selected 0 (q0={queue_0}, q1={queue_1})")
                else:
                    self._set_state(Signal.GREEN_1, f"selected 1 (q0={queue_0}, q1={queue_1})")
                self._last_green_lane = lane

            return self.state

        # Handle GREEN state
        if self.state in (Signal.GREEN_0, Signal.GREEN_1):
            current_lane = 0 if self.state == Signal.GREEN_0 else 1
            own_queue = queue_0 if current_lane == 0 else queue_1
            other_queue = queue_1 if current_lane == 0 else queue_0

            # Check max_green timeout
            if elapsed >= self.max_green_sec:
                self._set_state(Signal.RED_RED, "max_green fallback timer hit")

            # Check if we can switch earlier (after min_green)
            elif elapsed >= self.min_green_sec:
                # Switch if: own queue empty OR other queue is bigger
                if own_queue == 0 or other_queue > own_queue:
                    self._set_state(Signal.RED_RED,
                                  f"min_green met, switching (own={own_queue}, other={other_queue})")

            return self.state

        return self.state

    def get_decision_info(
        self,
        queue_0: int,
        queue_1: int,
        moving_0: int = 0,
        moving_1: int = 0,
    ) -> dict:
        """Get detailed decision information for UI/logging."""
        lane = self._pick_lane(queue_0, queue_1, moving_0, moving_1)
        elapsed = self._elapsed()

        return {
            'current_state': self.state.value,
            'recommended_lane': lane,
            'queue_0': queue_0,
            'queue_1': queue_1,
            'moving_0': moving_0,
            'moving_1': moving_1,
            'elapsed_in_state': elapsed,
            'min_green_met': elapsed >= self.min_green_sec,
            'max_green_exceeded': elapsed >= self.max_green_sec,
        }


class QueueBasedSignalTiming:
    """
    Calculates green duration based on queue depth.
    Formula: duration = base_time + (queue_count * time_per_vehicle)
    """

    def __init__(
        self,
        base_green_sec: float = 15,
        time_per_vehicle_sec: float = 4.0,
        max_green_sec: float = 120,
    ):
        self.base_green_sec = base_green_sec
        self.time_per_vehicle_sec = time_per_vehicle_sec
        self.max_green_sec = max_green_sec

    def calculate(self, queue_count: int) -> float:
        """Calculate recommended green duration for a given queue."""
        if queue_count <= 0:
            return 0

        duration = self.base_green_sec + (queue_count * self.time_per_vehicle_sec)
        return min(duration, self.max_green_sec)
