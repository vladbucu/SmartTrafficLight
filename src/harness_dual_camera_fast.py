#!/usr/bin/env python3
"""
Fast harness for dual-camera construction zone analysis.
Same as harness_dual_camera.py but WITHOUT OCR (for quick testing).
"""
import argparse
import csv
import sys
from pathlib import Path
from typing import Optional, Tuple
import cv2
import numpy as np

from detector_tracker import VehicleDetectorTracker
from dual_camera_analyzer import DualCameraAnalyzer
from vehicle_database import VehicleDatabase
from config_loader import load_config


def draw_overlay_fast(
    frame: np.ndarray,
    detections,
    camera_id: int,
    cam_state,
    signal_decision: dict,
    fps: float = 30.0
) -> np.ndarray:
    """Draw lightweight overlay without OCR."""
    h, w = frame.shape[:2]

    # Camera label
    cv2.putText(frame, f"Camera {camera_id}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

    # Draw detections
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"ID:{det.track_id}", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # Statistics
    y_offset = 60
    stats = [
        f"Stationary: {cam_state.stationary_count}",
        f"Moving: {cam_state.moving_count}",
        f"Vehicles: {len(cam_state.vehicle_speeds)}",
    ]

    for i, stat in enumerate(stats):
        cv2.putText(frame, stat, (10, y_offset + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

    # Signal
    if signal_decision and signal_decision.get('green_lane') == camera_id:
        green_text = f"GREEN for {signal_decision['green_duration_sec']:.0f}s"
        cv2.putText(frame, green_text, (10, h - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)
    else:
        cv2.putText(frame, "RED", (10, h - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

    return frame


def process_video_fast(
    video_path: str,
    camera_id: int,
    detector: VehicleDetectorTracker,
    analyzer: DualCameraAnalyzer,
    config: dict,
    output_path: Optional[str] = None,
) -> Tuple[int, list]:
    """Process single video (fast mode, no OCR)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open {video_path}")
        return 0, []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"\nProcessing camera {camera_id}:")
    print(f"  Input: {video_path}")
    print(f"  Resolution: {width}x{height}, FPS: {fps:.1f}, Frames: {total_frames}")

    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    else:
        out = None

    frame_count = 0
    csv_rows = []
    time_elapsed = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        time_elapsed = frame_count / fps

        # Detect and track (no OCR)
        detections = detector.track_frame(frame, persist=True)

        # Create fake plate detections for analyzer (no OCR, so all ?????):
        from plate_detector import PlateDetection
        fake_plates = [
            PlateDetection(
                track_id=det.track_id,
                plate_text="?????",
                confidence=0.0,
                bbox=det.bbox,
                color=(100, 100, 100),
                frame_count=1
            )
            for det in detections
        ]

        # Update analyzer
        cam_state = analyzer.update_camera(camera_id, fake_plates, time_elapsed, fps)
        signal_decision = analyzer.get_signal_decision()

        # Draw overlay
        frame = draw_overlay_fast(frame, detections, camera_id, cam_state, signal_decision, fps)

        # Write output
        if out:
            out.write(frame)

        # Log
        csv_rows.append({
            'frame': frame_count,
            't_sec': time_elapsed,
            'camera_id': camera_id,
            'stationary_count': cam_state.stationary_count,
            'moving_count': cam_state.moving_count,
            'detections': len(detections),
            'green_lane': signal_decision.get('green_lane'),
            'green_duration': signal_decision.get('green_duration_sec'),
        })

        if frame_count % 100 == 0:
            print(f"  Frame {frame_count}/{total_frames}")

    cap.release()
    if out:
        out.release()
        print(f"  Output: {output_path}")

    return frame_count, csv_rows


def main():
    parser = argparse.ArgumentParser(description="Dual-camera analyzer (FAST mode, no OCR)")
    parser.add_argument("--video", required=True, help="Camera 0 input video")
    parser.add_argument("--video2", help="Camera 1 input video (optional)")
    parser.add_argument("--config", default="config/config.yaml", help="Config file")
    parser.add_argument("--out", help="Camera 0 output video")
    parser.add_argument("--out2", help="Camera 1 output video")
    parser.add_argument("--log", help="CSV output log")

    args = parser.parse_args()

    config = load_config(args.config)

    print("Initializing (FAST MODE - no OCR)...")
    detector = VehicleDetectorTracker(conf=0.4, device="cpu")
    analyzer = DualCameraAnalyzer(stationary_threshold_sec=3.0, max_moving_speed=2.0)

    all_csv_rows = []

    # Camera 0
    frames_0, rows_0 = process_video_fast(
        args.video, 0, detector, analyzer, config,
        output_path=args.out
    )
    all_csv_rows.extend(rows_0)

    # Camera 1 (optional)
    if args.video2:
        frames_1, rows_1 = process_video_fast(
            args.video2, 1, detector, analyzer, config,
            output_path=args.out2
        )
        all_csv_rows.extend(rows_1)

    # Write log
    if args.log and all_csv_rows:
        with open(args.log, 'w', newline='') as f:
            fieldnames = all_csv_rows[0].keys()
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_csv_rows)
        print(f"\nLog: {args.log}")

    print("\n✅ FAST mode analysis complete")


if __name__ == "__main__":
    main()
