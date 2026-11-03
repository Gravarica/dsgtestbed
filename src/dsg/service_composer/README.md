# service_composer

Turns a pipeline of services into something Docker can start.

**`topology.py` knows graphs.** `topology_of(node_names, edges)` checks names, unknown nodes, self-loops and
cycles, and answers: `next_hops_of(node)`, `feeders_of(node)`, `sources()`, `from_first_to_last()`. An edge is
written `qr -> cv`.

**`compose.py` knows Docker Compose.** `compose_for_pipeline(nodes, node_settings, project, run_directory, user)`
gives one container per `NodeDeployment` with CPU quota, CPU set, memory limit, its own records folder, its own
local control and metrics port, and `NEXT_HOPS`, the addresses of the services after it. `without_network=True`
puts every service on a closed network behind a small forwarding container; the verifier uses that.

One service alone is a pipeline with one node. There is no second code path.
