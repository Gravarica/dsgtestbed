#!/bin/sh
set -e
cd "$(dirname "$0")"

with_services=yes
with_integration_test=no
for argument in "$@"; do
  case "$argument" in
    --no-services) with_services=no ;;
    --with-integration-test) with_integration_test=yes ;;
    *) echo "usage: ./setup.sh [--no-services] [--with-integration-test]"; exit 2 ;;
  esac
done

step() { printf '\n== %s\n' "$1"; }

step "checking this machine"
[ "$(uname -s)" = "Linux" ] || { echo "the testbed runs on Linux with Docker; this is $(uname -s)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is not installed"; exit 1; }
command -v bash >/dev/null || { echo "bash is not installed; the just installer needs it"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "python 3.10 or newer is needed, this is $(python3 --version)"; exit 1; }
command -v docker >/dev/null || { echo "docker is not installed"; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker does not answer; is the daemon running and are you allowed to use it?"; exit 1; }
[ -f /sys/fs/cgroup/cgroup.controllers ] || { echo "this machine does not use cgroup v2, which the testbed needs for CPU and memory counters"; exit 1; }
echo "linux, $(python3 --version), $(docker --version), cgroup v2"

step "installing the just command runner"
export PATH="$HOME/.local/bin:$PATH"
if command -v just >/dev/null; then
  echo "just $(just --version | cut -d' ' -f2) is already installed"
else
  mkdir -p "$HOME/.local/bin"
  curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to "$HOME/.local/bin" >/dev/null
  echo "installed just into $HOME/.local/bin"
fi

step "creating the python environment"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e ".[test]"
echo "installed the testbed into .venv"

step "writing node.yaml for this machine"
just setup-node

if [ "$with_services" = yes ]; then
  step "fetching, building and checking every service"
  just setup
fi

step "running the unit tests"
just test

if [ "$with_integration_test" = yes ]; then
  step "running the tests with real containers"
  just test-integration
fi

step "done"
cat <<TEXT
Before working, in every new shell:
    source .venv/bin/activate
    export PATH="\$HOME/.local/bin:\$PATH"
Then:
    just                                          lists every command
    just run experiments/qr-detector-single.yaml  a first measurement
TEXT
