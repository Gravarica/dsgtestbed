# Sample data

The readings are synthetic and generated, so there is no licence to respect. `prepare.sh` runs
`generate_readings.py` (standard library only, seed 20260926) once and writes into `fetched/readings/`:

- `readings.f32`: 40 windows x 64 channels x 8192 readings, float32 little endian, about 84 MB.
- `windows.json`: the layout and, for every window and channel, the parameters it was generated from.

Channels cycle through four kinds that look like IoT sensors sampled at 100 readings per second: temperature
(slow drift and a slow cycle), vibration (5 to 45 Hz oscillation), current (0.5 to 10 Hz), humidity (slow).
Each reading is level + slope x position + amplitude x sin(2 pi f t + phase) + Gaussian noise. The known
parameters let the tests check the summaries against the truth. The file is too large for git, so only this
README lives in `data/`.
