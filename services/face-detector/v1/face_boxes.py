from __future__ import annotations

import numpy as np

FACE_PROBABILITY_THRESHOLD = 0.7
OVERLAP_THRESHOLD = 0.5
CANDIDATES_CONSIDERED = 200


def area_of(left_top: np.ndarray, right_bottom: np.ndarray) -> np.ndarray:
    sides = np.clip(right_bottom - left_top, 0.0, None)
    return sides[..., 0] * sides[..., 1]


def overlap_ratio(boxes: np.ndarray, reference_box: np.ndarray) -> np.ndarray:
    overlap = area_of(np.maximum(boxes[..., :2], reference_box[..., :2]), np.minimum(boxes[..., 2:], reference_box[..., 2:]))
    total = area_of(boxes[..., :2], boxes[..., 2:]) + area_of(reference_box[..., :2], reference_box[..., 2:]) - overlap
    return overlap / (total + 1e-5)


def without_overlapping_boxes(boxes_with_probability: np.ndarray) -> np.ndarray:
    boxes = boxes_with_probability[:, :-1]
    remaining = np.argsort(boxes_with_probability[:, -1])[-CANDIDATES_CONSIDERED:]
    kept = []
    while len(remaining) > 0:
        best = remaining[-1]
        kept.append(best)
        if len(remaining) == 1:
            break
        remaining = remaining[:-1]
        remaining = remaining[overlap_ratio(boxes[remaining, :], np.expand_dims(boxes[best, :], axis=0)) <= OVERLAP_THRESHOLD]
    return boxes_with_probability[kept, :]


def face_boxes_in_pixels(image_width: int, image_height: int, confidences: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    face_probabilities = confidences[0][:, 1]
    likely = face_probabilities > FACE_PROBABILITY_THRESHOLD
    if not likely.any():
        return np.empty((0, 4), dtype=np.int32)
    candidates = np.concatenate([boxes[0][likely, :], face_probabilities[likely].reshape(-1, 1)], axis=1)
    kept = without_overlapping_boxes(candidates)
    kept[:, [0, 2]] *= image_width
    kept[:, [1, 3]] *= image_height
    return kept[:, :4].astype(np.int32)
