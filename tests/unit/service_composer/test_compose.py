from dsg.node import NodeSettings
from dsg.service_composer.compose import (
    NodeDeployment,
    compose_for_pipeline,
    container_name,
    control_url_on_the_host,
)

NODE = NodeSettings("2-15,18-31", "0-1,16-17", 18080, 18000)
QR = NodeDeployment("qr", "dsg/qr-detector:v1", 2.0, "4g", next_hops=["cv"], environment={"ARRIVAL_PROCESS": "poisson"})
CV = NodeDeployment("cv", "dsg/cv-analyzer:v1", 3.0, "8g")


def test_every_service_gets_its_own_limits_ports_and_records_folder(tmp_path):
    services = compose_for_pipeline([QR, CV], NODE, "dsg-test", tmp_path, "1003:1003")["services"]
    assert (services["qr"]["cpus"], services["qr"]["mem_limit"]) == (2.0, "4g")
    assert (services["cv"]["cpus"], services["cv"]["mem_limit"]) == (3.0, "8g")
    assert services["qr"]["cpuset"] == "2-15,18-31"
    assert services["qr"]["ports"] == ["127.0.0.1:18080:8080", "127.0.0.1:18000:8000"]
    assert services["cv"]["ports"] == ["127.0.0.1:18081:8080", "127.0.0.1:18001:8000"]
    assert services["qr"]["volumes"] == [f"{tmp_path / 'qr'}:/records"]
    assert services["cv"]["volumes"] == [f"{tmp_path / 'cv'}:/records"]
    assert control_url_on_the_host(NODE, 1) == "http://127.0.0.1:18081"


def test_a_service_is_told_who_comes_after_it(tmp_path):
    services = compose_for_pipeline([QR, CV], NODE, "dsg-test", tmp_path, "1:1")["services"]
    assert services["qr"]["environment"]["NEXT_HOPS"] == "http://cv:8080"
    assert services["cv"]["environment"]["NEXT_HOPS"] == ""
    assert services["qr"]["environment"]["NODE_NAME"] == "qr"
    assert services["qr"]["environment"]["CONTAINER_REF"] == container_name("dsg-test", "qr") == "dsg-test-qr"
    assert services["qr"]["environment"]["ARRIVAL_PROCESS"] == "poisson"


def test_without_network_every_service_sits_on_a_closed_network_behind_its_own_door(tmp_path):
    compose = compose_for_pipeline([QR, CV], NODE, "dsg-test", tmp_path, "1:1", without_network=True)
    assert "ports" not in compose["services"]["qr"]
    assert compose["services"]["qr"]["networks"] == ["closed"]
    assert compose["networks"]["closed"] == {"internal": True}
    assert compose["services"]["qr-door"]["ports"] == ["127.0.0.1:18080:8080"]
    assert compose["services"]["cv-door"]["ports"] == ["127.0.0.1:18081:8080"]
    assert "tcp-connect:cv:8080" in compose["services"]["cv-door"]["command"]
    assert compose["services"]["qr-door"]["cpuset"] == "0-1,16-17"
