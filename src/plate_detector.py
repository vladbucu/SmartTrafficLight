"""
License plate detection and OCR with multi-frame confidence validation.
Designed for Raspberry Pi: uses EasyOCR (lightweight) with frame skipping.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import numpy as np
from collections import defaultdict
import cv2

try:
    import easyocr
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


@dataclass
class PlateDetection:
    track_id: int
    plate_text: str
    confidence: float  # 0-1, how confident we are in this plate
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    color: Tuple[int, int, int]  # B, G, R from vehicle
    frame_count: int = 1  # frames we've seen this plate


class PlateOCRTracker:
    """
    Multi-frame plate validation system.
    - Requires consistent reads across multiple frames before confirming a plate
    - Tracks confidence per vehicle by track_id
    - Optimized for real-time on CPU (frame skipping, minimal overhead)
    """

    def __init__(self, confidence_threshold: float = 0.5, frame_skip: int = 3):
        """
        confidence_threshold: minimum confidence to report a detected plate (0-1)
        frame_skip: process every Nth frame for OCR (1=every frame, 3=every 3rd)
        """
        self.confidence_threshold = confidence_threshold
        self.frame_skip = frame_skip
        self.frame_count = 0

        # Initialize OCR reader if available
        self.reader = None
        if HAS_OCR:
            try:
                self.reader = easyocr.Reader(['en'], gpu=False)
            except Exception as e:
                print(f"Warning: EasyOCR init failed: {e}, plates won't be detected")

        # Track plates per vehicle (track_id)
        self.vehicle_plates: Dict[int, List[str]] = defaultdict(list)
        self.vehicle_confidences: Dict[int, List[float]] = defaultdict(list)
        self.vehicle_colors: Dict[int, Tuple[int, int, int]] = {}

        # Confirmed identities (track_id -> plate_text)
        self.confirmed_plates: Dict[int, str] = {}
        self.confirmed_confidences: Dict[int, float] = {}

    def extract_vehicle_color(self, frame: np.ndarray, bbox: Tuple[float, float, float, float]) -> Tuple[int, int, int]:
        """Extract dominant color from vehicle bounding box."""
        x1, y1, x2, y2 = bbox
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        # Expand box slightly to avoid edges
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1 + 5), max(0, y1 + 5)
        x2, y2 = min(w, x2 - 5), min(h, y2 - 5)

        if x2 <= x1 or y2 <= y1:
            return (128, 128, 128)  # neutral gray

        roi = frame[y1:y2, x1:x2]
        # Use center region for color (more representative)
        h_roi, w_roi = roi.shape[:2]
        center = roi[h_roi//4:3*h_roi//4, w_roi//4:3*w_roi//4]

        # Get dominant color
        avg_color = center.mean(axis=(0, 1)).astype(np.uint8)
        return tuple(int(c) for c in avg_color)

    def detect_and_read_plate(self, frame: np.ndarray, vehicle_bbox: Tuple[float, float, float, float]) -> Optional[str]:
        """
        Attempt to detect and read license plate in vehicle region.
        Returns plate text or None.
        """
        if not HAS_OCR or self.reader is None:
            return None

        try:
            x1, y1, x2, y2 = vehicle_bbox
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            if x2 <= x1 or y2 <= y1:
                return None

            roi = frame[y1:y2, x1:x2]

            # Run OCR
            results = self.reader.readtext(roi, detail=0)
            if not results:
                return None

            # Join text, keep only alphanumeric + common plate separators
            plate_text = ''.join(results)
            plate_text = ''.join(c for c in plate_text if c.isalnum() or c in '-')

            return plate_text if len(plate_text) >= 5 else None

        except Exception as e:
            return None

    def update(self, detections: List, frame: np.ndarray) -> List[PlateDetection]:
        """
        Update plate tracking for current frame detections.
        Returns list of PlateDetection objects with updated confidence.
        """
        self.frame_count += 1
        should_ocr = (self.frame_count % self.frame_skip) == 0

        result_detections = []
        processed_ids = set()

        for det in detections:
            track_id = det.track_id
            processed_ids.add(track_id)

            # Extract color for this vehicle
            color = self.extract_vehicle_color(frame, det.bbox)
            self.vehicle_colors[track_id] = color

            # Attempt OCR on sampling frames
            plate_text = None
            read_confidence = 0.0

            if should_ocr:
                plate_text = self.detect_and_read_plate(frame, det.bbox)
                if plate_text:
                    self.vehicle_plates[track_id].append(plate_text)
                    read_confidence = 0.6  # base confidence for OCR read

            # Calculate overall confidence from history
            history = self.vehicle_plates[track_id]
            confidence = 0.0

            if history:
                # Count mode (most common plate text)
                from collections import Counter
                plate_counter = Counter(history)
                most_common_plate, count = plate_counter.most_common(1)[0]

                # Confidence: how many times we've seen this plate / total samples
                base_conf = count / max(1, len(history))

                # Boost if consistent (have multiple reads)
                if count >= 2:
                    base_conf = min(0.95, base_conf + 0.2)

                confidence = base_conf

                # Update confirmed if exceeded threshold
                if confidence >= self.confidence_threshold:
                    if track_id not in self.confirmed_plates or self.confirmed_confidences.get(track_id, 0) < confidence:
                        self.confirmed_plates[track_id] = most_common_plate
                        self.confirmed_confidences[track_id] = confidence

            # Get most likely plate
            final_plate = self.confirmed_plates.get(track_id, "?????")
            final_conf = self.confirmed_confidences.get(track_id, confidence)

            result_detections.append(
                PlateDetection(
                    track_id=track_id,
                    plate_text=final_plate,
                    confidence=final_conf,
                    bbox=det.bbox,
                    color=color,
                    frame_count=len(history)
                )
            )

        # Clean up old track IDs
        for track_id in list(self.vehicle_plates.keys()):
            if track_id not in processed_ids:
                # Vehicle dropped from tracking, keep historical data
                pass

        return result_detections
