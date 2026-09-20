"""
Video test harness — runs detection + tracking + queue counting + crossing
counting over a video file, draws an annotated overlay, and writes a CSV log.

This validates the vision/counting building blocks against real footage. It
does NOT run the two-pole state machine (that needs two synced camera feeds,
which we don't have yet) — see simulate_state_machine.py for that.

Usage:
    python3 src/harness.py --video path/to/video.mp4 --config config/config.yaml \
        --out data/output/annotated.mp4 --log logs/run.csv
"""
import argparse
import csv
import math
import os
import shutil
import subprocess
import time

import cv2

from config_loader import load_config
from detector_tracker import VehicleDetectorTracker
from zones import Zone, CrossingLine
from queue_counter import QueueCounter
from crossing_counter import CrossingCounter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--config", default="config/config.yaml")
    ap.add_argument("--out", default="data/output/annotated.mp4")
    ap.add_argument("--log", default="logs/run.csv")
    ap.add_argument("--max_frames", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    cfg = load_config(args.config)

    det = VehicleDetectorTracker(
        weights=cfg["model"]["weights"],
        classes=cfg["model"]["classes"],
        conf=cfg["model"]["conf_threshold"],
        iou=cfg["model"]["iou_threshold"],
        device=cfg["model"]["device"],
        tracker=cfg["model"]["tracker"],
    )

    queue_zone = Zone(cfg["zones"]["queue_zone"], name="queue_zone")
    through_zone = Zone(cfg["zones"]["through_zone"], name="through_zone")
    cl_cfg = cfg["zones"]["crossing_line"]
    crossing_line = CrossingLine(cl_cfg["p1"], cl_cfg["p2"], cl_cfg["passed_side"])

    qc = QueueCounter(**cfg["queue_counter"])
    cc = CrossingCounter()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {args.video}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_diag = math.hypot(w, h)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.log)) or ".", exist_ok=True)

    # cv2.VideoWriter can fail to open (wrong/missing codec on this OS build)
    # WITHOUT raising an exception — writer.write() then silently no-ops for
    # every frame, so you'd end the run with a CSV log but no usable video.
    # Try a few (fourcc, container) combos until one actually opens.
    out_base, _ = os.path.splitext(args.out)
    candidates = [
        ("mp4v", args.out),
        ("avc1", args.out),
        ("XVID", out_base + ".avi"),
        ("MJPG", out_base + ".avi"),
    ]
    writer = None
    chosen_path = args.out
    for fourcc_str, path in candidates:
        fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
        w_try = cv2.VideoWriter(path, fourcc, fps, (w, h))
        if w_try.isOpened():
            writer = w_try
            chosen_path = path
            if (fourcc_str, path) != candidates[0]:
                print(f"NOTE: '{candidates[0][0]}' codec failed to open on this machine; "
                      f"fell back to '{fourcc_str}' -> {path}")
            break
        w_try.release()
    if writer is None:
        raise SystemExit(
            "Could not open ANY video writer (tried mp4v/avc1/.mp4 and XVID/MJPG/.avi). "
            "This usually means OpenCV's build on this machine is missing video codecs. "
            "Try: pip3 install --break-system-packages --force-reinstall opencv-python "
            "(the non-headless build bundles more codecs), then re-run."
        )
    args.out = chosen_path

    log_rows = []
    frame_idx = 0
    t0 = time.monotonic()
    max_queue_seen = 0
    max_passed_seen = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        if args.max_frames and frame_idx > args.max_frames:
            break

        t = frame_idx / fps  # video-time seconds, independent of wall-clock processing speed
        dets = det.track_frame(frame)

        active_ids_in_queue = []
        for d in dets:
            in_q = queue_zone.contains(d.centroid, w, h)
            qc.update(d.track_id, d.centroid, t, in_q)
            if in_q:
                active_ids_in_queue.append(d.track_id)

            in_through = through_zone.contains(d.centroid, w, h)
            if in_through:
                passed = crossing_line.has_passed(d.centroid, w, h)
                cc.update(d.track_id, passed)

        queue_count = qc.count(active_ids_in_queue, t, frame_diag)
        max_queue_seen = max(max_queue_seen, queue_count)
        max_passed_seen = max(max_passed_seen, cc.passed_count)

        # ---- draw overlay ----
        for d in dets:
            x1, y1, x2, y2 = map(int, d.bbox)
            stationary = qc.is_stationary(d.track_id, t, frame_diag)
            color = (0, 165, 255) if stationary else (0, 220, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"#{d.track_id} {d.cls_name}", (x1, max(0, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        cv2.polylines(frame, [queue_zone.to_pixel_polygon(w, h)], True, (255, 200, 0), 2)
        cv2.polylines(frame, [through_zone.to_pixel_polygon(w, h)], True, (0, 200, 255), 2)
        p1, p2 = crossing_line.to_pixel(w, h)
        cv2.line(frame, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), (0, 0, 255), 2)

        hud = f"queue={queue_count}  passed_this_cycle={cc.passed_count}  frame={frame_idx}"
        cv2.rectangle(frame, (0, 0), (w, 30), (0, 0, 0), -1)
        cv2.putText(frame, hud, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

        writer.write(frame)
        log_rows.append([frame_idx, round(t, 2), queue_count, cc.passed_count, len(dets)])

    cap.release()
    writer.release()

    if not os.path.exists(chosen_path) or os.path.getsize(chosen_path) == 0:
        print(f"WARNING: output video file is missing or empty: {chosen_path} "
              f"— something is still wrong with the video writer on this machine.")

    # OpenCV's video writer (mp4v/XVID/MJPG above) uses old codecs that QuickTime
    # Player (macOS) often refuses to open, even though the file is a valid,
    # playable video (VLC etc. handle it fine). Re-encode to real H.264 with
    # ffmpeg, if it's installed, so the output plays everywhere.
    final_path = chosen_path
    if shutil.which("ffmpeg"):
        h264_path = out_base + "_h264.mp4"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", chosen_path,
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                 h264_path],
                check=True,
            )
            final_path = h264_path
            print(f"Transcoded to H.264 for QuickTime/universal playback: {final_path}")
        except Exception as e:
            print(f"NOTE: ffmpeg transcode to H.264 failed ({e}); keeping {chosen_path} as-is "
                  f"— open it with VLC if QuickTime refuses it.")
    else:
        print(f"NOTE: ffmpeg not found on this machine, so {chosen_path} was left in an older "
              f"codec that QuickTime often refuses to play (VLC plays it fine). "
              f"Install ffmpeg (e.g. 'brew install ffmpeg') and re-run for a QuickTime-friendly file.")

    with open(args.log, "w", newline="") as f:
        w_ = csv.writer(f)
        w_.writerow(["frame", "t_sec", "queue_count", "passed_count_cumulative", "n_detections"])
        w_.writerows(log_rows)

    wall = time.monotonic() - t0
    print(f"Processed {frame_idx} frames in {wall:.1f}s ({frame_idx/max(wall,1e-6):.1f} fps)")
    print(f"Max queue count observed: {max_queue_seen}")
    print(f"Max passed count observed: {max_passed_seen}")
    print(f"Annotated video: {final_path}")
    print(f"Log CSV: {args.log}")


if __name__ == "__main__":
    main()
