from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import soundfile
from vosk import KaldiRecognizer, Model, SetLogLevel

SAMPLE_RATE = 16000
CHUNK_FRAMES = 4000
MODEL_DIRECTORIES = {1: "vosk-model-small-en-us-0.15", 2: "vosk-model-en-us-0.22-lgraph"}


@dataclass
class Samples:
    model: Model
    model_directory: str
    clip_ids: List[str]
    references: Dict[str, str]
    audio: List[bytes]


def init_worker(cfg) -> Samples:
    SetLogLevel(-1)
    clips_directory = Path(cfg.service_directory) / "fetched" / "clips"
    references = json.loads((clips_directory / "transcripts.json").read_text())
    clip_ids = sorted(references)
    model_directory = MODEL_DIRECTORIES[int(cfg.model_size)]
    frames = int(cfg.data_quality) * SAMPLE_RATE
    return Samples(
        model=Model(str(Path(cfg.service_directory) / "fetched" / "models" / model_directory)),
        model_directory=model_directory,
        clip_ids=clip_ids,
        references=references,
        audio=[first_frames(clips_directory / f"{clip_id}.flac", frames) for clip_id in clip_ids],
    )


def process(item, cfg, samples: Samples) -> str:
    return transcribed(samples.model, samples.audio[item.sample_index])


def transcribed(model: Model, audio: bytes) -> str:
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    spoken = []
    for start in range(0, len(audio), CHUNK_FRAMES * 2):
        if recognizer.AcceptWaveform(audio[start : start + CHUNK_FRAMES * 2]):
            spoken.append(json.loads(recognizer.Result())["text"])
    spoken.append(json.loads(recognizer.FinalResult())["text"])
    return " ".join(part for part in spoken if part)


def first_frames(flac_file: Path, frames: int) -> bytes:
    audio, rate = soundfile.read(str(flac_file), frames=frames, dtype="int16")
    if rate != SAMPLE_RATE:
        raise ValueError(f"{flac_file} is recorded at {rate} Hz")
    return audio.tobytes()


def word_error_rate(reference_words: List[str], spoken_words: List[str]) -> float:
    if not reference_words:
        return 1.0
    edits = list(range(len(spoken_words) + 1))
    for reference_index, reference_word in enumerate(reference_words, start=1):
        previous_row, edits = edits, [reference_index]
        for spoken_index, spoken_word in enumerate(spoken_words, start=1):
            substitution = previous_row[spoken_index - 1] + (reference_word != spoken_word)
            edits.append(min(substitution, previous_row[spoken_index] + 1, edits[spoken_index - 1] + 1))
    return edits[-1] / len(reference_words)
