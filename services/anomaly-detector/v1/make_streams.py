import sys
from pathlib import Path

import numpy as np

SEED = 20260926
STREAM_COUNT = 60
STREAM_LENGTH = 16384
NOISE_MEMORY = 0.6
SMALLEST_GAP_BETWEEN_ANOMALIES = 400
FIRST_ANOMALY_BEFORE = 200
SPIKE, LEVEL_SHIFT, DRIFT = 0, 1, 2
KIND_SHARES = [0.6, 0.2, 0.2]


def noise_with_memory(generator: np.random.Generator, length: int) -> np.ndarray:
    shocks = generator.normal(0.0, 1.0, length)
    noise = np.empty(length)
    noise[0] = shocks[0]
    for position in range(1, length):
        noise[position] = NOISE_MEMORY * noise[position - 1] + shocks[position]
    return noise / np.std(noise)


def normal_behaviour(generator: np.random.Generator, length: int) -> np.ndarray:
    time = np.arange(length)
    slow_period = generator.uniform(2000, 6000)
    faster_period = generator.uniform(800, 1600)
    return (
        generator.uniform(-20, 20)
        + generator.uniform(2, 6) * np.sin(2 * np.pi * time / slow_period + generator.uniform(0, 2 * np.pi))
        + generator.uniform(1, 3) * np.sin(2 * np.pi * time / faster_period + generator.uniform(0, 2 * np.pi))
        + generator.uniform(-3, 3) * time / length
        + noise_with_memory(generator, length)
    )


def anomaly_starts(generator: np.random.Generator, length: int) -> list:
    starts = [int(generator.integers(20, FIRST_ANOMALY_BEFORE))]
    while True:
        next_start = starts[-1] + SMALLEST_GAP_BETWEEN_ANOMALIES + int(generator.integers(0, 800))
        if next_start >= length - SMALLEST_GAP_BETWEEN_ANOMALIES:
            return starts
        starts.append(next_start)


def injected(generator: np.random.Generator, signal: np.ndarray):
    anomalous = np.zeros(len(signal), dtype=bool)
    events = []
    for start in anomaly_starts(generator, len(signal)):
        kind = int(generator.choice(3, p=KIND_SHARES))
        sign = generator.choice([-1.0, 1.0])
        if kind == SPIKE:
            end = start + 1
            signal[start] += sign * generator.uniform(6, 10)
        elif kind == LEVEL_SHIFT:
            end = start + int(generator.integers(20, 61))
            signal[start:end] += sign * generator.uniform(5, 8)
        else:
            end = start + int(generator.integers(40, 101))
            hump = 1.0 - np.abs(np.linspace(-1.0, 1.0, end - start))
            signal[start:end] += sign * generator.uniform(6, 9) * hump
        anomalous[start:end] = True
        events.append((start, end, kind))
    return anomalous, np.array(events, dtype=np.int32)


def make_streams(output_file: Path) -> None:
    generator = np.random.default_rng(SEED)
    streams = np.empty((STREAM_COUNT, STREAM_LENGTH), dtype=np.float32)
    anomalous = np.empty((STREAM_COUNT, STREAM_LENGTH), dtype=bool)
    all_events = []
    for stream_number in range(STREAM_COUNT):
        signal = normal_behaviour(generator, STREAM_LENGTH)
        anomalous[stream_number], events = injected(generator, signal)
        streams[stream_number] = signal
        all_events.append(np.column_stack([np.full(len(events), stream_number, dtype=np.int32), events]))
    np.savez_compressed(output_file, streams=streams, anomalous=anomalous, events=np.concatenate(all_events))
    print(f"{STREAM_COUNT} streams of {STREAM_LENGTH} readings in {output_file}")


if __name__ == "__main__":
    make_streams(Path(sys.argv[1]))
