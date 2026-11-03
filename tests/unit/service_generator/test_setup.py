from dsg.service_generator import setup
from dsg.service_generator.setup import FAILED, READY, set_up_every_service, setup_report


class FakeDocker:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.built = []

    def image_exists(self, image):
        return image in self.existing


def fake_builder(monkeypatch, prepared=(), tests_pass=True, build_fails=()):
    built = []

    def prepare(service, version):
        return service in prepared

    def build(service, version, docker):
        if service in build_fails:
            raise RuntimeError(f"pip could not install a package of {service}")
        built.append(service)
        return f"dsg/{service}:{version}"

    monkeypatch.setattr(setup.builder, "prepare", prepare)
    monkeypatch.setattr(setup.builder, "build", build)
    monkeypatch.setattr(setup.builder, "check", lambda service, version, docker, quietly=False: tests_pass)
    monkeypatch.setattr(setup, "list_services", lambda: [("qr-detector", "v1"), ("cv-analyzer", "v1")])
    return built


def test_every_service_is_fetched_built_and_checked(monkeypatch):
    built = fake_builder(monkeypatch, prepared=("cv-analyzer",))
    outcomes = set_up_every_service(FakeDocker(), lambda line: None)
    assert [outcome.outcome for outcome in outcomes] == [READY, READY]
    assert built == ["qr-detector", "cv-analyzer"]
    assert outcomes[0].fetched == "nothing to fetch" and outcomes[1].fetched == "fetched"
    assert "2 of 2 services ready" in setup_report(outcomes)


def test_an_image_that_exists_is_not_built_again_unless_asked(monkeypatch):
    built = fake_builder(monkeypatch)
    set_up_every_service(FakeDocker(existing={"dsg/qr-detector:v1"}), lambda line: None)
    assert built == ["cv-analyzer"]
    built.clear()
    set_up_every_service(FakeDocker(existing={"dsg/qr-detector:v1"}), lambda line: None, rebuild=True)
    assert built == ["qr-detector", "cv-analyzer"]


def test_a_service_that_fails_does_not_stop_the_others_and_is_named(monkeypatch):
    fake_builder(monkeypatch, build_fails=("qr-detector",))
    outcomes = set_up_every_service(FakeDocker(), lambda line: None)
    assert [outcome.outcome for outcome in outcomes] == [FAILED, READY]
    assert "pip could not install" in outcomes[0].problem
    assert "1 of 2 services ready" in setup_report(outcomes)
