# Sample data

The clips are read English from LibriSpeech `dev-clean`, https://www.openslr.org/12/, by Vassil Panayotov and
others, licensed CC BY 4.0. `prepare.sh` downloads the set and `select_clips.py` keeps the first 60 recordings
of at least twelve seconds, with the reference transcript of each, in `fetched/clips/`.

The two speech models are Vosk models from https://alphacephei.com/vosk/models, licensed Apache 2.0:
`vosk-model-small-en-us-0.15` for `model_size` 1 and `vosk-model-en-us-0.22-lgraph` for `model_size` 2.
`prepare.sh` puts them in `fetched/models/`.

Both are too large for git, so nothing but this file lives in `data/`.
