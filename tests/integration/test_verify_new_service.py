import shutil
import subprocess

import pytest

from dsg.repository import EXPERIMENTS_DIRECTORY, SERVICES_DIRECTORY
from dsg.service_generator.builder import new_service
from dsg.service_generator.catalog import image_name
from dsg.service_verifier.verification import VERIFIED, status_of, verify

pytestmark = pytest.mark.integration

THROWAWAY_SERVICE = "zz-throwaway-skeleton"


@pytest.fixture
def throwaway_service():
    new_service(THROWAWAY_SERVICE)
    yield THROWAWAY_SERVICE
    shutil.rmtree(SERVICES_DIRECTORY / THROWAWAY_SERVICE, ignore_errors=True)
    (EXPERIMENTS_DIRECTORY / f"{THROWAWAY_SERVICE}-single.yaml").unlink(missing_ok=True)
    subprocess.run(["docker", "image", "rm", "-f", image_name(THROWAWAY_SERVICE, "v1")], capture_output=True)


def test_the_skeleton_from_new_service_is_verified_for_real_on_a_closed_network(throwaway_service):
    report = verify(throwaway_service, "v1")
    assert report["status"] == VERIFIED, report["failures"]
    assert status_of(throwaway_service, "v1") == VERIFIED
    assert report["behaviour"]["knobs"]["work_size"]["seen"] == "no effect on time"
    assert report["behaviour"]["notes"] == ["knob work_size has no effect on the processing time"]
    assert report["behaviour"]["flags"] == []
    assert report["behaviour"]["at_default"]["measured_items"] >= 30
    assert [run["status"] for run in report["runs"]] == ["verified"]
    assert report["behaviour"]["at_default"]["throttled_share_of_periods"] == 0
    assert (EXPERIMENTS_DIRECTORY / f"{throwaway_service}-single.yaml").exists()
