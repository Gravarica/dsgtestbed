# load_generator

Decides when items arrive. Following elastic-workbench, items are created inside the service container, so
`ArrivalSchedule` and `ItemSource` run there. `RatePattern` and `RateSetter` run on the host.

- `ArrivalSchedule(process, seed, variability)` — planned arrival times: `poisson`, `deterministic`, or `renewal`
  (gamma-distributed gaps with the squared coefficient of variation `variability`: 0 evenly spaced, 1 as Poisson). The times never depend
  on how fast the service is.
- `ItemSource` — emits the items that are due, adds up the rates of all clients, logs every rate change.
- `RatePattern(name, peak_rate, start_second, speed, bursts)` — `constant`, or the elastic-workbench traces
  `bursty` and `diurnal`: one normalized value per second for an hour, times the peak, rounded. `speed` plays the
  trace faster (12 plays the hour in five minutes). `bursts` multiplies the rate by the share `Bursts` gives for
  that second; the rate is then kept to two decimals instead of rounded.
- `Bursts(factor, seconds, seed)` — on/off load with an exact mean: every period has one burst of `seconds` at
  `factor` times the mean and quiet seconds at about half the mean, sized so that the period averages to the mean.
  The burst starts at a seeded second, so each source gets its own. Factor 1 is no bursts.
- `RateSetter(pattern, change_rate)` — pushes the rate once per second, only when it changed, and keeps the rate
  it offered in every second (`offered_rates`).
