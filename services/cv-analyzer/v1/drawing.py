from __future__ import annotations

import cv2
import numpy as np

CLASS_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]
CLASS_COLORS = np.random.default_rng(3).uniform(0, 255, size=(len(CLASS_NAMES), 3))
MASK_ALPHA = 0.3


def with_drawn_detections(image: np.ndarray, boxes, scores, class_ids) -> np.ndarray:
    shorter_side = min(image.shape[:2])
    font_size = shorter_side * 0.0006
    text_thickness = int(shorter_side * 0.001)
    drawn = with_filled_boxes(image, boxes, class_ids)
    for class_id, box, score in zip(class_ids, boxes, scores):
        color = CLASS_COLORS[class_id]
        left, top, right, bottom = box.astype(int)
        cv2.rectangle(drawn, (left, top), (right, bottom), color, 2)
        draw_caption(drawn, f"{CLASS_NAMES[class_id]} {int(score * 100)}%", left, top, color, font_size, text_thickness)
    return drawn


def with_filled_boxes(image: np.ndarray, boxes, class_ids) -> np.ndarray:
    filled = image.copy()
    for box, class_id in zip(boxes, class_ids):
        left, top, right, bottom = box.astype(int)
        cv2.rectangle(filled, (left, top), (right, bottom), CLASS_COLORS[class_id], -1)
    return cv2.addWeighted(filled, MASK_ALPHA, image, 1 - MASK_ALPHA, 0)


def draw_caption(image, caption: str, left: int, top: int, color, font_size: float, thickness: int) -> None:
    (text_width, text_height), _ = cv2.getTextSize(caption, cv2.FONT_HERSHEY_SIMPLEX, font_size, thickness)
    cv2.rectangle(image, (left, top), (left + text_width, top - int(text_height * 1.2)), color, -1)
    cv2.putText(image, caption, (left, top), cv2.FONT_HERSHEY_SIMPLEX, font_size, (255, 255, 255), thickness, cv2.LINE_AA)
