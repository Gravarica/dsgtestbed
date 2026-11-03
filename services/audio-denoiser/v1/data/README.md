# Sample data

The clips are read English from LibriSpeech `dev-clean`, https://www.openslr.org/12/, by Vassil Panayotov and
others, licensed CC BY 4.0. They are the same 60 recordings of at least twelve seconds that speech-transcriber v1
uses. `prepare.sh` copies them from that service's `fetched/clips/` when it is present, and otherwise downloads
the set and keeps the first 60 such recordings with `select_clips.py`. They end up in `fetched/clips/`.

The recordings are clean, so every worker adds white noise to them when it starts: 5 dB below the level of the
clip, drawn with a fixed seed per clip. That noisy clip is what the service cleans.

They are too large for git, so nothing but this file lives in `data/`.
