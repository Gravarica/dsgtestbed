set -e
cd "$(dirname "$0")"
mkdir -p fetched

for model in vosk-model-small-en-us-0.15 vosk-model-en-us-0.22-lgraph; do
  if [ ! -d fetched/models/$model ]; then
    mkdir -p fetched/models
    curl -L --fail --silent --show-error -o fetched/$model.zip "https://alphacephei.com/vosk/models/$model.zip"
    unzip -q -o fetched/$model.zip -d fetched/models
    rm fetched/$model.zip
  fi
  echo "model fetched/models/$model"
done

if [ ! -f fetched/clips/transcripts.json ]; then
  if [ ! -f fetched/dev-clean.tar.gz ]; then
    curl -L --fail --silent --show-error -o fetched/dev-clean.tar.gz "https://www.openslr.org/resources/12/dev-clean.tar.gz"
  fi
  rm -rf fetched/LibriSpeech
  tar -xzf fetched/dev-clean.tar.gz -C fetched
  python3 select_clips.py fetched/LibriSpeech/dev-clean fetched/clips
  rm -rf fetched/LibriSpeech fetched/dev-clean.tar.gz
fi
echo "$(ls fetched/clips/*.flac | wc -l) clips in fetched/clips"
