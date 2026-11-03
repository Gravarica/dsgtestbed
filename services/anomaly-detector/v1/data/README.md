# Sample data

`streams.npz` holds 60 synthetic sensor streams of 16384 readings each, made by `make_streams.py` with a fixed
seed (`python3 make_streams.py data/streams.npz`). No outside data is used, so there is no licence to state.

Each stream is normal behaviour, a random offset, two slow periodic parts, a small trend and noise with
memory, plus injected anomalies about every 400 to 1200 readings, the first one always within the first 200
readings: spikes (one reading, 6 to 10 noise levels), level shifts (20 to 60 readings moved by 5 to 8) and
drifts (a hump of 40 to 100 readings, peak 6 to 9). The file stores the streams (`streams`), which readings are
anomalous (`anomalous`) and one row per anomaly (`events`: stream, start, end, kind 0 spike, 1 level shift,
2 drift).

## What the knobs mean

- `window_length`: how many readings from the start of each stream one item analyses.
- `model_size`: 1 is a robust z-score of the distance from a running median, 2 an isolation forest of 100
  trees with 256 readings per tree, 3 an isolation forest of 400 trees with 1024 readings per tree. Both
  forests work on the distance from the running median, its smoothed value and the step from the previous
  reading.
- `threshold`: a reading is anomalous when its anomaly score lies more than this many robust standard
  deviations above the median score of the window.
