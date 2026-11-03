# service_generator

**The procedures for generating services and applications with an assistant are in `procedures/` at the
repository root.** This package holds the code they call.

Turns a service folder into a checked image. Later this is also where generated services are written.

- `list_services()` — every `(service, version)` in `services/`.
- `new_service(name)` — writes a working skeleton: `brief.yaml`, `spec.yaml`, `service.py`, `test_service.py`, `requirements.txt`.
- `prepare(service, version)` — runs the service's own `prepare.sh` if it has one (model export, data download).
- `build(service, version, docker)` — builds `dsg/<service>:<version>` from `service.Dockerfile`.
- `check(service, version, docker)` — runs the service's own test inside its image.

`service.Dockerfile` is the one Dockerfile for every service. Its base image and system packages are the ones
from elastic-workbench.
