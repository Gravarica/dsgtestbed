import json
import shutil
import sys
from pathlib import Path

CLIP_COUNT = 60
LEAST_SECONDS = 12.0
FLAC_MARKER = b"fLaC"
STREAMINFO_OFFSET = 8
TOTAL_SAMPLES_BITS = 36


def seconds_of_flac(flac_file: Path) -> float:
    header = flac_file.open("rb").read(STREAMINFO_OFFSET + 18)
    if header[:4] != FLAC_MARKER:
        raise ValueError(f"{flac_file} is not a flac file")
    rate_channels_and_samples = int.from_bytes(header[STREAMINFO_OFFSET + 10 : STREAMINFO_OFFSET + 18], "big")
    sample_rate = rate_channels_and_samples >> 44
    total_samples = rate_channels_and_samples & ((1 << TOTAL_SAMPLES_BITS) - 1)
    return total_samples / sample_rate


def reference_texts(chapter_directory: Path) -> dict:
    texts = {}
    for transcript_file in chapter_directory.glob("*.trans.txt"):
        for line in transcript_file.read_text().splitlines():
            clip_id, text = line.split(" ", 1)
            texts[clip_id] = text.lower()
    return texts


def long_enough_clips(dataset_directory: Path):
    for flac_file in sorted(dataset_directory.glob("*/*/*.flac")):
        if seconds_of_flac(flac_file) >= LEAST_SECONDS:
            yield flac_file


def select(dataset_directory: Path, clips_directory: Path) -> None:
    clips_directory.mkdir(parents=True, exist_ok=True)
    texts = {}
    for flac_file in long_enough_clips(dataset_directory):
        shutil.copy(flac_file, clips_directory / flac_file.name)
        texts[flac_file.stem] = reference_texts(flac_file.parent)[flac_file.stem]
        if len(texts) == CLIP_COUNT:
            break
    if len(texts) < CLIP_COUNT:
        raise SystemExit(f"only {len(texts)} clips of at least {LEAST_SECONDS} seconds in {dataset_directory}")
    (clips_directory / "transcripts.json").write_text(json.dumps(texts, indent=2, sort_keys=True))


if __name__ == "__main__":
    select(Path(sys.argv[1]), Path(sys.argv[2]))
