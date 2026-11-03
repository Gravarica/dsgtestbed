set -e
cd "$(dirname "$0")"
mkdir -p fetched

if [ -f fetched/clips/transcripts.json ]; then
  echo "$(ls fetched/clips/*.flac | wc -l) clips already in fetched/clips"
  exit 0
fi

SPEECH_CLIPS=../../speech-transcriber/v1/fetched/clips
if [ -f $SPEECH_CLIPS/transcripts.json ]; then
  mkdir -p fetched/clips
  cp $SPEECH_CLIPS/*.flac $SPEECH_CLIPS/transcripts.json fetched/clips/
else
  if [ ! -f fetched/dev-clean.tar.gz ]; then
    curl -L --fail --silent --show-error -o fetched/dev-clean.tar.gz "https://www.openslr.org/resources/12/dev-clean.tar.gz"
  fi
  rm -rf fetched/LibriSpeech
  tar -xzf fetched/dev-clean.tar.gz -C fetched
  python3 select_clips.py fetched/LibriSpeech/dev-clean fetched/clips
  rm -rf fetched/LibriSpeech fetched/dev-clean.tar.gz
fi
echo "$(ls fetched/clips/*.flac | wc -l) clips in fetched/clips"
