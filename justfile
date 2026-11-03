# Every command of the testbed. `just` with no arguments shows this list.

# Show all commands.
list:
    @just --list --unsorted

# Write node.yaml for this machine: which CPUs services may use, which are kept for the testbed, the ports.
setup-node:
    @dsg setup-node

# Fetch, build and check every service in services/. Safe to run again; skips what is done.
setup:
    @dsg setup

# List the services in services/ with their status: verified, failed, or not verified.
services:
    dsg services

# Make a skeleton for a new service, e.g. `just new-service my-detector`.
new-service name:
    dsg new-service {{name}}

# Fetch what a service needs before it can be built (models, data), if it has a prepare.sh.
prepare service version:
    dsg prepare {{service}} {{version}}

# Build the image of a service, e.g. `just build qr-detector v1`.
build service version:
    dsg build {{service}} {{version}}

# Prove inside its image that a service does its job, e.g. `just check qr-detector v1`.
check service version:
    dsg check {{service}} {{version}}

# The testbed's own judgement of a service: is it built right, does it really work, how does it behave.
verify service version:
    dsg verify {{service}} {{version}}

# Run an experiment file, e.g. `just run experiments/qr-single.yaml`.
run experiment_file:
    dsg run {{experiment_file}}

# Check experiment files without running them: runs, nodes, largest core sum and expected hours per file.
estimate +files:
    dsg estimate {{files}}

# Write summary.json for a results folder or a campaign folder, e.g. `just summarize results/a1-qr-detector/<time>`.
summarize folder:
    dsg summarize {{folder}}

# Run several experiments one after another, e.g. `just campaign preliminary experiments/preliminary/*.yaml`.
# Writes results/campaigns/<name>/log.txt and status.txt. Start it inside tmux for a long campaign.
campaign name +files:
    #!/bin/sh
    export PYTHONUNBUFFERED=1
    mkdir -p results/campaigns/{{name}}
    log=results/campaigns/{{name}}/log.txt
    status=results/campaigns/{{name}}/status.txt
    total=$(echo {{files}} | wc -w)
    n=0
    echo "campaign {{name}} started $(date '+%F %T'), $total experiments" | tee -a "$status"
    for file in {{files}}; do
        n=$((n + 1))
        echo "[$n/$total] $file started $(date '+%F %T')" | tee -a "$status"
        if dsg run "$file" >> "$log" 2>&1; then outcome=finished; else outcome=FAILED; fi
        echo "[$n/$total] $file $outcome $(date '+%F %T'), $(grep -c ' -> valid' "$log") valid and $(grep -c ' -> INVALID' "$log") invalid runs so far" | tee -a "$status"
    done
    echo "campaign {{name}} done $(date '+%F %T')" | tee -a "$status"

# List the load patterns an experiment can name.
patterns:
    dsg patterns

# Start Prometheus (127.0.0.1:19090), cAdvisor (:18090) and Grafana (:13000). Optional.
monitor-up:
    dsg monitor-up

# Show whether Prometheus sees the running service.
monitor-status:
    dsg monitor-status

# Stop the monitoring containers.
monitor-down:
    dsg monitor-down

# Unit tests: no Docker, no network.
test:
    @python -m pytest tests/unit -q

# End-to-end test with a real container (needs `just build qr-detector v1`).
test-integration:
    @python -m pytest tests/integration -q
