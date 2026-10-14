#!/usr/bin/env python3
"""
Enhanced harness for dual-camera construction zone traffic analysis.
Detects vehicles, reads license plates, tracks queue depth per lane,
and recommends signal timing based on congestion.

Usage:
  python3 src/harness_dual_camera.py --video camera0.mp4 --video2 camera1.mp4 \
      --config config/config.yaml --out output_cam0.mp4 --out2 output_cam1.mp4
"""
import argparse
import csv
import sys
from pathlib import Path
from typing import Optional, Tuple
import cv2
import numpy as np

from detector_tracker import VehicleDetectorTracker, VEHICLE_CLASSES
from plate_detector import PlateOCRTracker
from dual_camera_analyzer import DualCameraAnalyzer
from vehicle_database import VehicleDatabase
from config_loader import load_config


def draw_overlay(
    frame: np.ndarray,
    plate_detections,
    camera_id: int,
    cam_state,
    signal_decision: dict,
    fps: float = 30.0
) -> np.ndarray:
    """Draw annotated overlay on frame: detections, plates, queue info, signal state."""
    h, w = frame.shape[:2]

    # Draw camera label
    cv2.putText(frame, f"Camera {camera_id}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

    # Draw detections
    for det in plate_detections:
        x1, y1, x2, y2 = det.bbox
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        # Color based on plate confidence
        color = (0, 255, 0) if det.confidence >= 0.5 else (0, 165, 255)

        # Draw bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Draw plate text
        plate_label = f"{det.plate_text} ({det.confidence:.2f})"
        cv2.putText(frame, plate_label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # Draw color indicator
        b, g, r = det.color
        cv2.rectangle(frame, (x2 - 30, y1), (x2, y1 + 20), (b, g, r), -1)

    # Draw statistics panel
    y_offset = 60
    stats = [
        f"Stationary: {cam_state.stationary_count}",
        f"Moving: {cam_state.moving_count}",
        f"Identified: {len(set(cam_state.identified_plates))}",
    ]

    for i, stat in enumerate(stats):
        cv2.putText(frame, stat, (10, y_offset + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

    # Draw signal recommendation if this is the chosen lane
    if signal_decision and signal_decision.get('green_lane') == camera_id:
        green_text = f"GREEN for {signal_decision['green_duration_sec']:.0f}s"
        cv2.putText(frame, green_text, (10, h - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)
        cv2.putText(frame, signal_decision['reasoning'], (10, h - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 0), 1)
    else:
        cv2.putText(frame, "RED", (10, h - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

    return frame


def process_video(
    video_path: str,
    camera_id: int,
    detector: VehicleDetectorTracker,
    plate_tracker: PlateOCRTracker,
    analyzer: DualCameraAnalyzer,
    vehicle_db: VehicleDatabase,
    config: dict,
    output_path: Optional[str] = None,
    log_path: Optional[str] = None,
) -> Tuple[int, list]:
    """
    Process a single video file.
    Returns: (frame_count, rows_for_csv)
    """
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

        # Detect and track
        detections = detector.track_frame(frame, persist=True)

        # Read plates with multi-frame validation
        plate_detections = plate_tracker.update(detections, frame)

        # Update analyzer
        cam_state = analyzer.update_camera(camera_id, plate_detections, time_elapsed, fps)
        signal_decision = analyzer.get_signal_decision()

        # Register sightings in database
        for det in plate_detections:
            if det.confidence >= 0.5 and det.plate_text != "?????":
                vehicle_db.register_sighting(
                    det.plate_text,
                    det.color,
                    camera_id,
                    event_type='entry'
                )

        # Draw overlay
        frame = draw_overlay(frame, plate_detections, camera_id, cam_state, signal_decision, fps)

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
            'identified_plates': len(set(cam_state.identified_plates)),
            'green_lane': signal_decision.get('green_lane'),
            'green_duration': signal_decision.get('green_duration_sec'),
        })

        if frame_count % 100 == 0:
            print(f"  Frame {frame_count}/{total_frames} ({100*frame_count/total_frames:.1f}%)")

    cap.release()
    if out:
        out.release()
        print(f"  Output: {output_path}")

    return frame_count, csv_rows


def main():
    parser = argparse.ArgumentParser(description="Dual-camera construction zone traffic analyzer")
    parser.add_argument("--video", required=True, help="Camera 0 input video")
    parser.add_argument("--video2", help="Camera 1 input video (optional)")
    parser.add_argument("--config", default="config/config.yaml", help="Config file")
    parser.add_argument("--out", help="Camera 0 output video")
    parser.add_argument("--out2", help="Camera 1 output video")
    parser.add_argument("--log", help="CSV output log")
    parser.add_argument("--db", default="data/vehicles.db", help="Vehicle database path")

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Initialize components
    print("Initializing...")
    detector = VehicleDetectorTracker(conf=0.4, device="cpu", classes=VEHICLE_CLASSES)
    plate_tracker = PlateOCRTracker(confidence_threshold=0.5, frame_skip=3)
    analyzer = DualCameraAnalyzer(stationary_threshold_sec=3.0, max_moving_speed=2.0)
    vehicle_db = VehicleDatabase(args.db)

    # Process videos
    all_csv_rows = []

    # Camera 0 (required)
    frames_0, rows_0 = process_video(
        args.video, 0, detector, plate_tracker, analyzer, vehicle_db, config,
        output_path=args.out, log_path=args.log
    )
    all_csv_rows.extend(rows_0)

    # Camera 1 (optional)
    if args.video2:
        frames_1, rows_1 = process_video(
            args.video2, 1, detector, plate_tracker, analyzer, vehicle_db, config,
            output_path=args.out2, log_path=None
        )
        all_csv_rows.extend(rows_1)

    # Write combined log
    if args.log and all_csv_rows:
        with open(args.log, 'w', newline='') as f:
            fieldnames = all_csv_rows[0].keys()
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_csv_rows)
        print(f"\nLog: {args.log}")

    # Print summary
    print("\n=== SUMMARY ===")
    summary = analyzer.get_summary()
    print(f"Camera 0: {summary['camera_0']['stationary']} waiting, "
          f"{summary['camera_0']['moving']} moving, "
          f"{summary['camera_0']['identified_plates']} identified vehicles")
    print(f"Camera 1: {summary['camera_1']['stationary']} waiting, "
          f"{summary['camera_1']['moving']} moving, "
          f"{summary['camera_1']['identified_plates']} identified vehicles")

    db_summary = vehicle_db.get_today_summary()
    print(f"\nDatabase: {db_summary['total_entries']} entries, "
          f"{db_summary['total_exits']} exits, "
          f"{db_summary['unique_vehicles']} unique vehicles")


if __name__ == "__main__":
    main()
