import json
import math
import random
import sys
from array import array
from pathlib import Path

SEED = 20260926
WINDOW_COUNT = 40
CHANNEL_COUNT = 64
READINGS_PER_WINDOW = 8192
READINGS_PER_SECOND = 100.0
CHANNEL_KINDS = {
    "temperature": {"level": (15.0, 35.0), "slope": (-0.002, 0.002), "amplitude": (0.2, 2.0), "frequency_hz": (0.05, 0.5), "noise": (0.02, 0.2)},
    "vibration": {"level": (-0.05, 0.05), "slope": (-0.00001, 0.00001), "amplitude": (0.5, 3.0), "frequency_hz": (5.0, 45.0), "noise": (0.1, 0.8)},
    "current": {"level": (2.0, 12.0), "slope": (-0.0005, 0.0005), "amplitude": (0.5, 4.0), "frequency_hz": (0.5, 10.0), "noise": (0.05, 0.5)},
    "humidity": {"level": (30.0, 80.0), "slope": (-0.003, 0.003), "amplitude": (0.5, 5.0), "frequency_hz": (0.02, 0.3), "noise": (0.1, 1.0)},
}


def channel_parameters(generator: random.Random, channel_index: int) -> dict:
    kind = list(CHANNEL_KINDS)[channel_index % len(CHANNEL_KINDS)]
    ranges = CHANNEL_KINDS[kind]
    parameters = {name: generator.uniform(low, high) for name, (low, high) in ranges.items()}
    parameters["phase"] = generator.uniform(0.0, 2.0 * math.pi)
    parameters["kind"] = kind
    return parameters


def channel_readings(generator: random.Random, parameters: dict) -> array:
    angular_step = 2.0 * math.pi * parameters["frequency_hz"] / READINGS_PER_SECOND
    return array(
        "f",
        (
            parameters["level"]
            + parameters["slope"] * position
            + parameters["amplitude"] * math.sin(angular_step * position + parameters["phase"])
            + generator.gauss(0.0, parameters["noise"])
            for position in range(READINGS_PER_WINDOW)
        ),
    )


def write_windows(output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    generator = random.Random(SEED)
    all_parameters = []
    with open(output_directory / "readings.f32", "wb") as readings_file:
        for _ in range(WINDOW_COUNT):
            window_parameters = [channel_parameters(generator, channel) for channel in range(CHANNEL_COUNT)]
            for parameters in window_parameters:
                readings = channel_readings(generator, parameters)
                if sys.byteorder != "little":
                    readings.byteswap()
                readings.tofile(readings_file)
            all_parameters.append(window_parameters)
    layout = {
        "windows": WINDOW_COUNT,
        "channels": CHANNEL_COUNT,
        "readings_per_window": READINGS_PER_WINDOW,
        "readings_per_second": READINGS_PER_SECOND,
        "dtype": "float32 little endian, windows x channels x readings",
        "seed": SEED,
        "parameters": all_parameters,
    }
    (output_directory / "windows.json").write_text(json.dumps(layout))


if __name__ == "__main__":
    write_windows(Path(sys.argv[1]))
