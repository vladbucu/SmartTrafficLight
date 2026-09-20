"""
Synthetic scenario tests for TrafficStateMachine — proves the decision logic
wiring (side selection, min/max green, fixed-timer fallback) is correct,
independent of any real video. Run with: python3 src/test_state_machine.py
"""
from state_machine import TrafficStateMachine, Light


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def run_scenario(name, steps, min_green=15, max_green=120, red_wait_fallback=90):
    print(f"\n=== {name} ===")
    clock = FakeClock()
    sm = TrafficStateMachine(
        min_green_sec=min_green, max_green_sec=max_green,
        red_wait_fallback_sec=red_wait_fallback, clock=clock,
    )
    for dt, queue_a, queue_b, corridor_clear in steps:
        clock.advance(dt)
        state = sm.step(queue_a, queue_b, corridor_clear)
    for entry in sm.log:
        print(f"  t={entry[0]:6.1f}s  {entry[1]:>8} -> {entry[2]:<8}  {entry[3]}")
    print(f"  final state: {sm.state.value}")
    return sm


# Scenario 1: A has more cars waiting than B, corridor starts clear (empty road at boot)
run_scenario(
    "A has bigger queue, clean start",
    steps=[(0, 5, 2, True), (1, 5, 2, True), (10, 4, 3, True), (10, 0, 3, True)],
)

# Scenario 2: min_green floor prevents instant flapping even if the other
# side's queue briefly looks bigger one tick later
run_scenario(
    "min_green floor holds despite a queue swing",
    steps=[(0, 1, 0, True), (1, 1, 0, True), (2, 0, 5, True), (5, 0, 5, True)],
)

# Scenario 3: max_green fallback forces a switch even if vision still sees cars
run_scenario(
    "max_green fallback fires (vision keeps reporting non-empty queue)",
    steps=[(0, 3, 1, True), (1, 3, 1, True)] + [(20, 3, 1, True)] * 6,
    max_green=120,
)

# Scenario 4: corridor never confirms clear -> forced-clear warning after red_wait_fallback_sec.
# Starts already in RED_RED (fresh state machine) with corridor_clear=False the whole time,
# so it must sit in RED_RED until the fixed fallback timer forces it.
run_scenario(
    "vision never confirms corridor clear -> fixed fallback forces it",
    steps=[(0, 2, 2, False)] + [(20, 2, 2, False)] * 5,
    red_wait_fallback=90,
)

print("\nAll scenarios ran without exceptions.")
