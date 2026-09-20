# Traffic CV prototype — single-pole vision module

Status: core building blocks written and self-tested. NOT yet tested on real
vehicle footage — no video was available (see "Test video" below).

## What's here

- `src/detector_tracker.py` — YOLOv8n + ByteTrack wrapper, gives each vehicle
  a persistent track ID across frames. Sanity-checked against a real photo
  (bus + people, bundled with ultralytics): detected correctly at 0.87+ conf.
- `src/zones.py` — polygon "queue zone" / "through zone" + a crossing line,
  all in normalized (0-1) coordinates so they survive a resolution change.
  **Placeholder coordinates in config/config.yaml — must be recalibrated
  against a real frame from the actual pole camera.**
- `src/queue_counter.py` — counts vehicles in the queue zone that have been
  near-stationary for a window (not just passing through).
- `src/crossing_counter.py` — counts unique vehicles crossing the line in the
  through zone exactly once (this is the "has this car cleared the corridor"
  signal).
- `src/state_machine.py` — the decision logic (which side gets green, for how
  long). Pure logic, no camera code, so it's unit-testable on its own. Run
  `python3 src/test_state_machine.py` — 4 scenarios, all pass:
  bigger-queue-wins, min-green floor holds, max-green fallback fires, and the
  fixed-timer fallback forces a decision when vision never confirms the
  corridor clear.
- `src/harness.py` — runs the full pipeline over a video file: detection,
  tracking, both counters, draws an annotated overlay (boxes, zones, crossing
  line, live counts), writes an annotated output video + a CSV log.
- `src/make_synthetic_video.py` — generates a synthetic clip (colored
  rectangles, not real vehicles) used ONLY to prove the video I/O / overlay /
  logging plumbing runs end-to-end without errors. It does NOT validate
  detection accuracy — YOLO correctly reports 0 detections on it, as it
  should for drawn rectangles.

## Test video — blocked, need one from you

I could not download stock footage to test against — pexels.com (and likely
other generic video hosts) are blocked by this session's network policy at
the proxy level, not something to route around. So the harness has been
validated for plumbing (synthetic clip, runs clean at ~14 fps on 2 CPU cores,
no GPU, in this sandbox) but NOT yet for real detection accuracy.

To actually test it: upload a video (or record a short phone clip) showing
either a real queue of stopped vehicles, or two-way traffic where one
direction is moving and the other is backed up — as close to the real
deployment framing as you can get. Then:

```
python3 src/harness.py --video your_video.mp4 --config config/config.yaml \
    --out data/output/annotated.mp4 --log logs/run.csv
```

## Setup

```
pip install -r requirements.txt --break-system-packages
```

(`yolov8n.pt` auto-downloads on first run, ~6MB.)

## Known placeholders that need real values before this means anything on site

- `zones.queue_zone` / `through_zone` / `crossing_line` in config.yaml — need
  a real frame from the real camera position to place correctly.
- `state_machine.red_wait_fallback_sec` (currently 90s) — must be derived
  from the actual corridor length and a conservative minimum vehicle speed,
  not left as a guess.
- Runs on CPU only in this sandbox (no GPU). 14 fps single-stream on a
  server Xeon core — a Raspberry Pi will likely be slower still. Worth
  benchmarking on real Pi hardware (or considering a Coral/Hailo accelerator,
  or a Jetson instead of a Pi) once we're past the pure-software test phase.
