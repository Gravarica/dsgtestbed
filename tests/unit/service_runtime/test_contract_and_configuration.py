import pytest

from dsg.service_runtime.configuration import Configuration, ConfigurationLocked, configuration_id
from dsg.service_runtime.contract import (
    HARNESS_KNOBS,
    Knob,
    KnobValueRejected,
    Outputs,
    ServiceInvalid,
    SpecInvalid,
    UnknownKnob,
    load_service_module,
    outputs_from,
    service_spec_from_mapping,
    size_in_bytes,
)

QR_SPEC = {
    "name": "qr-detector",
    "version": "v1",
    "service_type": "elastic-workbench-qr-detector",
    "input": "any",
    "output": "image",
    "knobs": {"data_quality": {"type": "int", "min": 100, "max": 1000, "default": 552}},
}


def test_number_inside_range_is_accepted_as_declared_type():
    knob = Knob("data_quality", "int", default=552, minimum=100, maximum=1000)
    assert knob.validated("700") == 700
    assert isinstance(knob.validated(700.0), int)


def test_number_outside_range_is_rejected_not_clamped():
    with pytest.raises(KnobValueRejected):
        Knob("data_quality", "int", default=552, minimum=100, maximum=1000).validated(1001)


def test_fraction_is_rejected_for_whole_number_knob():
    with pytest.raises(KnobValueRejected):
        Knob("parallelism", "int", default=1, minimum=1, maximum=8).validated(2.5)


def test_choice_knob_accepts_only_listed_values():
    assert HARNESS_KNOBS["discipline"].validated("fifo") == "fifo"
    with pytest.raises(KnobValueRejected):
        HARNESS_KNOBS["discipline"].validated("batch")


def test_window_batching_is_the_default_discipline():
    assert HARNESS_KNOBS["discipline"].default == "window"
    assert HARNESS_KNOBS["window_ms"].default == 1000


def test_spec_combines_harness_and_application_knobs():
    spec = service_spec_from_mapping(QR_SPEC)
    assert set(spec.all_knobs()) == {"parallelism", "discipline", "window_ms", "batch_size", "data_quality"}


def test_spec_may_not_redeclare_a_harness_knob():
    redeclared = {**QR_SPEC, "knobs": {"parallelism": {"type": "int", "min": 1, "max": 4, "default": 1}}}
    with pytest.raises(SpecInvalid):
        service_spec_from_mapping(redeclared)


def test_spec_may_not_declare_any_as_output():
    with pytest.raises(SpecInvalid):
        service_spec_from_mapping({**QR_SPEC, "output": "any"})


def test_configuration_starts_at_defaults_and_accepts_valid_changes():
    configuration = Configuration(service_spec_from_mapping(QR_SPEC).all_knobs())
    assert configuration.values()["data_quality"] == 552
    configuration.change("data_quality", 300)
    assert configuration.values()["data_quality"] == 300


def test_configuration_rejects_unknown_knob():
    with pytest.raises(UnknownKnob):
        Configuration(service_spec_from_mapping(QR_SPEC).all_knobs()).change("model_size", 2)


def test_locked_configuration_cannot_change():
    configuration = Configuration(service_spec_from_mapping(QR_SPEC).all_knobs())
    configuration.lock()
    with pytest.raises(ConfigurationLocked):
        configuration.change("data_quality", 300)


def test_configuration_id_depends_only_on_values():
    assert configuration_id({"a": 1, "b": 2}) == configuration_id({"b": 2, "a": 1})
    assert configuration_id({"a": 1}) != configuration_id({"a": 2})


def test_service_without_process_function_is_refused(tmp_path):
    (tmp_path / "service.py").write_text("def something_else():\n    return 1\n")
    with pytest.raises(ServiceInvalid):
        load_service_module(tmp_path)


def test_single_list_result_is_one_output_unless_wrapped():
    assert outputs_from([1, 2, 3]) == [[1, 2, 3]]
    assert outputs_from(Outputs([1, 2, 3])) == [1, 2, 3]
    assert outputs_from(None) == []
    assert size_in_bytes(b"abcd") == 4


def test_service_may_define_dataclasses_and_use_helper_files(tmp_path):
    (tmp_path / "helper.py").write_text("FACTOR = 3\n")
    (tmp_path / "service.py").write_text(
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "from helper import FACTOR\n\n\n"
        "@dataclass\nclass WorkerState:\n    factor: int\n\n\n"
        "def init_worker(cfg):\n    return WorkerState(FACTOR)\n\n\n"
        "def process(item, cfg, state):\n    return state.factor\n"
    )
    module = load_service_module(tmp_path)
    assert module.process(None, None, module.init_worker(None)) == 3
