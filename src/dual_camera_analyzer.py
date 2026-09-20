"""
Dual-camera traffic analysis for construction zone control.
Tracks two entry points separately:
- Camera 0: primary lane (where queue decision matters most)
- Camera 1: opposite lane (through traffic)

Each camera independently measures:
- Stationary vehicles (waiting in line)
- Moving vehicles (passing through)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import numpy as np


@dataclass
class CameraState:
    """Traffic state for a single camera."""
    camera_id: int
    stationary_count: int = 0  # vehicles parked > N seconds
    moving_count: int = 0  # vehicles currently in motion
    total_identified: int = 0  # vehicles with confirmed plates
    identified_plates: List[str] = field(default_factory=list)

    # Track individual vehicles
    vehicle_speeds: Dict[int, float] = field(default_factory=dict)  # track_id -> speed (pixels/sec)
    vehicle_dwell_time: Dict[int, float] = field(default_factory=dict)  # track_id -> seconds in frame
    vehicle_plates: Dict[int, str] = field(default_factory=dict)  # track_id -> plate


class DualCameraAnalyzer:
    """
    Analyzes traffic from two cameras simultaneously.
    Determines signal timing based on queue depth in each lane.
    """

    def __init__(
        self,
        stationary_threshold_sec: float = 3.0,
        max_moving_speed: float = 2.0,  # pixels per frame, adjust per resolution
    ):
        """
        stationary_threshold_sec: time vehicle must be still to count as "waiting"
        max_moving_speed: velocity threshold (pixels/frame) above which vehicle is moving
        """
        self.stationary_threshold_sec = stationary_threshold_sec
        self.max_moving_speed = max_moving_speed

        self.cameras: Dict[int, CameraState] = {
            0: CameraState(camera_id=0),
            1: CameraState(camera_id=1),
        }

        # Track vehicle positions for motion detection
        self.prev_centroids: Dict[int, Tuple[float, float]] = {}
        self.frame_times: Dict[int, float] = {}

    def update_camera(
        self,
        camera_id: int,
        plate_detections: List,  # PlateDetection objects
        frame_timestamp: float,
        fps: float = 30.0,
    ) -> CameraState:
        """
        Update state for a single camera.
        plate_detections: output from PlateOCRTracker
        frame_timestamp: absolute time (seconds since start)
        fps: playback speed (for motion calculation)
        """
        cam_state = self.cameras[camera_id]
        cam_state.stationary_count = 0
        cam_state.moving_count = 0
        cam_state.identified_plates = []

        time_per_frame = 1.0 / fps if fps > 0 else 0.033

        for det in plate_detections:
            track_id = det.track_id
            plate_text = det.plate_text
            bbox = det.bbox

            # Calculate centroid
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            centroid = (cx, cy)

            # Store plate if confirmed
            if det.confidence >= 0.5:  # reasonable confidence threshold
                cam_state.vehicle_plates[track_id] = plate_text
                if plate_text != "?????" and plate_text not in cam_state.identified_plates:
                    cam_state.identified_plates.append(plate_text)
                cam_state.total_identified += 1

            # Calculate motion
            prev_cent = self.prev_centroids.get(track_id)
            prev_time = self.frame_times.get(track_id, frame_timestamp)

            if prev_cent:
                dist = np.sqrt((centroid[0] - prev_cent[0])**2 + (centroid[1] - prev_cent[1])**2)
                time_diff = max(0.001, frame_timestamp - prev_time)
                speed = dist / time_diff  # pixels per second
                cam_state.vehicle_speeds[track_id] = speed
            else:
                cam_state.vehicle_speeds[track_id] = 0.0

            # Update dwell time
            dwell = cam_state.vehicle_dwell_time.get(track_id, 0.0)
            cam_state.vehicle_dwell_time[track_id] = dwell + time_per_frame

            # Classify as stationary or moving
            speed = cam_state.vehicle_speeds[track_id]
            dwell = cam_state.vehicle_dwell_time[track_id]

            if speed < self.max_moving_speed and dwell >= self.stationary_threshold_sec:
                cam_state.stationary_count += 1
            else:
                cam_state.moving_count += 1

            # Update position
            self.prev_centroids[track_id] = centroid
            self.frame_times[track_id] = frame_timestamp

        # Clean up old tracks
        for track_id in list(self.prev_centroids.keys()):
            if not any(d.track_id == track_id for d in plate_detections):
                del self.prev_centroids[track_id]
                if track_id in self.frame_times:
                    del self.frame_times[track_id]
                if track_id in cam_state.vehicle_speeds:
                    del cam_state.vehicle_speeds[track_id]
                if track_id in cam_state.vehicle_dwell_time:
                    del cam_state.vehicle_dwell_time[track_id]
                if track_id in cam_state.vehicle_plates:
                    del cam_state.vehicle_plates[track_id]

        return cam_state

    def get_signal_decision(self) -> Dict:
        """
        Decide which lane should get green light.

        Returns:
        {
            'green_lane': 0 or 1 or None,
            'green_duration_sec': recommended duration,
            'reasoning': explanation,
            'queue_0': stationary count in lane 0,
            'queue_1': stationary count in lane 1,
            'moving_0': moving count in lane 0,
            'moving_1': moving count in lane 1,
        }
        """
        queue_0 = self.cameras[0].stationary_count
        queue_1 = self.cameras[1].stationary_count
        moving_0 = self.cameras[0].moving_count
        moving_1 = self.cameras[1].moving_count

        total_queue = queue_0 + queue_1

        # No one waiting
        if total_queue == 0:
            return {
                'green_lane': None,
                'green_duration_sec': 0,
                'reasoning': 'no vehicles waiting',
                'queue_0': queue_0,
                'queue_1': queue_1,
                'moving_0': moving_0,
                'moving_1': moving_1,
            }

        # Decide based on queue depth
        if queue_0 > queue_1:
            green_lane = 0
            reasoning = f"lane 0 has larger queue ({queue_0} vs {queue_1})"
        elif queue_1 > queue_0:
            green_lane = 1
            reasoning = f"lane 1 has larger queue ({queue_1} vs {queue_0})"
        else:
            # Equal queues - alternate or prefer moving traffic
            if moving_0 > moving_1:
                green_lane = 0
                reasoning = f"equal queues, more through traffic in lane 0"
            else:
                green_lane = 1
                reasoning = f"equal queues, more through traffic in lane 1"

        # Calculate green duration: 3-5 seconds per waiting vehicle
        queue_in_green = queue_0 if green_lane == 0 else queue_1
        green_duration = min(120, max(15, queue_in_green * 4))  # 15-120 sec

        return {
            'green_lane': green_lane,
            'green_duration_sec': green_duration,
            'reasoning': reasoning,
            'queue_0': queue_0,
            'queue_1': queue_1,
            'moving_0': moving_0,
            'moving_1': moving_1,
        }

    def get_summary(self) -> Dict:
        """Get current traffic summary."""
        cam_0 = self.cameras[0]
        cam_1 = self.cameras[1]

        return {
            'camera_0': {
                'stationary': cam_0.stationary_count,
                'moving': cam_0.moving_count,
                'identified_plates': len(set(cam_0.identified_plates)),
                'recent_plates': cam_0.identified_plates[-5:],  # last 5 seen
            },
            'camera_1': {
                'stationary': cam_1.stationary_count,
                'moving': cam_1.moving_count,
                'identified_plates': len(set(cam_1.identified_plates)),
                'recent_plates': cam_1.identified_plates[-5:],
            },
        }
