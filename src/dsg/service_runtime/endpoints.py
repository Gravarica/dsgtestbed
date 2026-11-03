from __future__ import annotations

START_PROCESSING = "start_processing"
START_MEASUREMENT = "start_measurement"
STOP_PROCESSING = "stop_processing"
CHANGE_RATE = "change_rps"
HAND_OVER = "handover"
CHANGE_ANY_KNOB = "knob"
KNOBS = "knobs"
STATUS = "status"
DEFAULT_CLIENT_ID = "C_1"

ELASTIC_WORKBENCH_SCALING_ENDPOINTS = {
    "data_quality": "quality_scaling",
    "parallelism": "parallelism_scaling",
    "model_size": "model_scaling",
}
