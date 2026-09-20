"""
Generates a short synthetic test clip: colored rectangles standing in for
vehicles, some sitting still in a "queue" region, others driving across the
frame through a "through" region. This is a PLUMBING test only — YOLO will
NOT detect drawn rectangles as vehicles (it's trained on real photos), so
this does not validate detection accuracy. It validates that video I/O, zone
drawing, overlay rendering and CSV logging run end to end without errors,
ahead of a real video being available.
"""
import cv2
import numpy as np

W, H = 1280, 720
FPS = 25
DURATION_SEC = 12
N_FRAMES = FPS * DURATION_SEC

out = cv2.VideoWriter("data/videos/synthetic_plumbing_test.mp4",
                       cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))

# 3 "queued" rectangles that sit still in the lower-left, 2 "moving" rectangles
# that cross the upper-right through-zone left to right.
queued = [(80, 500), (80, 580), (250, 500)]
moving_start_x = -100

for i in range(N_FRAMES):
    frame = np.full((H, W, 3), 40, dtype=np.uint8)
    cv2.putText(frame, "SYNTHETIC PLUMBING TEST - not real vehicle imagery",
                (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)

    for (qx, qy) in queued:
        cv2.rectangle(frame, (qx, qy), (qx + 120, qy + 60), (60, 180, 60), -1)

    mx = int(moving_start_x + (i / N_FRAMES) * (W + 300))
    cv2.rectangle(frame, (mx, 300), (mx + 120, 360), (60, 60, 200), -1)
    mx2 = int(moving_start_x - 150 + (i / N_FRAMES) * (W + 300))
    cv2.rectangle(frame, (mx2, 380), (mx2 + 120, 440), (60, 60, 200), -1)

    out.write(frame)

out.release()
print("wrote data/videos/synthetic_plumbing_test.mp4")
