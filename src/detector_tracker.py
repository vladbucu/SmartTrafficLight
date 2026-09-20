"""
Wraps an Ultralytics YOLO model with its built-in ByteTrack tracker to produce
per-frame vehicle detections that carry a persistent track ID across frames.
The track ID is what lets the queue counter know "this is still the same car"
and lets the crossing counter count each vehicle exactly once.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np
from ultralytics import YOLO


@dataclass
class Detection:
    track_id: int
    cls_id: int
    cls_name: str
    conf: float
    bbox: Tuple[float, float, float, float]   # x1, y1, x2, y2 in pixel coords
    centroid: Tuple[float, float]              # cx, cy in pixel coords


class VehicleDetectorTracker:
    def __init__(
        self,
        weights: str = "yolov8n.pt",
        classes: Optional[List[int]] = None,
        conf: float = 0.35,
        iou: float = 0.5,
        device: str = "cpu",
        tracker: str = "bytetrack.yaml",
    ):
        self.model = YOLO(weights)
        self.classes = classes
        self.conf = conf
        self.iou = iou
        self.device = device
        self.tracker = tracker
        self.names = self.model.names

    def track_frame(self, frame: np.ndarray, persist: bool = True) -> List[Detection]:
        results = self.model.track(
            frame,
            persist=persist,
            classes=self.classes,
            conf=self.conf,
            iou=self.iou,
            device=self.device,
            tracker=self.tracker,
            verbose=False,
        )
        dets: List[Detection] = []
        r = results[0]
        if r.boxes is None or r.boxes.id is None:
            # No tracked detections this frame (nothing above threshold, or
            # tracker hasn't confirmed an ID yet). Not an error — just empty.
            return dets

        boxes = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int)
        confs = r.boxes.conf.cpu().numpy()
        clss = r.boxes.cls.cpu().numpy().astype(int)

        for box, tid, conf, cls_id in zip(boxes, ids, confs, clss):
            x1, y1, x2, y2 = box
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            dets.append(
                Detection(
                    track_id=int(tid),
                    cls_id=int(cls_id),
                    cls_name=self.names.get(int(cls_id), str(cls_id)),
                    conf=float(conf),
                    bbox=(float(x1), float(y1), float(x2), float(y2)),
                    centroid=(float(cx), float(cy)),
                )
            )
        return dets
