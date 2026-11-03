# Sample data

The payloads are generated, not downloaded. `payloads.py` builds 30 payloads of `data_quality` kilobytes each
from a fixed seed (20260926), so every worker and every run holds exactly the same bytes. Each payload is a mix
of 4 KB blocks of three kinds: random bytes, repeated sensor log text, and mostly empty blocks with a few set
bytes. They are made in `init_worker` because their size is a knob; no files are needed in this folder.
