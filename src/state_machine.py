"""
Decision logic only — no camera/model code here on purpose, so it can be
unit-tested with synthetic inputs independent of the vision pipeline.

Design principles carried over from the requirements discussion:
- A vision-confirmed "corridor clear" can shorten the wait, but the state
  machine NEVER grants green faster than min_green_sec, and NEVER holds a
  green past max_green_sec (the "2 minutes per lane" fixed fallback).
- If vision never confirms the corridor clear, a fixed red_wait_fallback_sec
  timer forces it clear anyway rather than deadlocking forever — same
  fixed-timer safety-floor principle commercial portable traffic signals use.
  red_wait_fallback_sec MUST be derived from the real corridor length and a
  conservative minimum vehicle speed on site — the placeholder here is NOT a
  real safety value.
- This module assumes no hardware interlock exists (confirmed for this
  project), so it is the only thing preventing both sides being green at
  once. It only ever asserts ONE of GREEN_A / GREEN_B / RED_RED at a time by
  construction — but that only protects against a software logic bug, not a
  serial-link failure. A physical interlock relay on the output is still
  recommended separately from this code.
"""
import time
from enum import Enum
from typing import List, Tuple


class Light(Enum):
    RED_RED = "RED_RED"
    GREEN_A = "GREEN_A"
    GREEN_B = "GREEN_B"


class TrafficStateMachine:
    def __init__(
        self,
        min_green_sec: float = 15,
        max_green_sec: float = 120,
        red_wait_fallback_sec: float = 90,
        clock=time.monotonic,
    ):
        self.min_green_sec = min_green_sec
        self.max_green_sec = max_green_sec
        self.red_wait_fallback_sec = red_wait_fallback_sec
        self._clock = clock
        self.state = Light.RED_RED
        self._state_since = self._clock()
        self._last_green_side = None  # 'A' or 'B'
        self.log: List[Tuple[float, str, str, str]] = []

    def _elapsed(self) -> float:
        return self._clock() - self._state_since

    def _set_state(self, new_state: Light, reason: str):
        self.log.append((self._clock(), self.state.value, new_state.value, reason))
        self.state = new_state
        self._state_since = self._clock()

    def _pick_side(self, queue_a: int, queue_b: int) -> str:
        if queue_a > queue_b:
            return "A"
        if queue_b > queue_a:
            return "B"
        return "B" if self._last_green_side == "A" else "A"

    def step(self, queue_a: int, queue_b: int, corridor_clear: bool) -> Light:
        """
        Call periodically with current queue counts and whether vision has
        confirmed the corridor is clear of vehicles from the last green phase.
        Returns the current Light state.
        """
        elapsed = self._elapsed()

        if self.state == Light.RED_RED:
            if not corridor_clear:
                if elapsed >= self.red_wait_fallback_sec:
                    self.log.append(
                        (self._clock(), "RED_RED", "RED_RED",
                         "WARNING: forced clear via fixed fallback timer — vision never confirmed")
                    )
                else:
                    return self.state
            if queue_a == 0 and queue_b == 0:
                return self.state  # nothing waiting, stay RED_RED
            side = self._pick_side(queue_a, queue_b)
            if side == "A":
                self._set_state(Light.GREEN_A, f"selected A (qA={queue_a}, qB={queue_b})")
            else:
                self._set_state(Light.GREEN_B, f"selected B (qA={queue_a}, qB={queue_b})")
            self._last_green_side = side
            return self.state

        if self.state in (Light.GREEN_A, Light.GREEN_B):
            own_queue = queue_a if self.state == Light.GREEN_A else queue_b
            other_queue = queue_b if self.state == Light.GREEN_A else queue_a
            if elapsed >= self.max_green_sec:
                self._set_state(Light.RED_RED, "max_green fallback timer hit")
            elif elapsed >= self.min_green_sec and (own_queue == 0 or other_queue > own_queue):
                self._set_state(Light.RED_RED, f"min_green met, switching (own={own_queue}, other={other_queue})")
            return self.state

        return self.state
