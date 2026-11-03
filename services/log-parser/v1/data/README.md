# Sample data

The logs are the 2000-line samples of LogHub, https://github.com/logpai/loghub, for eight systems: Apache,
HDFS, Hadoop, Spark, Zookeeper, OpenStack, Linux and OpenSSH. For each system `prepare.sh` downloads three
files into `fetched/loghub/<system>/`: the raw log (`<system>_2k.log`), LogHub's hand-labelled parse of every
line (`<system>_2k.log_structured.csv`) and the list of event templates (`<system>_2k.log_templates.csv`),
about 5.5 MB together, so nothing but this file lives in `data/`.

Licence: LogHub states that the datasets are freely available for research or academic work, and that any
usage or distribution must refer to the repository URL above and cite the LogHub paper where applicable:
Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu. "Loghub: A Large Collection of System Log
Datasets for AI-driven Log Analytics". ISSRE 2023.

Samples: sample `i` is a block of `data_quality` consecutive lines from the log of system `i mod 8`, starting
at a fixed offset, so the sixty samples cover all eight systems. The templates are ordered by how often they
occur in each system's labelled sample and interleaved across the systems; `pattern_count` keeps the first
ones of that list. The labelled files are used only by the tests, never by `process`.
