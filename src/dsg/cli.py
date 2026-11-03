from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dsg.docker_host import DockerHost
from dsg.node import (
    MachineNotReady,
    load_node_settings,
    node_settings_for_this_machine,
    problems_with_this_machine,
    write_node_settings,
)
from dsg.repository import NODE_FILE
from dsg.service_generator.setup import READY, set_up_every_service, setup_report
from dsg.load_generator.rate_pattern import available_patterns
from dsg.monitor.prometheus import PrometheusConnection
from dsg.monitor.stack import prometheus_url, start_monitor_stack, stop_monitor_stack
from dsg.service_generator import builder
from dsg.service_generator.catalog import ServiceMissing, list_services
from dsg.service_verifier.verification import VERIFIED, report_in_plain_words, status_of, verify


def show_services(arguments) -> int:
    for service, version in list_services():
        print(f"{service:24} {version:6} {status_of(service, version)}")
    return 0


def verify_service(arguments) -> int:
    report = verify(arguments.service, arguments.version)
    print(report_in_plain_words(report))
    return 0 if report["status"] == VERIFIED else 1


def create_service(arguments) -> int:
    print(f"created {builder.new_service(arguments.name)}")
    return 0


def prepare_service(arguments) -> int:
    prepared = builder.prepare(arguments.service, arguments.version)
    print("prepared" if prepared else "this service has no prepare.sh, nothing to do")
    return 0


def build_service(arguments) -> int:
    print(f"built {builder.build(arguments.service, arguments.version, DockerHost())}")
    return 0


def check_service(arguments) -> int:
    return 0 if builder.check(arguments.service, arguments.version, DockerHost()) else 1


def run_experiment_file(arguments) -> int:
    from dsg.experiment.grid import run_experiment
    from dsg.experiment.plan import load_experiment

    from dsg.experiment.plan import service_and_version

    experiment = load_experiment(Path(arguments.experiment_file))
    for node in (experiment.get("nodes") or {}).values():
        service, version = service_and_version(node.get("service", ""))
        try:
            status = status_of(service, version)
        except ServiceMissing:
            continue
        if status != VERIFIED:
            print(f"WARNING: {service} {version} is {status}. Run: just verify {service} {version}")
    run_experiment(Path(arguments.experiment_file))
    return 0


def estimate_experiment_files(arguments) -> int:
    from dsg.experiment.estimate import estimate_of, estimate_table
    from dsg.experiment.plan import PlanInvalid

    workload_cpu_count = load_node_settings(NODE_FILE).workload_cpu_count()
    estimates, refused = [], 0
    for experiment_file in arguments.experiment_files:
        try:
            estimates.append(estimate_of(Path(experiment_file), workload_cpu_count))
        except PlanInvalid as problem:
            print(f"REFUSED {experiment_file}: {problem}")
            refused += 1
    if estimates:
        print(estimate_table(estimates))
    return 1 if refused else 0


def set_up_node(arguments) -> int:
    problems = problems_with_this_machine()
    for problem in problems:
        print(f"PROBLEM: {problem}")
    if problems:
        return 1
    if NODE_FILE.exists() and not arguments.overwrite:
        print(f"{NODE_FILE.name} exists and is kept; use --overwrite to write it again")
        return 0
    try:
        settings = node_settings_for_this_machine(os.cpu_count())
    except MachineNotReady as problem:
        print(f"PROBLEM: {problem}")
        return 1
    write_node_settings(NODE_FILE, settings)
    print(f"wrote {NODE_FILE.name}: {settings.workload_cpu_count()} CPUs for services ({settings.workload_cpuset}), {settings.infrastructure_cpuset} kept for the testbed")
    return 0


def set_up_services(arguments) -> int:
    outcomes = set_up_every_service(DockerHost(), print, rebuild=arguments.rebuild)
    print(setup_report(outcomes))
    return 0 if all(outcome.outcome == READY for outcome in outcomes) else 1


def summarize_results(arguments) -> int:
    from dsg.experiment.summary import write_summary

    print(write_summary(Path(arguments.results_folder)))
    return 0


def show_patterns(arguments) -> int:
    print("\n".join(available_patterns()))
    return 0


def monitor_up(arguments) -> int:
    node = load_node_settings(NODE_FILE)
    start_monitor_stack(DockerHost(), node)
    print(f"Prometheus {prometheus_url(node)}   Grafana http://127.0.0.1:{node.grafana_port}   cAdvisor http://127.0.0.1:{node.cadvisor_port}")
    return 0


def monitor_down(arguments) -> int:
    stop_monitor_stack(DockerHost(), load_node_settings(NODE_FILE))
    return 0


def monitor_status(arguments) -> int:
    prometheus = PrometheusConnection(prometheus_url(load_node_settings(NODE_FILE)))
    if not prometheus.is_up():
        print("Prometheus is not running. Start it with: just monitor-up")
        return 1
    for target, health in prometheus.scrape_targets().items():
        print(f"{health:5} {target}")
    return 0


def command_line() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dsg")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("services").set_defaults(act=show_services)
    setup_node = commands.add_parser("setup-node")
    setup_node.add_argument("--overwrite", action="store_true")
    setup_node.set_defaults(act=set_up_node)
    setup = commands.add_parser("setup")
    setup.add_argument("--rebuild", action="store_true")
    setup.set_defaults(act=set_up_services)
    commands.add_parser("patterns").set_defaults(act=show_patterns)
    new_service = commands.add_parser("new-service")
    new_service.add_argument("name")
    new_service.set_defaults(act=create_service)
    for name, act in (
        ("prepare", prepare_service),
        ("build", build_service),
        ("check", check_service),
        ("verify", verify_service),
    ):
        command = commands.add_parser(name)
        command.add_argument("service")
        command.add_argument("version")
        command.set_defaults(act=act)
    summarize = commands.add_parser("summarize")
    summarize.add_argument("results_folder")
    summarize.set_defaults(act=summarize_results)
    estimate = commands.add_parser("estimate")
    estimate.add_argument("experiment_files", nargs="+")
    estimate.set_defaults(act=estimate_experiment_files)
    run = commands.add_parser("run")
    run.add_argument("experiment_file")
    run.set_defaults(act=run_experiment_file)
    for name, act in (("monitor-up", monitor_up), ("monitor-down", monitor_down), ("monitor-status", monitor_status)):
        commands.add_parser(name).set_defaults(act=act)
    return parser


def main() -> None:
    arguments = command_line().parse_args()
    sys.exit(arguments.act(arguments))


if __name__ == "__main__":
    main()
