import pytest

from dsg.node import MachineNotReady, cpuset_of, cpus_in_set, load_node_settings, node_settings_for_this_machine, write_node_settings


def with_smt(cpu_count):
    half = cpu_count // 2
    return lambda cpu: sorted({cpu, (cpu + half) % cpu_count})


def without_smt(cpu):
    return [cpu]


def test_cpu_numbers_and_cpuset_text_convert_both_ways():
    assert cpus_in_set("0-1,16-17") == [0, 1, 16, 17]
    assert cpuset_of([0, 1, 16, 17]) == "0-1,16-17"
    assert cpuset_of([3]) == "3"
    assert cpuset_of([2, 3, 4, 5, 6, 7]) == "2-7"


def test_a_32_thread_machine_with_smt_keeps_two_cores_and_their_siblings():
    settings = node_settings_for_this_machine(32, with_smt(32))
    assert settings.infrastructure_cpuset == "0-1,16-17"
    assert settings.workload_cpuset == "2-15,18-31"
    assert settings.workload_cpu_count() == 28


def test_a_machine_without_smt_keeps_two_cpus():
    settings = node_settings_for_this_machine(8, without_smt)
    assert settings.infrastructure_cpuset == "0-1"
    assert settings.workload_cpuset == "2-7"


def test_a_small_machine_still_leaves_two_cpus_for_services():
    settings = node_settings_for_this_machine(4, with_smt(4))
    assert settings.workload_cpu_count() == 2


def test_too_small_a_machine_is_refused():
    with pytest.raises(MachineNotReady):
        node_settings_for_this_machine(3, without_smt)


def test_node_settings_round_trip_through_the_file(tmp_path):
    settings = node_settings_for_this_machine(16, with_smt(16))
    write_node_settings(tmp_path / "node.yaml", settings)
    assert load_node_settings(tmp_path / "node.yaml") == settings
    assert settings.prometheus_port == 19090
