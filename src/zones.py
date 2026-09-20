"""
Zones and crossing lines are defined in NORMALIZED coordinates (0-1, origin
top-left) so the same config works regardless of camera resolution. They must
be recalibrated per physical camera install by looking at one real frame.
"""
from typing import List, Tuple
import cv2
import numpy as np


class Zone:
    def __init__(self, norm_points: List[Tuple[float, float]], name: str = ""):
        self.norm_points = norm_points
        self.name = name

    def to_pixel_polygon(self, frame_w: int, frame_h: int) -> np.ndarray:
        return np.array(
            [[int(x * frame_w), int(y * frame_h)] for x, y in self.norm_points],
            dtype=np.int32,
        )

    def contains(self, point: Tuple[float, float], frame_w: int, frame_h: int) -> bool:
        poly = self.to_pixel_polygon(frame_w, frame_h)
        return cv2.pointPolygonTest(poly, (float(point[0]), float(point[1])), False) >= 0


class CrossingLine:
    """
    A directed line. A track has 'passed' once its centroid is on the
    passed_side of the line p1->p2. Used to count vehicles that have cleared
    a point (e.g. the far end of the single-lane corridor).
    """

    def __init__(self, p1_norm: Tuple[float, float], p2_norm: Tuple[float, float], passed_side: str = "right"):
        self.p1_norm = p1_norm
        self.p2_norm = p2_norm
        assert passed_side in ("right", "left")
        self.passed_side = passed_side

    def to_pixel(self, frame_w: int, frame_h: int):
        p1 = (self.p1_norm[0] * frame_w, self.p1_norm[1] * frame_h)
        p2 = (self.p2_norm[0] * frame_w, self.p2_norm[1] * frame_h)
        return p1, p2

    def side_of(self, point: Tuple[float, float], frame_w: int, frame_h: int) -> str:
        p1, p2 = self.to_pixel(frame_w, frame_h)
        cross = (p2[0] - p1[0]) * (point[1] - p1[1]) - (p2[1] - p1[1]) * (point[0] - p1[0])
        return "right" if cross > 0 else "left"

    def has_passed(self, point: Tuple[float, float], frame_w: int, frame_h: int) -> bool:
        return self.side_of(point, frame_w, frame_h) == self.passed_side
