import pytest

from dsg.service_generator.builder import PreparationFailed, ServiceAlreadyExists, new_service, prepare
from dsg.service_generator.catalog import ServiceMissing, image_name, list_services, service_directory
from dsg.service_runtime.contract import load_service_module, load_service_spec


def test_new_service_skeleton_is_a_valid_loadable_service(tmp_path):
    directory = new_service("my-detector", services_directory=tmp_path)
    spec = load_service_spec(directory)
    assert (spec.name, spec.version) == ("my-detector", "v1")
    assert "work_size" in spec.application_knobs
    assert callable(load_service_module(directory).process)
    assert "def test_proof(" in (directory / "test_service.py").read_text()
    assert (directory / "brief.yaml").exists()


def test_existing_service_version_is_never_overwritten(tmp_path):
    new_service("my-detector", services_directory=tmp_path)
    with pytest.raises(ServiceAlreadyExists):
        new_service("my-detector", services_directory=tmp_path)


def test_catalog_lists_every_service_version_and_names_its_image(tmp_path):
    new_service("b-service", services_directory=tmp_path)
    new_service("a-service", services_directory=tmp_path)
    new_service("a-service", version="v2", services_directory=tmp_path)
    assert list_services(tmp_path) == [("a-service", "v1"), ("a-service", "v2"), ("b-service", "v1")]
    assert image_name("a-service", "v2") == "dsg/a-service:v2"


def test_unknown_service_is_reported_before_docker_is_touched(tmp_path):
    with pytest.raises(ServiceMissing):
        service_directory("ghost", "v1", tmp_path)


def test_the_qr_detector_from_elastic_workbench_is_in_the_catalog():
    assert ("qr-detector", "v1") in list_services()


def test_prepare_runs_the_service_own_script_in_its_folder(tmp_path):
    directory = new_service("with-models", services_directory=tmp_path)
    assert prepare("with-models", "v1", tmp_path) is False
    (directory / "prepare.sh").write_text("touch models_were_fetched\n")
    assert prepare("with-models", "v1", tmp_path) is True
    assert (directory / "models_were_fetched").exists()


def test_failing_prepare_script_is_reported(tmp_path):
    directory = new_service("broken", services_directory=tmp_path)
    (directory / "prepare.sh").write_text("exit 3\n")
    with pytest.raises(PreparationFailed):
        prepare("broken", "v1", tmp_path)
